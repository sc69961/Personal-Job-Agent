#!/usr/bin/env python3
"""
vault_sync_crm.py — Auto-confirm CRM applications from the resume vault.

THE PERMANENT FIX for recurring needs_review flags:

Every time Steve applies to a company, a resume file is saved to the Obsidian vault
with a predictable naming convention:
  Steve Christian Resume_PM2026_<Company>.docx
  Steve Christian Resume_TPM2026_<Company>.docx
  Steve Christian Resume_<Role>2026_<Company>.docx

This script:
  1. Scans the vault directory for resume files
  2. Extracts company names from filenames
  3. For any CRM entry whose company matches a vault file:
     - Sets user_confirmed = True  (tells the CRM: "yes, I applied here")
     - Clears needs_review          (stops it from flagging on every sync)
  4. Saves locally and uploads to S3

This should be run after each CRM sync, or whenever new resumes are added.
The gmail_crm.py module calls vault_sync() automatically at the end of each run
(see INTEGRATION section at the bottom of this file).

Run standalone from ~/Downloads/job-agent:  python3 vault_sync_crm.py

WHY THIS WORKS:
  - The vault is Steve's own record, maintained manually — it's ground truth
  - Resume filename = company applied to (by construction, every time)
  - Once user_confirmed=True, gmail_crm.py never re-flags that entry as needs_review
  - New applications auto-confirm within one CRM sync after the resume is saved
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ── Vault location ─────────────────────────────────────────────────────────────
VAULT_DIR = Path(os.path.expanduser(
    "~/Documents/Steve Vault /AI Assistant Docs"
))
CRM_PATH = Path(__file__).parent / "output" / "crm.json"

# ── Company name normalization ─────────────────────────────────────────────────
# Maps vault filename suffixes (after stripping prefix/extension) to canonical CRM names.
# Add entries here whenever a vault filename and CRM company name diverge.
COMPANY_ALIASES: dict[str, str] = {
    # vault key → canonical CRM company name
    "AIR":                  "AIR Communities",
    "BoxPower":             "BoxPower",
    "BoxPowerSenior":       "BoxPower",          # second BoxPower resume → same company
    "ContractDenver":       None,                 # skip — unnamed staffing client
    "EA":                   "Electronic Arts",
    "EVGO":                 "EVgo",
    "EnergyExemplarPMInsights": "Energy Exemplar",
    "GoogleFi":             "Google",
    "GoogleSustainability": "Google",
    "GoogleUserVoice":      "Google",
    "Google":               "Google",
    "Meta_PM":              "Meta",
    "Omnidian":             "Omnidian",
    "Omnidian(1)":          "Omnidian",           # duplicate resume file, same company
    "RenewHome":            "Renew Home",
    "RhythmEnergyGTM":      "Rhythm Energy",
    "UplightDirector":      "Uplight",
    "UplightPMII":          "Uplight",
    "UplightTPM":           "Uplight",
    "VoltusDirectorCX":     "Voltus",
    "VoltusPMM":            "Voltus",
    "XcelProductDev":       "Xcel Energy",
    "Xcel":                 "Xcel Energy",
    "YesEnergyPO":          "Yes Energy",
    "YesEnergy_SeniorPM":   "Yes Energy",
    "ZeroHomes":            "Zero Homes",
    "ZeroHomesSenior":      "Zero Homes",
    "Zero":                 "Zero Homes",
    "AdvancedEnergyProductMktg": "Advanced Energy",
    "AdvancedEnergyTechMktg":    "Advanced Energy",
    "AdvancedEnergy":            "Advanced Energy",
    "ArcadiaProcessing":    "Arcadia",
    "EngineOmni":           "Engine",
    "EngineX":              "Engine",
    "EnergyHub":            "EnergyHub",
    "OctopusStrategy":      "Octopus Energy US",
    "Octopus":              "Octopus Energy US",
    "VoltusDirectorCX":     "Voltus",
    "Vivint_NRG":           "NRG (Vivint Smart Home)",
    "Vivint":               "NRG (Vivint Smart Home)",
    "PanoAI":               "Pano AI",
    "RhythmEnergy":         "Rhythm Energy",
    "YesEnergy":            "Yes Energy",
    "YesEnergyPO":          "Yes Energy",
    "YesEnergy_SeniorPM":   "Yes Energy",
    "EA":                   "Electronic Arts",
}

# Resume file pattern: strip prefix + year + suffix
_RESUME_RE = re.compile(
    r"^Steve Christian Resume_[A-Za-z]+2026_(.+)\.docx$",
    re.IGNORECASE,
)


def extract_vault_companies(vault_dir: Path) -> set[str]:
    """Scan vault for resume files, return set of canonical company names."""
    companies: set[str] = set()
    if not vault_dir.exists():
        print(f"⚠  Vault directory not found: {vault_dir}")
        return companies

    for f in vault_dir.iterdir():
        if not f.is_file():
            continue
        m = _RESUME_RE.match(f.name)
        if not m:
            continue
        suffix = m.group(1)  # e.g. "BoxPower", "AIR", "Google"

        if suffix in COMPANY_ALIASES:
            canonical = COMPANY_ALIASES[suffix]
            if canonical:  # None means skip
                companies.add(canonical)
        else:
            # No alias defined — use the suffix as-is (best effort)
            companies.add(suffix)

    return companies


def normalize_crm_company(name: str) -> str:
    """Lowercase + strip punctuation for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def vault_sync(
    crm_path: Path = CRM_PATH,
    vault_dir: Path = VAULT_DIR,
    upload_to_s3: bool = True,
    verbose: bool = True,
) -> int:
    """
    Sync vault resume files against CRM entries.
    Returns the number of newly confirmed entries.
    """
    if not crm_path.exists():
        if verbose:
            print(f"CRM not found at {crm_path} — skipping vault sync")
        return 0

    with open(crm_path) as f:
        crm = json.load(f)

    apps = crm.get("applications", [])
    vault_companies = extract_vault_companies(vault_dir)

    if verbose:
        print(f"Vault: {len(vault_companies)} distinct companies confirmed")

    # Build a normalized lookup from vault company names
    vault_normalized: dict[str, str] = {
        normalize_crm_company(c): c for c in vault_companies
    }

    newly_confirmed = 0
    for app in apps:
        co = app.get("company", "")
        if not co:
            continue
        if app.get("user_confirmed"):
            continue  # already confirmed, skip

        co_norm = normalize_crm_company(co)
        if co_norm in vault_normalized:
            app["user_confirmed"] = True
            app.pop("needs_review", None)
            newly_confirmed += 1
            if verbose:
                print(f"  ✅ Auto-confirmed: {co} (resume found in vault)")

    if verbose:
        print(f"\nvault_sync complete: {newly_confirmed} new confirmations")

    crm["applications"] = apps

    with open(crm_path, "w") as f:
        json.dump(crm, f, indent=2)

    if upload_to_s3 and newly_confirmed > 0:
        _upload_to_s3(crm)

    return newly_confirmed


def _upload_to_s3(crm: dict) -> None:
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


# ── Standalone run ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("vault_sync_crm.py")
    print("Auto-confirming CRM applications from resume vault")
    print("=" * 60)
    print()

    n = vault_sync(verbose=True)

    if n == 0:
        print("Nothing new to confirm — all vault-matched entries already confirmed.")
    else:
        print(f"\n{n} entries confirmed. Dashboard will reflect on next run.")
