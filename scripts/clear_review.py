"""
clear_review.py — Clear the needs_review flag on CRM entries.

Usage:
  python3 scripts/clear_review.py               # clear ALL flagged entries
  python3 scripts/clear_review.py "Xcel Energy" "Meta"   # clear specific companies
"""

import json
import sys
import os

CRM_PATH = "./output/crm.json"

if not os.path.exists(CRM_PATH):
    print("crm.json not found — run main.py first")
    sys.exit(1)

with open(CRM_PATH) as f:
    crm = json.load(f)

apps = crm.get("applications", [])
flagged = [a for a in apps if a.get("needs_review")]

if not flagged:
    print("No entries need review.")
    sys.exit(0)

# If specific companies passed, only clear those
targets = [t.lower() for t in sys.argv[1:]]

cleared = []
for app in apps:
    if not app.get("needs_review"):
        continue
    co = app.get("company", "")
    if targets and co.lower() not in targets:
        continue
    app["needs_review"] = False
    app.pop("review_reason", None)
    cleared.append(co)

if not cleared:
    print(f"No matching entries found. Flagged companies: {[a['company'] for a in flagged]}")
    sys.exit(1)

with open(CRM_PATH, "w") as f:
    json.dump(crm, f, indent=2)

print(f"Cleared {len(cleared)} entr{'y' if len(cleared)==1 else 'ies'}:")
for co in cleared:
    print(f"  ✓ {co}")
print("\nRe-run main.py --dashboard to refresh the dashboard.")
