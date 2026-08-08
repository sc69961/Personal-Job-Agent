"""
resolve_review.py — Fix the 5 known needs_review items in crm.json.

Applies targeted corrections based on the actual email data, then
pushes the fixed crm.json to S3 and regenerates the dashboard.

Run from ~/Downloads/job-agent:
  python3 scripts/resolve_review.py
"""

import sys, os, json, hashlib
sys.path.insert(0, ".")

CRM_PATH = "./output/crm.json"

if not os.path.exists(CRM_PATH):
    print("crm.json not found — run main.py first")
    sys.exit(1)

with open(CRM_PATH) as f:
    crm = json.load(f)

apps = crm.setdefault("applications", [])
app_by_id   = {a["id"]: a for a in apps}
app_by_co   = {a["company"].lower(): a for a in apps}

def find(company):
    return app_by_co.get(company.lower())

def resolve(app, **overrides):
    """Clear review flag and set user_confirmed so the CRM won't re-raise it."""
    app["needs_review"]   = False
    app["user_confirmed"] = True
    app.pop("review_reason", None)
    for k, v in overrides.items():
        app[k] = v

changes = []

# ── 1. Phaidra — Staff PM ─────────────────────────────────────────────────────
a = find("Phaidra")
if a and a.get("needs_review"):
    resolve(a, status="applied", status_label="Applied",
            job_title=a.get("job_title") or "Staff Product Manager")
    changes.append("Phaidra — confirmed Applied/Staff PM, user_confirmed set")

# ── 2. Meta — title unknown ───────────────────────────────────────────────────
a = find("Meta")
if a and a.get("needs_review"):
    resolve(a, status="applied", status_label="Applied",
            job_title=a.get("job_title") or "Energy Portfolio Manager, Wholesale")
    changes.append("Meta — filled title 'Energy Portfolio Manager, Wholesale', user_confirmed set")

# ── 3. Xcel Energy — new role, CRM wrongly marked Ghosted ────────────────────
a = find("Xcel Energy")
if a and a.get("needs_review"):
    resolve(a, status="applied", status_label="Applied",
            job_title="Manager/Sr Manager, Product Portfolio",
            follow_up_date="2026-08-19",
            recommended_action="Wait for Xcel Energy to review your application; follow up in 10 business days.")
    changes.append("Xcel Energy — fixed to Applied, user_confirmed set")

# ── 4. Engine — two roles (Group PM Growth vs Staff PM Engine X) ─────────────
engine = find("Engine")
if engine and engine.get("needs_review"):
    resolve(engine)  # keep existing "Group Product Manager, Growth" entry as-is
    changes.append("Engine (Group PM Growth) — cleared review flag, user_confirmed set")
    # Add a second entry for the Staff PM / Engine X role from the ATS email
    new_id_eng = hashlib.md5(b"engine-staff-pm-enginex-2026").hexdigest()[:10]
    if not any(a.get("job_title","").startswith("Staff Product Manager") and a.get("company") == "Engine" for a in apps):
        apps.append({
            "id":                 new_id_eng,
            "company":            "Engine",
            "job_title":          "Staff Product Manager, Engine X",
            "job_url":            "https://job-boards.greenhouse.io/engine",
            "applied_date":       "",
            "status":             "applied",
            "status_label":       "Applied",
            "last_activity":      "2026-08-06",
            "follow_up_date":     "2026-08-18",
            "recommended_action": "Confirm which Engine role you applied to and follow up in 10 business days.",
            "notes":              "ATS confirmation email referenced 'Staff Product Manager, Engine X' — separate from Group PM Growth application.",
            "thread_ids":         [],
            "needs_review":       False,
            "user_confirmed":     True,
        })
        changes.append("Engine — added second entry for 'Staff Product Manager, Engine X'")

# ── 5. Omnidian (⚠) — email is actually from Zero Homes ─────────────────────
omnidian = find("Omnidian")
if omnidian and omnidian.get("needs_review"):
    stray_tid = omnidian.get("thread_ids", [])[-1] if omnidian.get("thread_ids") else None
    resolve(omnidian, status="rejected", status_label="Rejected",
            job_title="Senior Product Manager, Residential Business")
    changes.append("Omnidian — restored to Rejected, user_confirmed set")
    new_id_zh = hashlib.md5(b"zerohomes-senior-2026-08-04").hexdigest()[:10]
    if not any(a.get("job_title","").startswith("Senior") and a.get("company","").lower() == "zero homes" for a in apps):
        apps.append({
            "id":                 new_id_zh,
            "company":            "Zero Homes",
            "job_title":          "Senior Product Manager",
            "job_url":            "https://jobs.lever.co/zerohomes",
            "applied_date":       "2026-08-04",
            "status":             "applied",
            "status_label":       "Applied",
            "last_activity":      "2026-08-04",
            "follow_up_date":     "2026-08-18",
            "recommended_action": "Wait for Zero Homes to review your senior PM application; follow up in 10 business days.",
            "notes":              "New senior application (Aug 4 resume). Separate from rejected role (Jul 2026).",
            "thread_ids":         [stray_tid] if stray_tid else [],
            "needs_review":       False,
            "user_confirmed":     True,
        })
        changes.append("Zero Homes — created new Senior PM entry (Aug 4)")

# ── 6. Trystar — two different roles ─────────────────────────────────────────
trystar = find("Trystar")
if trystar and trystar.get("needs_review"):
    resolve(trystar)  # keep "Offering Manager IOI" as-is
    changes.append("Trystar (Offering Manager IOI) — user_confirmed set")
    new_id_ts = hashlib.md5(b"trystar-pm-npd-2026-08").hexdigest()[:10]
    if not any(a.get("job_title","").startswith("Product Manager - New") and a.get("company") == "Trystar" for a in apps):
        apps.append({
            "id":                 new_id_ts,
            "company":            "Trystar",
            "job_title":          "Product Manager - New Product Development",
            "job_url":            "https://www.linkedin.com/jobs/view/product-manager-new-product-development-at-trystar-4430030512",
            "applied_date":       "",
            "status":             "applied",
            "status_label":       "Applied",
            "last_activity":      "2026-08-06",
            "follow_up_date":     "2026-08-18",
            "recommended_action": "Confirm which Trystar role this email is for and follow up in 10 business days.",
            "notes":              "ADP confirmation email subject. May be separate from Offering Manager IOI application.",
            "thread_ids":         [],
            "needs_review":       False,
            "user_confirmed":     True,
        })
        changes.append("Trystar — added second entry for 'Product Manager - New Product Development'")

# ── Save ─────────────────────────────────────────────────────────────────────
with open(CRM_PATH, "w") as f:
    json.dump(crm, f, indent=2)

print(f"\nApplied {len(changes)} fix(es):")
for c in changes:
    print(f"  ✓ {c}")

# ── Push to S3 ───────────────────────────────────────────────────────────────
try:
    from config.config import S3_BUCKET_NAME, AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
    import boto3
    s3 = boto3.client("s3", region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
    s3.put_object(Bucket=S3_BUCKET_NAME, Key="crm.json",
        Body=json.dumps(crm, indent=2).encode())
    print(f"\nPushed to s3://{S3_BUCKET_NAME}/crm.json ✓")
except Exception as e:
    print(f"\nS3 push skipped ({e}) — run fix_crm_review.py or push manually")

print("\nNext: regenerate and deploy the dashboard:")
print("  python3 main.py --dashboard")
print("  cd ~/Downloads/job-agent-cloud && firebase deploy --only hosting:jobs")
