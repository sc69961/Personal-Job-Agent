#!/usr/bin/env python3
"""
patch_crm.py — One-time fix for the 14 needs_review items from the August 2026 CRM audit.

Resolutions applied:
  1.  BoxPower duplicates: merge "Box Power" (space variant) + blank EASI/Anderson entry
      into the canonical "BoxPower" entry. Confirmed active (interview stage, Anderson call).
  2.  Omnidian: status was "rejected" from a Voltus demographic survey email misattributed
      via the shared Lever ATS domain. Reset to "applied" (no actual rejection received).
  3.  Uplight (Predictive Controls): interview_requested from June is stale — Steve is
      pursuing Director of PD separately; this role is cold. Downgrade to ghosted.
  4.  Climatebase: email was a mass newsletter, not a personalized recruiter response.
      Keep status but confirm to stop re-flagging.
  5.  All remaining 9 items: confirmed applied/ghosted with user_confirmed=True.

Run from ~/Downloads/job-agent:  python3 patch_crm.py
Uploads the patched crm.json to S3 and saves it locally.
"""

import json
import os
import sys
import pickle
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

CRM_PATH = "output/crm.json"

# ── Load CRM ──────────────────────────────────────────────────────────────────
if not os.path.exists(CRM_PATH):
    sys.exit(f"CRM not found at {CRM_PATH} — run 'python3 main.py --dashboard --headless' first")

with open(CRM_PATH) as f:
    crm = json.load(f)

apps = crm.get("applications", [])
print(f"Loaded {len(apps)} CRM entries, {sum(1 for a in apps if a.get('needs_review'))} flagged for review\n")

# ── Helper: confirm an entry (suppress future review flags) ───────────────────
def confirm(app, *, status=None, notes=None):
    app["user_confirmed"] = True
    app.pop("needs_review", None)
    if status:
        app["status"] = status
        app["status_label"] = status.replace("_", " ").title()
    if notes:
        app["notes"] = notes
    return app

# ── Step 1: Find and merge BoxPower duplicates ────────────────────────────────
# Canonical entry: company=="BoxPower"
# Duplicates:  company=="Box Power" (with space), company=="" (EASI/Anderson email)

canonical_bp = next((a for a in apps if a.get("company") == "BoxPower" and a.get("needs_review")), None)
dupe_space   = next((a for a in apps if a.get("company") == "Box Power"), None)
dupe_blank   = next((a for a in apps if not a.get("company") and a.get("needs_review")), None)

if canonical_bp:
    # Merge thread IDs from duplicates into canonical
    existing_threads = set(canonical_bp.get("thread_ids", []))
    for dupe in [dupe_space, dupe_blank]:
        if dupe:
            for tid in dupe.get("thread_ids", []):
                existing_threads.add(tid)
    canonical_bp["thread_ids"] = list(existing_threads)
    # Confirm the canonical entry — active interview process, Anderson call scheduled
    confirm(canonical_bp, notes="Active: Alexander Asante call done 2026-08-19. Anderson Barkow call scheduled — final interview stage.")
    print(f"✅ BoxPower (canonical): confirmed interview_requested, merged threads from duplicates")

# Remove duplicate entries
removed = []
for dupe in [dupe_space, dupe_blank]:
    if dupe and dupe in apps:
        apps.remove(dupe)
        removed.append(dupe.get("company") or "(blank)")
if removed:
    print(f"   Removed duplicate entries: {removed}")

# ── Step 2: Fix Omnidian misattribution ───────────────────────────────────────
# The "rejected" status came from a Voltus demographic survey email routed through
# Lever ATS (shared domain noreply@hire.lever.co), not from Omnidian.
omnidian = next((a for a in apps if a.get("company") == "Omnidian" and a.get("needs_review")), None)
if omnidian:
    confirm(omnidian,
            status="applied",
            notes="Rejected status was a Voltus demographic survey misattributed via shared Lever ATS domain. No actual Omnidian rejection received. Status reset to applied.")
    print(f"✅ Omnidian: reset status rejected→applied (Voltus demographic survey misattribution fixed)")

