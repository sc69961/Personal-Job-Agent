"""
gmail_crm.py — Scrapes Gmail for job application threads, uses Claude to
classify status, and maintains output/crm.json as a persistent CRM store.
"""

import os
import re
import json
import pickle
import hashlib
from typing import Optional
import base64
import logging
from datetime import datetime, timedelta
from anthropic import Anthropic
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

CRM_PATH = "./output/crm.json"

# Gmail search queries — cast a wide net for anything job-related
GMAIL_SEARCH_QUERIES = [
    # Emails we sent that look like applications
    'from:me subject:(application OR "cover letter" OR resume OR "applied for") newer_than:120d',
    # Automated "thank you for applying" responses
    'subject:("thank you for applying" OR "application received" OR "we received your application") newer_than:120d',
    # Interview requests
    'subject:(interview OR "next steps" OR "move forward" OR "schedule a call" OR "chat with") newer_than:120d',
    # Rejections
    'subject:("unfortunately" OR "not moving forward" OR "decided to" OR "other candidates" OR "position has been filled") newer_than:120d',
    # Offers
    'subject:(offer OR "pleased to" OR "excited to offer") newer_than:120d',
]

# Status priority — higher index wins when merging
STATUS_PRIORITY = [
    "applied", "response_received", "interview_requested", "offer", "withdrawn", "rejected", "ghosted"
]

# Days of silence after which an "applied" entry is considered ghosted
GHOST_AFTER_DAYS = 30


# ---------------------------------------------------------------------------
# Company name normalization — strips legal suffixes so variants match
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = re.compile(
    r'\b(inc\.?|llc\.?|corp\.?|co\.?|ltd\.?|incorporated|limited|company)\b[\s,]*',
    flags=re.I
)

def _normalize_company(name: str) -> str:
    """Strip legal suffixes, punctuation, and extra spaces for fuzzy matching."""
    name = _LEGAL_SUFFIXES.sub('', name)
    name = re.sub(r'[^\w\s]', ' ', name)   # punctuation → space
    return ' '.join(name.lower().split())


def _app_id(company: str, job_title: str) -> str:
    """Generate a stable ID from normalized company + title."""
    norm_co    = _normalize_company(company)
    norm_title = job_title.lower().strip()
    return hashlib.md5(f"{norm_co}_{norm_title}".encode()).hexdigest()[:10]


def _find_existing_by_company(company: str, app_by_id: dict) -> Optional[dict]:
    """
    Find an existing CRM entry by normalized company name match.
    Used to catch status updates that arrive in separate email threads.
    Returns the best matching entry, or None.
    """
    norm = _normalize_company(company)
    if not norm:
        return None
    candidates = []
    for app in app_by_id.values():
        existing_norm = _normalize_company(app.get("company", ""))
        if existing_norm and existing_norm == norm:
            candidates.append(app)
    if not candidates:
        return None
    # Prefer the entry with the highest-priority status
    def status_rank(a):
        return STATUS_PRIORITY.index(a.get("status", "applied")) if a.get("status") in STATUS_PRIORITY else 0
    return sorted(candidates, key=status_rank, reverse=True)[0]


def _should_upgrade_status(current: str, new: str) -> bool:
    """Return True if new status is higher priority than current."""
    try:
        return STATUS_PRIORITY.index(new) > STATUS_PRIORITY.index(current)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------

def _get_gmail_service(credentials_path: str):
    token_path = credentials_path.replace("google_credentials.json", "google_token.pickle")
    creds = None
    if os.path.exists(token_path):
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds:
        raise RuntimeError("No Google token found. Run scripts/auth_google.py first.")
    return build("gmail", "v1", credentials=creds)


