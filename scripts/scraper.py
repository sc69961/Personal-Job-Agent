"""
scraper.py — Pulls job listings from Climatebase, LinkedIn search URLs,
and any custom RSS/JSON feeds you configure.

Sources:
  - Climatebase: public API (no auth needed)
  - LinkedIn: targeted search URL scraping (best-effort; uses BeautifulSoup)
  - Custom RSS: any job board that publishes an RSS feed
"""

import json
import re
import time
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional
import requests
from bs4 import BeautifulSoup

# ── Bypass macOS/system proxy settings that cause ProxyError ──
# Python's requests picks up System Preferences → Network → Proxies automatically.
# trust_env=False tells it to ignore those entirely.
_noproxy = requests.Session()
_noproxy.trust_env = False
requests.get  = _noproxy.get   # type: ignore[method-assign]
requests.post = _noproxy.post  # type: ignore[method-assign]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Salary extraction from description text
# ---------------------------------------------------------------------------

_SALARY_PATTERNS = [
    # "Compensation\n120,000 – 135,000 / year"  (Lever style)
    r'compensation[\s\n:]*\$?([\d,]+)\s*[-–—]\s*\$?([\d,]+)\s*(?:/\s*(?:year|yr|annual))?',
    # "$120,000 - $160,000 per year"
    r'\$\s*([\d,]+)\s*[-–—]\s*\$\s*([\d,]+)\s*(?:per\s+year|/\s*year|/\s*yr|annually)',
    # "120K - 160K"  or  "$120k–$160k"
    r'\$?\s*([\d]+)k\s*[-–—]\s*\$?\s*([\d]+)k',
    # "Base salary: $140,000"
    r'(?:base\s+)?salary[:\s]+\$?([\d,]+)(?:\s*[-–—]\s*\$?([\d,]+))?',
]

def _extract_salary_from_text(text: str) -> str:
    """
    Scan description text for a salary range and return a clean string like
    '$120,000–$135,000 / year', or '' if nothing found.
    """
    text_lower = text.lower()
    for pattern in _SALARY_PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            lo = m.group(1).replace(",", "")
            hi_raw = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            # Handle "k" suffix patterns (group values are already digits-only)
            if "k" in pattern:
                lo_val = int(lo) * 1000
                hi_val = int(hi_raw) * 1000 if hi_raw else None
            else:
                lo_val = int(lo)
                hi_val = int(hi_raw.replace(",", "")) if hi_raw else None
            if lo_val < 30_000:   # sanity: skip hourly/daily rates mistaken as annual
                continue
            if hi_val:
                return f"${lo_val:,}–${hi_val:,} / year"
            return f"${lo_val:,} / year"
    return ""

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

def make_job(
    title: str,
    company: str,
    location: str,
    url: str,
    description: str,
    source: str,
    salary_text: str = "",
    posted_date: str = "",
) -> dict:
    """Return a normalized job dict."""
    job_id = hashlib.md5(f"{company}_{title}_{url}".encode()).hexdigest()[:12]
    return {
        "id":           job_id,
        "title":        title.strip(),
        "company":      company.strip(),
        "location":     location.strip(),
        "url":          url.strip(),
        "description":  description.strip(),
        "source":       source,
        "salary_text":  salary_text.strip(),
        "posted_date":  posted_date or datetime.now().strftime("%Y-%m-%d"),
        "scraped_at":   datetime.now().isoformat(),
        "score":        None,   # filled in by scorer.py
        "score_reason": None,
        "cover_letter": None,
    }


# ---------------------------------------------------------------------------
# Climatebase scraper (public API, most reliable)
# ---------------------------------------------------------------------------

CLIMATEBASE_JOBS_URL = "https://climatebase.org/api/jobs/"

def _parse_climatebase_results(results: list, max_jobs: int) -> list[dict]:
    """Parse raw Climatebase API results into normalized job dicts."""
    jobs = []
    for item in results[:max_jobs]:
        title    = item.get("title", "")
        company  = item.get("company_name", item.get("company", {}).get("name", ""))
        location = item.get("location", "Remote")
        url      = item.get("url") or item.get("apply_url") or item.get("job_url", "")
        desc     = item.get("description") or item.get("short_description", "")
        salary   = item.get("salary") or item.get("compensation", "")
        posted   = item.get("posted_at", "")[:10] if item.get("posted_at") else ""
        if not (title and company):
            continue
        jobs.append(make_job(
            title=title, company=company, location=location,
            url=url, description=desc, source="climatebase",
            salary_text=str(salary), posted_date=posted,
        ))
    return jobs


