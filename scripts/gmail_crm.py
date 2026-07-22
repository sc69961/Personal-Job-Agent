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
    # ATS auto-confirmations — keep to catch applications Steve submitted
    # without sending a manual email (e.g. LinkedIn Easy Apply, direct ATS form)
    # Claude classifies these as 'applied', not 'response_received'
    'subject:("thank you for applying" OR "application received" OR "we received your application") newer_than:120d',
    # Interview requests
    'subject:(interview OR "next steps" OR "move forward" OR "schedule a call" OR "chat with") newer_than:120d',
    # Rejections — subject line signals
    'subject:("unfortunately" OR "not moving forward" OR "decided to" OR "other candidates" OR "position has been filled") newer_than:120d',
    # Rejections — body text signals (catches polite rejections that arrive as replies)
    '("not to advance" OR "not moving forward" OR "decided not to move" OR "not selected" OR "moving in a different direction" OR "not advance you" OR "not be moving forward") newer_than:120d',
    '("after careful deliberation" OR "after careful consideration" OR "we have decided" OR "difficult decision" OR "not the right fit") newer_than:120d',
    # Offers — require stronger signals than just "offer" (too many false positives)
    'subject:("offer letter" OR "job offer" OR "pleased to offer" OR "excited to offer you" OR "formal offer") newer_than:120d',
    '("we would like to offer you" OR "offer letter attached" OR "contingent offer" OR "total compensation" OR "start date") newer_than:120d',
]

# Status priority — higher index wins when merging
STATUS_PRIORITY = [
    "applied", "response_received", "interview_requested", "offer", "withdrawn", "rejected", "ghosted"
]

# Days of silence after which an "applied" entry is considered ghosted
GHOST_AFTER_DAYS = 30


# Generic email domains that are NOT company identifiers
_GENERIC_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "me.com", "aol.com", "protonmail.com", "live.com", "msn.com",
    # ATS / recruiting platforms — not company domains
    "greenhouse.io", "lever.co", "ashbyhq.com", "workday.com",
    "myworkdayjobs.com", "icims.com", "taleo.net", "successfactors.com",
    "smartrecruiters.com", "jobvite.com", "brassring.com", "kenexa.com",
    "recruitee.com", "bamboohr.com", "rippling.com", "workable.com",
    "linkedin.com", "indeed.com", "glassdoor.com",
}


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
# Domain-based matching helpers
# ---------------------------------------------------------------------------

def _extract_sender_domains(messages: list) -> set:
    """
    Pull unique company-owned email domains from all message senders.
    Excludes generic providers (Gmail, Yahoo) and ATS platforms (Greenhouse,
    Lever, Ashby) so we only match on real company domains.
    """
    domains = set()
    for msg in messages:
        headers = msg.get("payload", {}).get("headers", [])
        from_header = _header(headers, "from")
        # Extract address from "Name <addr@domain.com>" or "addr@domain.com"
        match = re.search(r'[\w.+-]+@([\w.-]+\.[a-zA-Z]{2,})', from_header)
        if match:
            domain = match.group(1).lower()
            if domain not in _GENERIC_DOMAINS:
                domains.add(domain)
    return domains


def _build_domain_map(app_by_id: dict) -> dict:
    """
    Build {email_domain: [app_id, ...]} from domains already stored on CRM entries.
    Used to match new threads to existing applications by recruiter email domain.
    """
    domain_map: dict = {}
    for app_id, app in app_by_id.items():
        for domain in app.get("sender_domains", []):
            domain_map.setdefault(domain, []).append(app_id)
    return domain_map


def _find_existing_by_domain(
    sender_domains: set, domain_map: dict, app_by_id: dict
) -> Optional[dict]:
    """
    Return the CRM entry whose stored sender domains intersect with the
    current thread's sender domains.  If multiple entries match (shouldn't
    happen often), prefer the one with the highest-priority status.
    """
    candidates = []
    for domain in sender_domains:
        for app_id in domain_map.get(domain, []):
            app = app_by_id.get(app_id)
            if app and app not in candidates:
                candidates.append(app)
    if not candidates:
        return None

    def status_rank(a):
        s = a.get("status", "applied")
        return STATUS_PRIORITY.index(s) if s in STATUS_PRIORITY else 0

    return sorted(candidates, key=status_rank, reverse=True)[0]


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
        # Persist the refreshed token so the next run (including GitHub Actions)
        # picks up the updated access token rather than re-fetching from Secrets.
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
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
    """Build a compact text summary of a thread for Claude.
    Processes up to 10 messages, 1500 chars each, newest-last so Claude
    sees the most recent reply (e.g. a rejection) in the final position.
    """
    parts = []
    for msg in messages[:10]:
        headers = msg.get("payload", {}).get("headers", [])
        subject = _header(headers, "subject")
        from_   = _header(headers, "from")
        date    = _header(headers, "date")
        body    = _extract_text(msg.get("payload", {}))[:1500]
        parts.append(f"From: {from_}\nDate: {date}\nSubject: {subject}\n{body}")
    return "\n---\n".join(parts)


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