def _decode_body(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_text(payload: dict) -> str:
    """Recursively extract plain text from a Gmail message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        return _decode_body(payload.get("body", {}).get("data", ""))
    text = ""
    for part in payload.get("parts", []):
        text += _extract_text(part)
    return text


def _header(headers: list, name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _summarize_thread(messages: list) -> str:
    """Build a compact text summary of a thread for Claude."""
    parts = []
    for msg in messages[:6]:
        headers = msg.get("payload", {}).get("headers", [])
        subject = _header(headers, "subject")
        from_   = _header(headers, "from")
        date    = _header(headers, "date")
        body    = _extract_text(msg.get("payload", {}))[:600]
        parts.append(f"From: {from_}\nDate: {date}\nSubject: {subject}\n{body}")
    return "\n---\n".join(parts)


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

def _analyze_thread(thread_text: str, client: Anthropic):
    prompt = f"""You are analyzing an email thread to determine if it's related to a job application.

EMAIL THREAD:
{thread_text[:3500]}

If this thread is NOT related to a job application, return exactly: null

If it IS job-related, return ONLY valid JSON (no markdown, no explanation):

{{
  "job_title": "<job title applied for — check the subject line, email body, and any 'Re:' lines. If you see a specific role name, use it. Only use empty string if truly impossible to determine>",
  "company": "<company name — strip legal suffixes like Inc, LLC, Corp from display but return the clean name>",
  "applied_date": "<YYYY-MM-DD when application was sent, or empty string>",
  "status": "<one of: applied | response_received | interview_requested | rejected | offer | withdrawn>",
  "status_label": "<one of: Applied | Response Received | Interview Requested | Rejected | Offer Received | Withdrawn>",
  "last_activity": "<YYYY-MM-DD of the most recent email in thread>",
  "follow_up_date": "<YYYY-MM-DD — if no response yet, suggest following up in 7-10 business days from last_activity; if interview scheduled, put that date; if rejected or offer, leave empty>",
  "recommended_action": "<1 concise sentence: the single most important action Steve should take right now>"
}}

IMPORTANT for job_title: Look carefully at the email subject lines (especially lines starting with 'Subject:', 'Re:', or 'Fwd:'). The role name is almost always mentioned. If the subject says 'Thank you for applying to Senior Product Manager at Acme', the job_title is 'Senior Product Manager'. Never leave job_title blank if the role name appears anywhere in the thread."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.lower().startswith("null"):
            return None
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        logger.debug(f"Claude analysis failed: {e}")
        return None


# ---------------------------------------------------------------------------
# URL lookup
# ---------------------------------------------------------------------------

def _try_match_url(company: str) -> str:
    """Try to find a job URL from scored or raw results."""
    norm = _normalize_company(company)
    for path in ["./output/scored_jobs.json", "./output/raw_jobs.json"]:
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                jobs = json.load(f)
            for j in jobs:
                if _normalize_company(j.get("company", "")) == norm:
                    url = j.get("url", "")
                    if url:
                        return url
        except Exception:
            pass
    return ""


# ---------------------------------------------------------------------------
# CRM persistence
# ---------------------------------------------------------------------------

def load_crm() -> dict:
    if os.path.exists(CRM_PATH):
        with open(CRM_PATH) as f:
            return json.load(f)
    return {"applications": [], "last_synced": None}


def save_crm(crm: dict):
    os.makedirs(os.path.dirname(CRM_PATH), exist_ok=True)
    crm["last_synced"] = datetime.now().isoformat()
    with open(CRM_PATH, "w") as f:
        json.dump(crm, f, indent=2)


# ---------------------------------------------------------------------------
# Main sync
# ---------------------------------------------------------------------------

def sync_gmail_crm(config: dict) -> dict:
    """
    Pull Gmail threads, classify with Claude, merge into crm.json.
    Returns the updated CRM dict.
    """
    api_key = config.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    client  = Anthropic(api_key=api_key)
    service = _get_gmail_service(config["GOOGLE_CREDENTIALS_PATH"])
    crm     = load_crm()

    seen_thread_ids = {tid for app in crm["applications"] for tid in app.get("thread_ids", [])}
    app_by_id = {app["id"]: app for app in crm["applications"]}

    processed = 0

    for query in GMAIL_SEARCH_QUERIES:
        try:
            results = service.users().threads().list(
                userId="me", q=query, maxResults=40
            ).execute()
            threads = results.get("threads", [])
            logger.info(f"  Query returned {len(threads)} threads")

            for meta in threads:
                tid = meta["id"]
                if tid in seen_thread_ids:
                    continue
                seen_thread_ids.add(tid)

                thread  = service.users().threads().get(userId="me", id=tid, format="full").execute()
                summary = _summarize_thread(thread.get("messages", []))
                result  = _analyze_thread(summary, client)

                if not result:
                    continue

                company   = result.get("company", "")
                job_title = result.get("job_title", "")
                new_status = result.get("status", "applied")

                # Primary match: exact company+title hash
                aid = _app_id(company, job_title)

                if aid in app_by_id:
                    app = app_by_id[aid]
                else:
                    # Secondary match: same normalized company name (catches cross-thread status updates)
                    app = _find_existing_by_company(company, app_by_id)

                if app:
                    # Update mutable fields — only upgrade status, never downgrade
                    if _should_upgrade_status(app.get("status", "applied"), new_status):
                        app["status"]       = new_status
                        app["status_label"] = result.get("status_label", app["status_label"])
                    app["last_activity"]      = result.get("last_activity", app.get("last_activity", ""))
                    # Fill in missing job title if we now have one
                    if not app.get("job_title") and job_title:
                        app["job_title"] = job_title
                    # Fill in missing URL
                    if not app.get("job_url"):
                        app["job_url"] = _try_match_url(company)
                    if _should_upgrade_status(app.get("status", "applied"), new_status):
                        app["follow_up_date"]     = result.get("follow_up_date", app.get("follow_up_date", ""))
                        app["recommended_action"] = result.get("recommended_action", app.get("recommended_action", ""))
                    app.setdefault("thread_ids", []).append(tid)
                else:
                    new_app = {
                        "id":                 aid,
                        "job_title":          job_title,
                        "company":            company,
                        "job_url":            _try_match_url(company),
                        "applied_date":       result.get("applied_date", ""),
                        "status":             new_status,
                        "status_label":       result.get("status_label", "Applied"),
                        "last_activity":      result.get("last_activity", ""),
                        "follow_up_date":     result.get("follow_up_date", ""),
                        "recommended_action": result.get("recommended_action", ""),
                        "notes":              "",
                        "thread_ids":         [tid],
                    }
                    crm["applications"].append(new_app)
                    app_by_id[aid] = new_app

                processed += 1

        except Exception as e:
            logger.error(f"Gmail CRM query failed: {e}")

    # Auto-ghost: mark "applied" entries with no activity for 30+ days
    ghosted_count = 0
    cutoff = (datetime.now() - timedelta(days=GHOST_AFTER_DAYS)).strftime("%Y-%m-%d")
    for app in crm["applications"]:
        if app.get("status") == "applied":
            last = app.get("last_activity", "")
            if last and last < cutoff:
                app["status"]             = "ghosted"
                app["status_label"]       = "Ghosted"
                app["recommended_action"] = (
                    "No response after 30+ days — safe to consider closed. "
                    "Move on or send a brief reconnect if there's a strong relationship."
                )
                ghosted_count += 1
    if ghosted_count:
        logger.info(f"  → Auto-ghosted {ghosted_count} stale applications (no activity > {GHOST_AFTER_DAYS} days)")

    # Sort by last_activity descending
    crm["applications"].sort(key=lambda a: a.get("last_activity", ""), reverse=True)
    save_crm(crm)
    logger.info(f"CRM sync complete — {processed} new threads, {len(crm['applications'])} total applications")
    return crm