# ── Step 3: Downgrade stale Uplight Predictive Controls ──────────────────────
uplight_pc = next(
    (a for a in apps if a.get("company") == "Uplight"
     and "predictive" in (a.get("job_title") or "").lower()
     and a.get("needs_review")), None
)
if uplight_pc:
    confirm(uplight_pc,
            status="ghosted",
            notes="Predictive Controls role is stale — no movement since June 2026 interview request. Steve is now pursuing Uplight Director of Product Development separately (applied 2026-07-07 via Jobvite). This thread is cold.")
    print(f"✅ Uplight Predictive Controls: downgraded interview_requested→ghosted (stale, pursuing Director separately)")

# ── Step 4–14: Confirm remaining review items ─────────────────────────────────
CONFIRMATIONS = {
    # (company_substr, title_substr): (status_override, notes)
    "Tremendous": (
        None,
        "Confirmed real rejection — Vault has Resume_PM2026_Tremendous.docx"
    ),
    "Engine": (
        None,
        "Confirmed applied — Vault has Resume_PM2026_Engine.docx (+ EngineX, EngineOmni)"
    ),
    "Xcel Energy": (
        None,
        "Confirmed ghosted — Vault has Resume_PM2026_Xcel.docx and XcelProductDev.docx"
    ),
    "Climatebase": (
        "response_received",
        "Email was a mass Climatebase newsletter, not a personalized recruiter response. Keeping response_received; confirmed to suppress future re-flagging."
    ),
    "Google": (
        None,
        "Confirmed ghosted — Vault has Resume_PM2026_Google.docx (+ GoogleFi, GoogleSustainability, GoogleUserVoice)"
    ),
    "Trystar": (
        None,
        "Confirmed ghosted — Vault has Resume_PM2026_Trystar.docx"
    ),
    "AIR Communities": (
        None,
        "Steve confirmed applied — Vault has Resume_PM2026_AIR.docx"
    ),
    "Volkswagen Group": (
        None,
        "Steve confirmed applied — no vault resume on file but Steve recalls applying"
    ),
    "Renew Home": (
        "applied",
        "Vault has Resume_TPM2026_Renew.docx — Steve applied for a TPM role (not the TIM title in CRM). Title corrected. Status was ghosted from old thread; resetting to applied since role mismatch was the source of confusion."
    ),
}

# Fix Renew Home title too
renew = next((a for a in apps if a.get("company") == "Renew Home" and a.get("needs_review")), None)
if renew:
    renew["job_title"] = "Senior Technical Program Manager, VPP"

for co_key, (status_override, notes) in CONFIRMATIONS.items():
    entry = next(
        (a for a in apps if co_key.lower() in (a.get("company") or "").lower() and a.get("needs_review")),
        None
    )
    if entry:
        confirm(entry, status=status_override, notes=notes)
        co = entry.get("company", co_key)
        st = status_override or entry.get("status", "?")
        print(f"✅ {co:30s}: confirmed {st}")
    else:
        # Already confirmed or not found
        pass

# ── Final count ───────────────────────────────────────────────────────────────
still_flagged = [a for a in apps if a.get("needs_review") and not a.get("user_confirmed")]
print(f"\nAfter patch: {len(still_flagged)} entries still need_review (not yet confirmed)")
for a in still_flagged:
    print(f"  - {a.get('company','?')} | {a.get('job_title','?')}")

crm["applications"] = apps
crm["last_patched"] = datetime.now().isoformat()

# ── Save locally ──────────────────────────────────────────────────────────────
with open(CRM_PATH, "w") as f:
    json.dump(crm, f, indent=2)
print(f"\n✅ crm.json saved locally ({len(apps)} entries)")

# ── Upload to S3 ──────────────────────────────────────────────────────────────
try:
    from config.config import (
        AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
        S3_BUCKET_NAME as BUCKET, AWS_REGION,
    )
    import boto3
    s3 = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )
    s3.put_object(
        Bucket=BUCKET,
        Key="crm.json",
        Body=json.dumps(crm, indent=2),
        ContentType="application/json",
    )
    print("✅ crm.json uploaded to S3")
except Exception as e:
    print(f"⚠  S3 upload skipped: {e}")
    print("   Run 'python3 scripts/s3_storage.py upload' or re-run after fixing config.")

print("""
Done. Next steps:
  1. Refresh the dashboard: python3 main.py --dashboard --headless
  2. Commit + push job-agent-cloud so the cloud CRM has the fix on the next sync.
  3. Run vault_sync_crm.py (separate script) to auto-confirm future applications.
""")
