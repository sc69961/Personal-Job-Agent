#!/usr/bin/env python3
"""
send_morning_brief.py — Email the morning job review brief.

Runs after the daily job agent completes. Reads scored_jobs.json + crm.json
(from S3), generates the brief via morning_jobs_brief.py, and sends it to
Steve via Gmail SMTP (same app password already used for the daily digest).

Skips silently if there are no new roles to surface (avoids empty-brief spam).
"""

import os
import sys
import smtplib
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import the brief generator ────────────────────────────────────────────────
from scripts.morning_jobs_brief import run as generate_brief

# ── Config ────────────────────────────────────────────────────────────────────
RECIPIENT   = "sc69961@gmail.com"
SENDER      = "sc69961@gmail.com"
SMTP_HOST   = "smtp.gmail.com"
SMTP_PORT   = 587
MIN_SCORE   = 65
LOOKBACK    = 7  # days

def _get_app_password() -> str:
    pw = os.environ.get("GMAIL_APP_PASSWORD", "")
    if pw:
        return pw
    try:
        from config.config import GMAIL_APP_PASSWORD
        return GMAIL_APP_PASSWORD
    except Exception:
        return ""


def _markdown_to_html(md: str) -> str:
    """Very lightweight Markdown → HTML for the email body."""
    lines = md.split("\n")
    html_lines = []
    for line in lines:
        # Headers
        if line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            html_lines.append(f"<h2 style='margin-top:24px;border-bottom:1px solid #e0e0e0;padding-bottom:4px'>{line[3:]}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1 style='color:#1a73e8'>{line[2:]}</h1>")
        # Blockquotes
        elif line.startswith("> "):
            html_lines.append(f"<blockquote style='border-left:3px solid #ccc;margin:8px 0;padding:4px 12px;color:#555'>{line[2:]}</blockquote>")
        # Horizontal rule
        elif line.strip() == "---":
            html_lines.append("<hr style='border:none;border-top:1px solid #e0e0e0;margin:20px 0'>")
        # List items
        elif line.startswith("- "):
            html_lines.append(f"<li>{line[2:]}</li>")
        # Bold inline
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            html_lines.append(f"<p style='margin:4px 0'>{line}</p>")

    # Process inline bold: **text** → <strong>text</strong>
    html = "\n".join(html_lines)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    # Italics: *text* → <em>text</em>
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    # Links: [text](url) → <a>
    html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)

    return f"""
    <html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                        max-width: 680px; margin: 0 auto; padding: 20px; color: #333">
    {html}
    <hr style="border:none;border-top:1px solid #e0e0e0;margin-top:32px">
    <p style="font-size:12px;color:#999">
      Job Agent · <a href="https://stevechristianmba-jobs.web.app">Open Dashboard</a>
    </p>
    </body></html>
    """


def send_brief() -> bool:
    brief_md = generate_brief(min_score=MIN_SCORE, lookback_days=LOOKBACK)

    # Skip if no new roles
    if "No new high-scored roles" in brief_md:
        print("No new roles to surface — skipping email.")
        return False

    # Count roles found
    review_count = brief_md.count("### ")
    quick_count  = len([l for l in brief_md.split("\n") if l.startswith("- ") and "Score:" in l])

    today        = datetime.now().strftime("%a %b %-d")
    subject      = f"☀️ Job Review — {today} ({review_count} to review, {quick_count} quick apply)"

    html_body = _markdown_to_html(brief_md)

    app_pw = _get_app_password()
    if not app_pw:
        print("ERROR: GMAIL_APP_PASSWORD not set — cannot send email.")
        sys.exit(1)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER
    msg["To"]      = RECIPIENT
    msg.attach(MIMEText(brief_md, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER, app_pw)
        server.sendmail(SENDER, RECIPIENT, msg.as_string())

    print(f"✅ Morning brief sent to {RECIPIENT} ({review_count} review roles, {quick_count} quick apply)")
    return True


if __name__ == "__main__":
    send_brief()