def _scrape_climatebase_playwright(max_jobs: int = 50) -> list[dict]:
    """
    Playwright fallback for Climatebase — launches a real browser,
    waits for the jobs API response, and parses it.
    """
    from playwright.sync_api import sync_playwright
    jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        try:
            # Navigate and explicitly wait for the API response
            with page.expect_response(
                lambda r: "/api/jobs" in r.url and r.status == 200,
                timeout=20000
            ) as response_info:
                page.goto("https://climatebase.org/jobs?job_type=full-time", timeout=30000)

            api_response = response_info.value
            data = api_response.json()
            results = data.get("results", [])
            jobs = _parse_climatebase_results(results, max_jobs)
            logger.info(f"Climatebase (Playwright): fetched {len(jobs)} jobs")

        except Exception as e:
            logger.warning(f"Climatebase Playwright response wait failed: {e}")
            # Last resort: scrape visible job cards from the rendered HTML
            try:
                page.wait_for_selector(".job-card, [data-testid='job-card'], article", timeout=10000)
                html = page.content()
                soup = BeautifulSoup(html, "lxml")
                cards = soup.select(".job-card, [data-testid='job-card'], article")
                for card in cards[:max_jobs]:
                    title   = card.get_text(" ", strip=True)[:80]
                    link    = card.find("a")
                    url     = "https://climatebase.org" + link["href"] if link and link.get("href", "").startswith("/") else (link["href"] if link else "")
                    if title and url:
                        jobs.append(make_job(title=title, company="", location="", url=url, description="", source="climatebase"))
                if jobs:
                    logger.info(f"Climatebase (HTML fallback): found {len(jobs)} cards")
            except Exception as e2:
                logger.error(f"Climatebase HTML fallback failed: {e2}")
        finally:
            browser.close()

    return jobs


def scrape_climatebase(max_jobs: int = 50) -> list[dict]:
    """
    Pull jobs from Climatebase. Tries the direct API first;
    falls back to Playwright browser rendering if blocked.
    """
    params = {"page_size": min(max_jobs, 100), "ordering": "-posted_at", "job_type": "full-time"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://climatebase.org/jobs",
    }

    try:
        session = requests.Session()
        session.trust_env = False
        session.headers.update(headers)
        session.get("https://climatebase.org/jobs", timeout=15)
        time.sleep(1)
        resp = session.get(CLIMATEBASE_JOBS_URL, params=params, timeout=20)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        jobs = _parse_climatebase_results(results, max_jobs)
        logger.info(f"Climatebase: fetched {len(jobs)} jobs")
        return jobs
    except Exception as e:
        logger.warning(f"Climatebase direct API blocked ({e}) — trying Playwright...")

    try:
        return _scrape_climatebase_playwright(max_jobs)
    except Exception as e:
        logger.debug(f"Climatebase Playwright fallback failed: {e}")

    logger.info("Climatebase: all methods blocked — skipping (LinkedIn covers most of the same listings)")
    return []


# ---------------------------------------------------------------------------
# LinkedIn scraper (keyword search, best-effort HTML parse)
# ---------------------------------------------------------------------------

LINKEDIN_SEARCH_URLS = [
    # Energy / climate PM roles
    "https://www.linkedin.com/jobs/search/?keywords=product+manager+DER+energy&location=Denver%2C+CO&f_WT=2&f_TPR=r604800",
    "https://www.linkedin.com/jobs/search/?keywords=senior+product+manager+VPP+DERMS&location=United+States&f_WT=2&f_TPR=r604800",
    "https://www.linkedin.com/jobs/search/?keywords=product+manager+climate+tech&location=Denver%2C+CO&f_WT=2&f_TPR=r604800",
    # Fintech / AI PM roles
    "https://www.linkedin.com/jobs/search/?keywords=senior+product+manager+fintech&location=Denver%2C+CO&f_WT=2&f_TPR=r604800",
    "https://www.linkedin.com/jobs/search/?keywords=product+manager+AI+startup+remote&location=United+States&f_WT=2&f_TPR=r604800",
    # Broad senior PM remote
    "https://www.linkedin.com/jobs/search/?keywords=senior+product+manager&location=United+States&f_WT=2&f_TPR=r604800&f_E=4%2C5",
]