def _analyze_thread(
    thread_text: str,
    client: Anthropic,
    active_applications: list = None,
) -> Optional[dict]:
    """
    Ask Claude to classify a Gmail thread.

    active_applications — list of dicts with keys: company, job_title, applied_date, status.
    When provided, Claude can identify which existing application a vague recruiter
    reply belongs to (e.g. "Following up" with no job title in the subject).

    Returns a dict, or None if the thread is not job-related.

    New fields in the returned dict:
      confidence      : int 0-100. How sure Claude is about the company/title/status.
      needs_review    : bool. True when confidence < 70 or the match is ambiguous.
      match_reasoning : str. Brief explanation of how Claude identified the match.
      matched_company : str or "". If Claude matched to an existing application,
                        the company name of that match.
      matched_title   : str or "". Same for job title.
    """
    # Build active applications context block
    if active_applications:
        app_lines = "\n".join(
            f"  - {a.get('company', '?')} | {a.get('job_title', '?')} "
            f"| applied {a.get('applied_date', '?')} | status: {a.get('status', '?')}"
            for a in active_applications
        )
        active_context = f"""
STEVE'S ACTIVE APPLICATIONS (use this to match vague recruiter emails to the right role):
{app_lines}

If this email is clearly about one of the above applications (even if the subject
doesn't name the role), set matched_company and matched_title to that entry.
If you can't confidently match it, leave them as empty strings.
"""
    else:
        active_context = ""

    prompt = f"""You are analyzing an email thread to determine if it's related to a job application.
{active_context}
EMAIL THREAD:
{thread_text[:3500]}

If this thread is NOT related to a job application, return exactly: null

If it IS job-related, return ONLY valid JSON (no markdown, no explanation):

{{
  "job_title": "<job title applied for — check the subject line, email body, and any 'Re:' lines. If you see a specific role name, use it. If you matched to an existing application, use that application's title. Only use empty string if truly impossible to determine>",
  "company": "<company name — strip legal suffixes like Inc, LLC, Corp from display but return the clean name>",
  "applied_date": "<YYYY-MM-DD when application was sent, or empty string>",
  "status": "<Choose ONE — read carefully:
    applied = Steve submitted an application OR the only reply is an automated ATS confirmation. Auto-confirmations include: 'Thank you for applying', 'We received your application', 'Your application has been submitted', 'Application received', noreply/donotreply sender addresses, or any email that is clearly a templated system message. These are NOT human responses — keep status as 'applied'.
    response_received = A REAL HUMAN at the company (recruiter, hiring manager) sent a personal reply that is NOT a template. The email must be clearly written for Steve specifically, not a form letter. Signs of a real human reply: personalized greeting, specific questions, scheduling language, signed with a person's name and title.
    interview_requested = An actual interview, phone screen, or hiring-manager call was explicitly scheduled or requested by a human.
    rejected = Company says they are NOT moving forward. ANY of these phrases = rejected: 'not to advance', 'not moving forward', 'decided not to', 'not the right fit', 'after careful deliberation', 'not selected', 'moving in a different direction', 'will not be proceeding', 'pursuing other candidates'. Use rejected even if earlier emails showed an interview.
    offer = Company sent an ACTUAL FORMAL JOB OFFER with specific salary numbers, start date, or benefits package in THIS email thread. A job description mentioning a salary range is NOT an offer. 'Thank you for applying' is NOT an offer. An ATS confirmation email is NOT an offer. Only use 'offer' if the email text explicitly says something like 'we would like to offer you the position' or 'offer letter attached'.
    withdrawn = Steve withdrew his application.>",
  "status_label": "<one of: Applied | Response Received | Interview Requested | Rejected | Offer Received | Withdrawn>",
  "last_activity": "<YYYY-MM-DD of the most recent email in thread>",
  "follow_up_date": "<YYYY-MM-DD — if no response yet, suggest following up in 7-10 business days from last_activity; if interview scheduled, put that date; if rejected or offer, leave empty>",
  "recommended_action": "<1 concise sentence: the single most important action Steve should take right now>",
  "confidence": <integer 0-100 — how confident are you in the company, job title, and status classification?
    90-100: subject line or body explicitly names the role and company; status signal is unambiguous
    70-89:  company is clear but role is inferred; or status has one ambiguous signal
    50-69:  role or company inferred from context; recruiter email with no explicit job reference
    below 50: guessing based on timing or partial signals — Steve should verify>,
  "needs_review": <true if confidence < 70 OR if there are multiple possible matching applications at the same company OR if the job title is empty>,
  "match_reasoning": "<1 sentence: how you identified which application this belongs to, or why you're uncertain>",
  "matched_company": "<if you matched this to one of Steve's existing applications, the company name — else empty string>",
  "matched_title": "<if you matched this to one of Steve's existing applications, the job title — else empty string>"
}}

IMPORTANT for job_title: Look carefully at the email subject lines (especially lines starting with 'Subject:', 'Re:', or 'Fwd:'). The role name is almost always mentioned. If the subject says 'Thank you for applying to Senior Product Manager at Acme', the job_title is 'Senior Product Manager'. Never leave job_title blank if the role name appears anywhere in the thread.
IMPORTANT for offer: Be very conservative. If you are not 100% certain this is a real offer letter (specific compensation, start date, or explicit 'we want to hire you'), use 'response_received' or 'interview_requested' instead. A false offer in the CRM is more damaging than a missed one."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.lower().startswith("null"):
            return None
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        # Ensure needs_review is set correctly even if Claude omitted it
        if "confidence" in result:
            if result["confidence"] < 70 or not result.get("job_title"):
                result["needs_review"] = True
        return result
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

    # Build domain → app_id map for recruiter email domain matching
    domain_map = _build_domain_map(app_by_id)

    processed = 0
    needs_review_count = 0

    # -----------------------------------------------------------------------
    # Pass 0: Re-scan existing active application threads for status updates.
    # This catches rejections/offers/new interview rounds that arrive as replies
    # to already-seen threads (e.g. interview thread → second-round invite in
    # same chain, or recruiter sends rejection as a reply).
    #
    # Cost control: rescan threads with last_activity within GHOST_AFTER_DAYS
    # (matching the ghost cutoff so we never skip a thread that is still
    # technically "active").  Previously used 14 days — too short; second-round
    # invites often arrive 3-5 weeks after the first interview request.
    # -----------------------------------------------------------------------
    RESCAN_STATUSES = {"applied", "response_received", "interview_requested"}
    rescan_cutoff = (datetime.now() - timedelta(days=GHOST_AFTER_DAYS)).strftime("%Y-%m-%d")
    for app in crm["applications"]:
        last_active = app.get("last_activity", "")
        if last_active and last_active < rescan_cutoff:
            continue  # beyond ghost window — skip rescan, save tokens
        if app.get("status") in RESCAN_STATUSES:
            for tid in app.get("thread_ids", []):
                try:
                    thread   = service.users().threads().get(userId="me", id=tid, format="full").execute()
                    messages = thread.get("messages", [])
                    # Only re-analyze if the thread has grown since last_activity
                    if not messages:
                        continue
                    latest_headers = messages[-1].get("payload", {}).get("headers", [])
                    latest_date    = _header(latest_headers, "date")
                    last_activity  = app.get("last_activity", "")
                    # Parse and compare dates
                    try:
                        from email.utils import parsedate_to_datetime
                        latest_dt = parsedate_to_datetime(latest_date)
                        last_dt   = datetime.fromisoformat(last_activity) if last_activity else None
                        if last_dt and latest_dt.date() <= last_dt.date():
                            continue  # no new messages, skip
                    except Exception:
                        pass  # can't parse dates — re-analyze anyway
                    summary = _summarize_thread(messages)
                    active_apps = [
                        {"company": a.get("company"), "job_title": a.get("job_title"),
                         "applied_date": a.get("applied_date"), "status": a.get("status")}
                        for a in crm["applications"]
                        if a.get("status") in RESCAN_STATUSES
                    ]
                    result  = _analyze_thread(summary, client, active_applications=active_apps)
                    if not result:
                        continue
                    new_status = result.get("status", "applied")
                    status_changed = _should_upgrade_status(app.get("status", "applied"), new_status)

                    # Always refresh mutable fields when the thread has new messages,
                    # even if the status didn't change (e.g. second-round interview
                    # invite keeps status = "interview_requested" but needs fresh
                    # last_activity, recommended_action, and follow_up_date).
                    if status_changed:
                        logger.info(f"  Thread rescan: {app.get('company')} '{app.get('job_title')}' "
                                    f"{app['status']} → {new_status} "
                                    f"(confidence {result.get('confidence', '?')})")
                        app["status"]       = new_status
                        app["status_label"] = result.get("status_label", app.get("status_label", ""))
                    else:
                        logger.info(f"  Thread rescan: {app.get('company')} '{app.get('job_title')}' "
                                    f"status unchanged ({app['status']}), refreshing activity fields")

                    # Refresh activity fields regardless of status change
                    app["last_activity"]      = result.get("last_activity", app.get("last_activity", ""))
                    app["notes"]              = result.get("notes", app.get("notes", ""))
                    app["recommended_action"] = result.get("recommended_action", app.get("recommended_action", ""))
                    app["follow_up_date"]     = result.get("follow_up_date", app.get("follow_up_date", ""))
                    app["confidence"]         = result.get("confidence", 80)
                    if result.get("needs_review"):
                        app["needs_review"]    = True
                        app["match_reasoning"] = result.get("match_reasoning", "")
                        needs_review_count += 1
                    processed += 1
                except Exception as e:
                    logger.debug(f"  Thread rescan failed for {tid}: {e}")

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

                thread   = service.users().threads().get(userId="me", id=tid, format="full").execute()
                messages = thread.get("messages", [])
                summary  = _summarize_thread(messages)

                # Extract company-owned sender domains from this thread
                thread_domains = _extract_sender_domains(messages)

                # Build active applications context for Claude
                active_apps = [
                    {"company": a.get("company"), "job_title": a.get("job_title"),
                     "applied_date": a.get("applied_date"), "status": a.get("status")}
                    for a in crm["applications"]
                    if a.get("status") not in ("rejected", "withdrawn", "ghosted")
                ]

                result = _analyze_thread(summary, client, active_applications=active_apps)

                if not result:
                    continue

                company    = result.get("company", "")
                job_title  = result.get("job_title", "")
                new_status = result.get("status", "applied")
                confidence = result.get("confidence", 80)
                flag_review = result.get("needs_review", False)
                reasoning  = result.get("match_reasoning", "")

                # ── Three-layer matching (most → least reliable) ──────────
                # 1. Recruiter email domain — catches recruiter replies on new
                #    threads that have no job title in the subject
                app = _find_existing_by_domain(thread_domains, domain_map, app_by_id)

                # 2. If Claude identified a specific existing application, honour it
                if not app:
                    m_co    = result.get("matched_company", "")
                    m_title = result.get("matched_title", "")
                    if m_co and m_title:
                        candidate_id = _app_id(m_co, m_title)
                        app = app_by_id.get(candidate_id)

                # 3. Exact company+title hash
                if not app:
                    aid = _app_id(company, job_title)
                    app = app_by_id.get(aid)

                # 4. Company-name-only fallback
                if not app:
                    app = _find_existing_by_company(company, app_by_id)

                if app:
                    # Merge sender domains into the matched entry so future
                    # recruiter replies on new threads are found by domain
                    existing_domains = set(app.get("sender_domains", []))
                    existing_domains.update(thread_domains)
                    app["sender_domains"] = list(existing_domains)
                    # Refresh domain map with newly discovered domains
                    for d in thread_domains:
                        domain_map.setdefault(d, [])
                        if app["id"] not in domain_map[d]:
                            domain_map[d].append(app["id"])

                    if _should_upgrade_status(app.get("status", "applied"), new_status):
                        app["status"]       = new_status
                        app["status_label"] = result.get("status_label", app["status_label"])
                        app["follow_up_date"]     = result.get("follow_up_date", app.get("follow_up_date", ""))
                        app["recommended_action"] = result.get("recommended_action", app.get("recommended_action", ""))

                    app["last_activity"] = result.get("last_activity", app.get("last_activity", ""))
                    app["confidence"]    = confidence

                    if not app.get("job_title") and job_title:
                        app["job_title"] = job_title
                    if not app.get("job_url"):
                        app["job_url"] = _try_match_url(company)
                    if flag_review:
                        app["needs_review"]    = True
                        app["match_reasoning"] = reasoning
                        needs_review_count += 1
                        logger.info(f"  ⚠ Low confidence ({confidence}) match: "
                                    f"{company} '{job_title}' — {reasoning}")
                    else:
                        app.pop("needs_review", None)
                        app.pop("match_reasoning", None)

                    app.setdefault("thread_ids", []).append(tid)

                else:
                    aid = _app_id(company, job_title)
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
                        "confidence":         confidence,
                        "needs_review":       flag_review,
                        "match_reasoning":    reasoning if flag_review else "",
                        "notes":              "",
                        "thread_ids":         [tid],
                        "sender_domains":     list(thread_domains),
                    }
                    if flag_review:
                        needs_review_count += 1
                        logger.info(f"  ⚠ New entry, low confidence ({confidence}): "
                                    f"{company} '{job_title}' — {reasoning}")
                    crm["applications"].append(new_app)
                    app_by_id[aid] = new_app
                    # Register domains for future matching
                    for d in thread_domains:
                        domain_map.setdefault(d, []).append(aid)

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
    review_note = f", {needs_review_count} need review ⚠" if needs_review_count else ""
    logger.info(f"CRM sync complete — {processed} new threads, {len(crm['applications'])} total applications{review_note}")
    return crm
