"""
chunked_scrape.py — Time-budgeted, resumable scraping runner.

Each invocation processes tasks from a persistent queue (output/scrape_queue.json)
until TIME_BUDGET seconds elapse, appending newly found jobs to output/raw_jobs.json
(deduped by id). Run repeatedly until it reports queue empty.
"""
import os
import sys
import json
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("chunked_scrape")

from scripts import scraper
from config.target_companies import COMPANY_CAREER_URLS

QUEUE_PATH = "./output/scrape_queue.json"
RAW_PATH = "./output/raw_jobs.json"
TIME_BUDGET = float(os.environ.get("CHUNK_TIME_BUDGET", "34"))


def build_queue():
    tasks = []
    tasks.append({"type": "climatebase"})
    for name, url in scraper.CLIMATE_JOB_BOARDS:
        tasks.append({"type": "climate_board", "name": name, "url": url})
    for company, url in COMPANY_CAREER_URLS.items():
        tasks.append({"type": "company", "company": company, "url": url})
    for url in scraper.LINKEDIN_SEARCH_URLS:
        tasks.append({"type": "linkedin", "url": url})
    return tasks


def load_queue():
    if os.path.exists(QUEUE_PATH):
        with open(QUEUE_PATH) as f:
            return json.load(f)
    q = build_queue()
    save_queue(q)
    return q


def save_queue(q):
    with open(QUEUE_PATH, "w") as f:
        json.dump(q, f, indent=2)


def load_raw():
    if os.path.exists(RAW_PATH):
        with open(RAW_PATH) as f:
            return json.load(f)
    return []


def save_raw(jobs):
    with open(RAW_PATH, "w") as f:
        json.dump(jobs, f, indent=2)


def run_task(task):
    """Return list of job dicts for a single scrape task."""
    t = task["type"]
    try:
        if t == "climatebase":
            return scraper.scrape_climatebase(max_jobs=50)
        elif t == "climate_board":
            # inline single-board scrape (reuse logic from scrape_climate_boards)
            import requests
            from bs4 import BeautifulSoup
            from urllib.parse import urlparse
            headers = {
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
                "Accept-Language": "en-US,en;q=0.9",
            }
            board_name, board_url = task["name"], task["url"]
            resp = requests.get(board_url, headers=headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            parsed = urlparse(board_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            seen, board_jobs = set(), []
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)
                if not title or len(title) < 5 or len(title) > 120:
                    continue
                if not scraper._is_pm_role(title):
                    continue
                href = a["href"]
                if href.startswith("/"):
                    href = base + href
                elif not href.startswith("http"):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                board_jobs.append(scraper.make_job(
                    title=title, company=board_name, location="See listing",
                    url=href, description="", source=board_name.lower().replace(".", "_"),
                ))
            return board_jobs
        elif t == "company":
            company, url = task["company"], task["url"]
            ats_type, slug_or_url = scraper._detect_ats(url)
            if ats_type == "greenhouse":
                return scraper._scrape_greenhouse(company, slug_or_url, eu=False)
            elif ats_type == "greenhouse_eu":
                return scraper._scrape_greenhouse(company, slug_or_url, eu=True)
            elif ats_type == "lever":
                return scraper._scrape_lever(company, slug_or_url)
            elif ats_type == "workable":
                return scraper._scrape_workable(company, slug_or_url)
            elif ats_type == "ashby":
                return scraper._scrape_ashby(company, slug_or_url)
            elif ats_type == "workday":
                return scraper._scrape_workday(company, slug_or_url)
            elif ats_type == "bamboohr":
                return scraper._scrape_bamboohr(company, slug_or_url)
            elif ats_type == "rippling":
                return scraper._scrape_rippling(company, slug_or_url)
            elif ats_type == "icims":
                return scraper._scrape_icims(company, slug_or_url)
            else:
                return scraper._scrape_html_careers(company, slug_or_url)
        elif t == "linkedin":
            # Single-URL LinkedIn scrape, skip per-job description fetch to save time budget
            import requests
            from bs4 import BeautifulSoup
            import hashlib
            headers = {
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
                "Accept-Language": "en-US,en;q=0.9",
            }
            resp = requests.get(task["url"], headers=headers, timeout=15)
            if resp.status_code == 429:
                return []
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all("div", class_=lambda c: c and "job-search-card" in c)
            jobs = []
            for card in cards:
                title_el = card.find("h3")
                company_el = card.find("h4")
                location_el = card.find("span", class_=lambda c: c and "location" in (c or ""))
                link_el = card.find("a", href=True)
                title = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                location = location_el.get_text(strip=True) if location_el else ""
                link = link_el["href"].split("?")[0] if link_el else ""
                if not (title and company and link):
                    continue
                jobs.append(scraper.make_job(
                    title=title, company=company, location=location,
                    url=link, description="", source="linkedin",
                ))
            return jobs
    except Exception as e:
        logger.error(f"Task {task} failed: {e}")
        return []
    return []


def main():
    start = time.time()
    queue = load_queue()
    raw_jobs = load_raw()
    seen_ids = {j["id"] for j in raw_jobs}

    done_count = 0
    remaining = []
    for i, task in enumerate(queue):
        if time.time() - start > TIME_BUDGET:
            remaining = queue[i:]
            break
        label = task.get("company") or task.get("name") or task.get("url", task["type"])[:60] or task["type"]
        jobs = run_task(task)
        new = 0
        for j in jobs:
            if j["id"] not in seen_ids:
                seen_ids.add(j["id"])
                raw_jobs.append(j)
                new += 1
        done_count += 1
        logger.info(f"[{task['type']}] {label} -> {len(jobs)} found, {new} new (total raw={len(raw_jobs)})")
    else:
        remaining = []

    save_raw(raw_jobs)
    save_queue(remaining)

    print(f"CHUNK_RESULT tasks_done={done_count} tasks_remaining={len(remaining)} total_raw_jobs={len(raw_jobs)} elapsed={time.time()-start:.1f}s")


if __name__ == "__main__":
    main()