def scrape_linkedin(max_jobs: int = 50) -> list[dict]:
    """
    Scrape LinkedIn job search results pages.
    Note: LinkedIn rate-limits aggressively. This works for small daily volumes.
    If you get blocked consistently, add a rotating proxy (see SETUP.md).
    """
    jobs = []
    seen_ids = set()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    for url in LINKEDIN_SEARCH_URLS:
        if len(jobs) >= max_jobs:
            break
        try:
            time.sleep(3)  # be polite
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 429:
                logger.warning("LinkedIn rate-limited — waiting 60s")
                time.sleep(60)
                continue
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all("div", class_=lambda c: c and "job-search-card" in c)

            for card in cards:
                try:
                    title_el   = card.find("h3")
                    company_el = card.find("h4")
                    location_el= card.find("span", class_=lambda c: c and "location" in (c or ""))
                    link_el    = card.find("a", href=True)
                    posted_el  = card.find("time")

                    title    = title_el.get_text(strip=True) if title_el else ""
                    company  = company_el.get_text(strip=True) if company_el else ""
                    location = location_el.get_text(strip=True) if location_el else ""
                    link     = link_el["href"].split("?")[0] if link_el else ""
                    posted   = posted_el.get("datetime", "")[:10] if posted_el else ""

                    if not (title and company and link):
                        continue

                    job_id = hashlib.md5(f"{company}_{title}_{link}".encode()).hexdigest()[:12]
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    # Fetch full job description (throttled)
                    desc = _fetch_linkedin_job_description(link, headers)

                    jobs.append(make_job(
                        title=title, company=company, location=location,
                        url=link, description=desc, source="linkedin",
                        posted_date=posted,
                    ))

                    if len(jobs) >= max_jobs:
                        break

                except Exception as e:
                    logger.debug(f"Card parse error: {e}")

        except Exception as e:
            logger.error(f"LinkedIn search failed ({url[:60]}...): {e}")

    logger.info(f"LinkedIn: fetched {len(jobs)} jobs")
    return jobs


def _fetch_linkedin_job_description(url: str, headers: dict) -> str:
    """Fetch and parse a single LinkedIn job posting for its description."""
    try:
        time.sleep(2)
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        desc_el = (
            soup.find("div", class_=lambda c: c and "description" in (c or "")) or
            soup.find("section", class_=lambda c: c and "description" in (c or ""))
        )
        return desc_el.get_text(separator="\n", strip=True)[:3000] if desc_el else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Company career site scrapers (Greenhouse, Lever, Workable, Ashby, HTML)
# ---------------------------------------------------------------------------

# PM title keywords — only roles matching these are kept
_PM_KEYWORDS = [
    "product manager", "product management",
    "director of product", "director, product",
    "head of product",
    "vp of product", "vp, product", "vice president of product", "vice president, product",
    "principal product", "principal pm", "staff product", "group product",
    "product lead", "product owner",
    "chief product", "cpo",
]

def _is_pm_role(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _PM_KEYWORDS)


def _detect_ats(url: str) -> tuple:
    """Return (ats_type, slug_or_url) for a given career page URL."""
    if "apply.workable.com" in url:
        slug = url.split("apply.workable.com/")[1].strip("/").split("/")[0].split("?")[0]
        return ("workable", slug)
    if "jobs.lever.co" in url:
        slug = url.split("jobs.lever.co/")[1].strip("/").split("?")[0].split("/")[0]
        return ("lever", slug)
    if "jobs.ashbyhq.com" in url:
        slug = url.split("jobs.ashbyhq.com/")[1].strip("/").split("?")[0].split("/")[0]
        return ("ashby", slug)
    if "eu.greenhouse.io" in url:
        slug = url.rstrip("/").split("/")[-1].split("?")[0]
        return ("greenhouse_eu", slug)
    if "greenhouse.io" in url:
        slug = url.rstrip("/").split("/")[-1].split("?")[0]
        return ("greenhouse", slug)
    if "myworkdayjobs.com" in url:
        return ("workday", url)
    if ".bamboohr.com" in url:
        return ("bamboohr", url)
    if "ats.rippling.com" in url:
        return ("rippling", url)
    return ("html", url)


