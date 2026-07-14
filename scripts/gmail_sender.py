"""
gmail_sender.py — Sends a daily digest email via Gmail SMTP (App Password).
No OAuth required — uses a Gmail App Password that never expires.
Generate one at: myaccount.google.com/apppasswords
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)

SCORE_COLOR = {
    "strong yes": ("#1a7a3a", "#d4f0df"),   # dark green text, light green bg
    "yes":        ("#1a5f7a", "#d4eaf5"),   # blue
    "maybe":      ("#7a5a1a", "#f5ebd4"),   # amber
    "no":         ("#7a1a1a", "#f5d4d4"),   # red
}

def score_badge_html(score: int, recommendation: str) -> str:
    rec = recommendation or "maybe"
    text_color, bg_color = SCORE_COLOR.get(rec, ("#444", "#eee"))
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
        f'font-size:13px;font-weight:bold;background:{bg_color};color:{text_color};">'
        f'{score}/100 — {rec.upper()}</span>'
    )

def job_card_html(job: dict, rank: int) -> str:
    badge = score_badge_html(job.get("score", 0), job.get("apply_recommendation", "maybe"))
    strengths = job.get("top_strengths", [])
    gaps = job.get("top_gaps", [])
    reasons = job.get("top_reasons", [])
    url = job.get("url", "#")
    company_tier = job.get("company_tier", "")
    tier_label = {"climatetech": "⚡ Climate/Energy", "fintech_ai": "🤖 Fintech/AI", "other": "🏢 Other"}.get(company_tier, "")
    target = " ✅ Target Co" if job.get("is_target_company") else ""

    confidence = job.get("confidence", 50)
    conf_color = "#1a7a3a" if confidence >= 80 else ("#7a5a1a" if confidence >= 55 else "#7a1a1a")

    strengths_html = "".join(f"<li>{s}</li>" for s in strengths)
    gaps_html = "".join(f"<li style='color:#888'>{g}</li>" for g in gaps) if gaps else ""
    reasons_html = "".join(f"<li>{r}</li>" for r in reasons) if reasons else ""

    return f"""
    <div style="border:1px solid #ddd;border-radius:8px;padding:18px;margin-bottom:16px;background:#fff;">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">
        <div>
          <span style="font-size:13px;color:#888;">#{rank}</span>
          <strong style="font-size:17px;margin-left:6px;">{job.get('title','')}</strong>
        </div>
        {badge}
      </div>
      <div style="color:#555;font-size:14px;margin-bottom:4px;">
        <strong>{job.get('company','')}</strong> &nbsp;·&nbsp; {job.get('location','')}
        &nbsp;&nbsp;<span style="color:#888;font-size:12px;">{tier_label}{target}</span>
      </div>
      <div style="font-size:12px;color:{conf_color};margin-bottom:6px;">🎯 {confidence}% confidence in this score</div>
      {f'<div style="color:#888;font-size:12px;margin-bottom:8px;">Salary: {job["salary_text"]}</div>' if job.get("salary_text") else ''}
      <p style="font-size:14px;color:#333;margin:8px 0 10px;">{job.get('match_summary','')}</p>
      {"<div style='font-size:12px;color:#888;margin-bottom:6px;'><strong style='color:#6b5e8a;'>📋 Why this score:</strong><ul style='margin:4px 0;padding-left:18px;'>" + reasons_html + "</ul></div>" if reasons else ""}
      {"<ul style='font-size:13px;margin:4px 0;padding-left:18px;color:#1a7a3a;'>" + strengths_html + "</ul>" if strengths else ""}
      {"<ul style='font-size:13px;margin:4px 0;padding-left:18px;'>" + gaps_html + "</ul>" if gaps else ""}
      <div style="margin-top:12px;display:flex;gap:10px;">
        <a href="{url}" style="display:inline-block;padding:7px 16px;background:#1a5f7a;color:#fff;border-radius:6px;text-decoration:none;font-size:13px;font-weight:bold;">View &amp; Apply →</a>
        <a href="mailto:steve.christianmba@gmail.com?subject=Cover letter: {job.get('title','')} @ {job.get('company','')}&body=Job URL: {url}" style="display:inline-block;padding:7px 16px;background:#f5f5f5;color:#333;border-radius:6px;text-decoration:none;font-size:13px;border:1px solid #ddd;">Draft Cover Letter</a>
      </div>
    </div>"""


def pipeline_summary_html(crm: dict) -> str:
    """Build a compact pipeline snapshot from the CRM dict."""
    apps = crm.get("applications", []) if crm else []
    if not apps:
        return ""

    status_counts = {}
    for a in apps:
        s = a.get("status", "applied")
        status_counts[s] = status_counts.get(s, 0) + 1

    active       = sum(status_counts.get(s, 0) for s in ("applied", "response_received", "interview_requested"))
    interviews   = status_counts.get("interview_requested", 0)
    offers       = status_counts.get("offer", 0)
    ghosted      = status_counts.get("ghosted", 0)
    total_sent   = len(apps) - status_counts.get("ghosted", 0)
    response_ct  = sum(status_counts.get(s, 0) for s in ("response_received", "interview_requested", "offer"))
    response_pct = round(response_ct / total_sent * 100) if total_sent else 0

    # Applications needing follow-up today
    from datetime import datetime as dt
    today = dt.now().strftime("%Y-%m-%d")
    followups = [
        a["company"] for a in apps
        if a.get("follow_up_date") and a.get("follow_up_date") <= today
        and a.get("status") not in ("ghosted", "rejected", "withdrawn", "offer")
    ]
    followup_html = ""
    if followups:
        items = "".join(f"<li style='margin:2px 0;'>{c}</li>" for c in followups[:5])
        more  = f" <span style='color:#888'>+{len(followups)-5} more</span>" if len(followups) > 5 else ""
        followup_html = f"""
        <div style="margin-top:10px;padding-top:10px;border-top:1px solid #dde3ea;">
          <div style="font-size:12px;font-weight:bold;color:#7a3a1a;margin-bottom:4px;">📅 Follow up today:</div>
          <ul style="font-size:12px;margin:0;padding-left:18px;color:#555;">{items}</ul>{more}
        </div>"""

    return f"""
    <div style="background:#fff;border:1px solid #dde3ea;border-radius:8px;padding:16px 20px;margin-bottom:16px;">
      <div style="font-size:13px;font-weight:bold;color:#1a3a5c;margin-bottom:10px;">📊 Pipeline Snapshot</div>
      <div style="display:flex;gap:20px;flex-wrap:wrap;">
        <div style="text-align:center;min-width:60px;">
          <div style="font-size:22px;font-weight:bold;color:#1a3a5c;">{active}</div>
          <div style="font-size:11px;color:#888;">Active</div>
        </div>
        <div style="text-align:center;min-width:60px;">
          <div style="font-size:22px;font-weight:bold;color:#1a7a3a;">{interviews}</div>
          <div style="font-size:11px;color:#888;">Interviews</div>
        </div>
        <div style="text-align:center;min-width:60px;">
          <div style="font-size:22px;font-weight:bold;color:#7a3a9a;">{offers}</div>
          <div style="font-size:11px;color:#888;">Offers</div>
        </div>
        <div style="text-align:center;min-width:60px;">
          <div style="font-size:22px;font-weight:bold;color:#1a5f7a;">{response_pct}%</div>
          <div style="font-size:11px;color:#888;">Response rate</div>
        </div>
        <div style="text-align:center;min-width:60px;">
          <div style="font-size:22px;font-weight:bold;color:#aaa;">{ghosted}</div>
          <div style="font-size:11px;color:#888;">Ghosted</div>
        </div>
      </div>
      {followup_html}
    </div>"""


def build_digest_html(jobs: list[dict], run_date: str, total_scraped: int, crm: dict = None) -> str:
    cards = "".join(job_card_html(job, i+1) for i, job in enumerate(jobs))
    pipeline = pipeline_summary_html(crm or {})
    return f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:660px;margin:30px auto;background:#f4f6f8;">

    <!-- Header -->
    <div style="background:#1a3a5c;padding:24px 28px;border-radius:8px 8px 0 0;">
      <h1 style="color:#fff;margin:0;font-size:20px;">🎯 Job Digest — {run_date}</h1>
      <p style="color:#a8c4dc;margin:6px 0 0;font-size:13px;">
        {total_scraped} jobs scraped · {len(jobs)} above fit threshold · sorted by score
      </p>
    </div>

    <!-- Body -->
    <div style="padding:20px 16px;">
      {pipeline}
      {cards}
    </div>

    <!-- Footer -->
    <div style="padding:16px 20px;background:#e8ecf0;border-radius:0 0 8px 8px;font-size:12px;color:#888;text-align:center;">
      Generated by your Job Agent · <a href="https://docs.google.com/spreadsheets" style="color:#1a5f7a;">View full Google Sheet</a>
    </div>
  </div>
</body>
</html>"""


def send_digest(
    jobs: list[dict],
    config: dict,
    total_scraped: int,
    credentials_path: str = None,   # kept for API compatibility, unused
    crm: dict = None,
) -> bool:
    """
    Send the daily digest email via Gmail SMTP using an App Password.
    App Passwords never expire — no OAuth tokens to manage.
    """
    app_password = config.get("GMAIL_APP_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD", "")
    if not app_password:
        logger.error(
            "GMAIL_APP_PASSWORD not set. "
            "Generate one at myaccount.google.com/apppasswords and add it to config.py "
            "and the GMAIL_APP_PASSWORD GitHub Secret."
        )
        return False

    run_date = datetime.now().strftime("%b %-d, %Y")
    top_jobs = jobs[:config.get("TOP_N_FOR_EMAIL", 10)]

    html_body = build_digest_html(top_jobs, run_date, total_scraped, crm=crm)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🎯 Job Digest {run_date} — Top {len(top_jobs)} matches"
    msg["From"]    = config["GMAIL_SENDER"]
    msg["To"]      = config["DIGEST_EMAIL_TO"]
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config["GMAIL_SENDER"], app_password)
            server.send_message(msg)
        logger.info(f"Digest email sent to {config['DIGEST_EMAIL_TO']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False