def _scrape_greenhouse(company: str, slug: str, eu: bool = False) -> list:
    base = "https://boards-api.eu.greenhouse.io" if eu else "https://boards-api.greenhouse.io"
    url = f"{base}/v1/boards/{slug}/jobs?content=true"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        jobs = []
        for job in data.get("jobs", []):
            title = job.get("title", "")
            if not _is_pm_role(title):
                continue
            offices = job.get("offices", [])
            location = offices[0].get("name", "Remote") if offices else "Remote"
            desc = BeautifulSoup(job.get("content", ""), "html.parser").get_text()
            jobs.append(make_job(
                title=title, company=company, location=location,
                url=job.get("absolute_url", ""), description=desc[:3000],
                source="company_site",
            ))
        logger.info(f"{company} (Greenhouse): {len(jobs)} PM roles")
        return jobs
    except Exception as e:
        logger.error(f"{company} Greenhouse scrape failed: {e}")
        return []


def _scrape_lever(company: str, slug: str) -> list:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        jobs = []
        for posting in data:
            title = posting.get("text", "")
            if not _is_pm_role(title):
                continue
            cats = posting.get("categories", {})
            location = cats.get("location") or (cats.get("allLocations") or ["Remote"])[0]
            desc = posting.get("descriptionPlain", "") or BeautifulSoup(
                posting.get("description", ""), "html.parser").get_text()
            salary_text = _extract_salary_from_text(desc)
            jobs.append(make_job(
                title=title, company=company, location=location,
                url=posting.get("hostedUrl", ""), description=desc[:3000],
                source="company_site", salary_text=salary_text,
            ))
        logger.info(f"{company} (Lever): {len(jobs)} PM roles")
        return jobs
    except Exception as e:
        logger.error(f"{company} Lever scrape failed: {e}")
        return []


def _scrape_workable(company: str, slug: str) -> list:
    url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
    try:
        resp = requests.post(
            url,
            json={"query": "", "location": [], "department": [], "worktype": [], "remote": []},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        jobs = []
        for job in data.get("results", []):
            title = job.get("title", "")
            if not _is_pm_role(title):
                continue
            loc_obj = job.get("location", {})
            location = loc_obj.get("city") or ("Remote" if job.get("remote") else "Unknown")
            shortcode = job.get("shortcode", "")
            job_url = f"https://apply.workable.com/{slug}/j/{shortcode}/"

            # The list endpoint returns stubs with no description — fetch the full JD
            description = job.get("description", "") or ""
            if not description and shortcode:
                try:
                    detail_resp = requests.get(
                        f"https://apply.workable.com/api/v3/accounts/{slug}/jobs/{shortcode}",
                        timeout=10,
                    )
                    if detail_resp.status_code == 200:
                        detail = detail_resp.json()
                        description = detail.get("description", "") or detail.get("content", "") or ""
                except Exception:
                    pass

            jobs.append(make_job(
                title=title, company=company, location=location,
                url=job_url, description=description[:3000],
                source="company_site",
            ))
        logger.info(f"{company} (Workable): {len(jobs)} PM roles")
        return jobs
    except Exception as e:
        logger.error(f"{company} Workable scrape failed: {e}")
        return []


def _scrape_ashby(company: str, slug: str) -> list:
    url = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams"
    payload = {
        "operationName": "ApiJobBoardWithTeams",
        "variables": {"organizationHostedJobsPageName": slug},
        "query": (
            "query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {"
            "  jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) {"
            "    jobPostings { id title locationName isRemote externalLink descriptionHtml }"
            "  }"
            "}"
        ),
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        postings = (resp.json().get("data", {}).get("jobBoard", {}) or {}).get("jobPostings", [])
        jobs = []
        for posting in postings:
            title = posting.get("title", "")
            if not _is_pm_role(title):
                continue
            location = posting.get("locationName") or ("Remote" if posting.get("isRemote") else "Unknown")
            desc = BeautifulSoup(posting.get("descriptionHtml", ""), "html.parser").get_text()
            salary_text = _extract_salary_from_text(desc)
            job_url = posting.get("externalLink") or f"https://jobs.ashbyhq.com/{slug}/{posting.get('id', '')}"
            jobs.append(make_job(
                title=title, company=company, location=location,
                url=job_url, description=desc[:3000],
                source="company_site", salary_text=salary_text,
            ))
        logger.info(f"{company} (Ashby): {len(jobs)} PM roles")
        return jobs
    except Exception as e:
        logger.error(f"{company} Ashby scrape failed: {e}")
        return []


def _scrape_workday(company: str, url: str) -> list:
    """
    Workday has a hidden JSON API — no JS rendering needed.
    URL format: https://{tenant}.wd{n}.myworkdayjobs.com/{board}
    """
    import re
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        host   = parsed.netloc  # e.g. stem.wd12.myworkdayjobs.com
        path   = parsed.path.strip("/")  # e.g. StemInc or en-US/fluenceenergy-jobs
        # Extract tenant from hostname
        tenant = host.split(".")[0]
        # Extract board — last path segment
        board  = path.split("/")[-1]
        api_url = f"https://{host}/wday/cxs/{tenant}/{board}/jobs"
        payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "product manager"}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        }
        resp = requests.post(api_url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        jobs = []
        for item in data.get("jobPostings", []):
            title = item.get("title", "")
            if not _is_pm_role(title):
                continue
            location  = item.get("locationsText", "Remote")
            job_path  = item.get("externalPath", "")
            job_url   = f"https://{host}{job_path}" if job_path else url
            posted    = item.get("postedOn", "")[:10] if item.get("postedOn") else ""
            jobs.append(make_job(
                title=title, company=company, location=location,
                url=job_url, description=item.get("jobReqId", ""),
                source="company_site", posted_date=posted,
            ))
        logger.info(f"{company} (Workday): {len(jobs)} PM roles")
        return jobs
    except Exception as e:
        logger.error(f"{company} Workday scrape failed: {e}")
        return []


def _scrape_bamboohr(company: str, url: str) -> list:
    """BambooHR public job embed API."""
    from urllib.parse import urlparse
    try:
        subdomain = urlparse(url).netloc.split(".")[0]
        api_url   = f"https://{subdomain}.bamboohr.com/jobs/embed2/?version=1.0.0"
        resp      = requests.get(api_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        jobs = []
        for li in soup.find_all("li"):
            a = li.find("a", href=True)
            if not a:
                continue
            title = a.get_text(strip=True)
            if not _is_pm_role(title):
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = f"https://{subdomain}.bamboohr.com{href}"
            dept = li.find("span", class_=lambda c: c and "department" in (c or ""))
            loc  = li.find("span", class_=lambda c: c and "location" in (c or ""))
            jobs.append(make_job(
                title=title, company=company,
                location=loc.get_text(strip=True) if loc else "See listing",
                url=href, description="", source="company_site",
            ))
        logger.info(f"{company} (BambooHR): {len(jobs)} PM roles")
        return jobs
    except Exception as e:
        logger.error(f"{company} BambooHR scrape failed: {e}")
        return []


def _scrape_rippling(company: str, url: str) -> list:
    """Rippling ATS — fetch JSON from their public jobs API."""
    from urllib.parse import urlparse
    try:
        # URL: https://ats.rippling.com/{slug}/jobs
        slug    = urlparse(url).path.strip("/").split("/")[0]
        api_url = f"https://api.rippling.com/platform/api/ats/public/jobs?companySlug={slug}"
        headers = {"Accept": "application/json",
                   "User-Agent": "Mozilla/5.0"}
        resp    = requests.get(api_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data    = resp.json()
        jobs    = []
        for item in (data if isinstance(data, list) else data.get("jobs", [])):
            title = item.get("name", "") or item.get("title", "")
            if not _is_pm_role(title):
                continue
            location = item.get("location", {})
            loc_str  = location.get("city", "") if isinstance(location, dict) else str(location)
            job_url  = item.get("jobPostUrl", "") or f"{url}/{item.get('id','')}"
            jobs.append(make_job(
                title=title, company=company, location=loc_str or "See listing",
                url=job_url, description=item.get("description", "")[:3000],
                source="company_site",
            ))
        logger.info(f"{company} (Rippling): {len(jobs)} PM roles")
        return jobs
    except Exception as e:
        logger.error(f"{company} Rippling scrape failed: {e}")
        return []


def _scrape_html_careers(company: str, url: str) -> list:
    """Generic HTML scraper — finds links whose text matches PM keywords."""
    from urllib.parse import urlparse
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        clean_url = url.split("#")[0]  # strip anchors before fetching
        resp = requests.get(clean_url, headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        parsed = urlparse(clean_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        jobs = []
        seen = set()
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            if not title or len(title) < 5 or len(title) > 120:
                continue
            if not _is_pm_role(title):
                continue
            href = a["href"]
            if href.startswith("/"):
                href = base + href
            elif not href.startswith("http"):
                continue
            if href in seen:
                continue
            seen.add(href)
            jobs.append(make_job(
                title=title, company=company, location="See listing",
                url=href, description="", source="company_site",
            ))
        logger.info(f"{company} (HTML): {len(jobs)} PM roles")
        return jobs
    except Exception as e:
        logger.error(f"{company} HTML scrape failed: {e}")
        return []


def scrape_company_sites(max_jobs: int = 200) -> list:
    """Scrape each company's career page directly using the best available method."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from config.target_companies import COMPANY_CAREER_URLS

    all_jobs = []
    for company, url in COMPANY_CAREER_URLS.items():
        try:
            time.sleep(1)
            ats_type, slug_or_url = _detect_ats(url)
            if ats_type == "greenhouse":
                batch = _scrape_greenhouse(company, slug_or_url, eu=False)
            elif ats_type == "greenhouse_eu":
                batch = _scrape_greenhouse(company, slug_or_url, eu=True)
            elif ats_type == "lever":
                batch = _scrape_lever(company, slug_or_url)
            elif ats_type == "workable":
                batch = _scrape_workable(company, slug_or_url)
            elif ats_type == "ashby":
                batch = _scrape_ashby(company, slug_or_url)
            elif ats_type == "workday":
                batch = _scrape_workday(company, slug_or_url)
            elif ats_type == "bamboohr":
                batch = _scrape_bamboohr(company, slug_or_url)
            elif ats_type == "rippling":
                batch = _scrape_rippling(company, slug_or_url)
            else:
                batch = _scrape_html_careers(company, slug_or_url)
            all_jobs.extend(batch)
        except Exception as e:
            logger.error(f"Company site scrape failed for {company}: {e}")

    logger.info(f"Company sites total: {len(all_jobs)} PM roles")
    return all_jobs


# ---------------------------------------------------------------------------
# Climate-focused job board scrapers
# ---------------------------------------------------------------------------

CLIMATE_JOB_BOARDS = [
    ("ClimateTechList",  "https://www.climatetechlist.com/jobs"),
    ("ClimatePeople",    "https://www.climatepeople.com/jobs"),
    ("ClimateDraft",     "https://jobs.climatedraft.org/jobs"),
    ("Terra.do",         "https://www.terra.do/climate-jobs/job-board/"),
]

def scrape_climate_boards(max_jobs: int = 100) -> list:
    """Scrape climate-focused job aggregator boards for PM roles."""
    from urllib.parse import urlparse
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    all_jobs = []
    for board_name, board_url in CLIMATE_JOB_BOARDS:
        try:
            time.sleep(2)
            resp = requests.get(board_url, headers=headers, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            parsed = urlparse(board_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            seen = set()
            board_jobs = []
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)
                if not title or len(title) < 5 or len(title) > 120:
                    continue
                if not _is_pm_role(title):
                    continue
                href = a["href"]
                if href.startswith("/"):
                    href = base + href
                elif not href.startswith("http"):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                # Try to find company name near the link
                parent = a.find_parent()
                company = ""
                if parent:
                    siblings = parent.find_all(string=True)
                    text_bits = [s.strip() for s in siblings if s.strip() and s.strip() != title]
                    company = text_bits[0] if text_bits else board_name
                board_jobs.append(make_job(
                    title=title, company=company or board_name,
                    location="See listing", url=href,
                    description="", source=board_name.lower().replace(".", "_"),
                ))
            logger.info(f"{board_name}: {len(board_jobs)} PM roles found")
            all_jobs.extend(board_jobs)
        except Exception as e:
            logger.error(f"{board_name} scrape failed: {e}")
    return all_jobs


# ---------------------------------------------------------------------------
# Custom RSS / JSON feed scraper
# ---------------------------------------------------------------------------

CUSTOM_FEEDS = [
    # Add any job board RSS feeds here. Format: (name, url, type)
]

def scrape_custom_feeds(max_jobs: int = 30) -> list:
    """Scrape any custom RSS or HTML job feeds you've configured."""
    return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def scrape_all(max_per_source: int = 50) -> list[dict]:
    """Run all scrapers and return a deduplicated merged job list."""
    all_jobs = []
    seen = set()

    for fetch_fn in [scrape_climatebase, scrape_linkedin, scrape_company_sites, scrape_climate_boards, scrape_custom_feeds]:
        try:
            batch = fetch_fn(max_jobs=max_per_source)
            for job in batch:
                if job["id"] not in seen:
                    seen.add(job["id"])
                    all_jobs.append(job)
        except Exception as e:
            logger.error(f"Scraper {fetch_fn.__name__} failed: {e}")

    logger.info(f"Total unique jobs scraped: {len(all_jobs)}")
    return all_jobs
