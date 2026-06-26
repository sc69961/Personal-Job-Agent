# Job Agent — Setup Guide

This guide gets you from zero to a running daily job agent in about 30 minutes.

---

## What you need before starting

- Python 3.11+ installed
- An Anthropic API key (get one at console.anthropic.com)
- A Google account (for Sheets + Gmail)

---

## Step 1 — Install Python dependencies

```bash
cd job-agent/
pip install -r requirements.txt
```

---

## Step 2 — Set your Anthropic API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

To make this permanent, add it to your shell profile (`~/.zshrc` or `~/.bash_profile`):
```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc
source ~/.zshrc
```

Cost estimate: a daily run scoring ~100 jobs costs roughly **$0.05–0.15/day** using claude-haiku.

---

## Step 3 — Google Credentials (for Sheets + Gmail)

You have two options. **Option A** is easier for personal use.

### Option A: OAuth2 (recommended for personal Gmail)

1. Go to https://console.cloud.google.com
2. Create a new project (name it "Job Agent")
3. Enable these APIs:
   - Google Sheets API
   - Gmail API
4. Go to **Credentials → Create Credentials → OAuth client ID**
5. Application type: **Desktop app**
6. Download the JSON file and save it as `config/google_credentials.json`
7. Run the auth helper once (it opens a browser window):
   ```bash
   python scripts/auth_google.py
   ```
   This saves a token file and you won't need to re-auth for 7 days.

### Option B: Service Account (for automation/cron)

1. Go to https://console.cloud.google.com
2. Create a new project → Enable Google Sheets API + Gmail API
3. Go to **Credentials → Create Credentials → Service Account**
4. Name it "job-agent" → Grant "Editor" role
5. Click the service account → **Keys → Add Key → Create new key → JSON**
6. Save the downloaded JSON as `config/google_credentials.json`
7. **Important for Gmail**: Service accounts can't send Gmail directly without
   Google Workspace domain-wide delegation. For personal Gmail, use Option A.

---

## Step 4 — Create your Google Sheet

1. Go to https://sheets.google.com
2. Create a new blank spreadsheet
3. Name it "Job Agent Results"
4. Copy the Sheet ID from the URL:
   `https://docs.google.com/spreadsheets/d/THIS_IS_YOUR_SHEET_ID/edit`
5. Paste it into `config/config.py`:
   ```python
   GOOGLE_SHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
   ```

If using a service account (Option B), also share the Sheet with your
service account email (ends in @...iam.gserviceaccount.com) with Editor access.

---

## Step 5 — OAuth helper script (Option A only)

Create this file to handle the OAuth2 flow:

```python
# scripts/auth_google.py
from google_auth_oauthlib.flow import InstalledAppFlow
import pickle, os

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

flow = InstalledAppFlow.from_client_secrets_file("config/google_credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

with open("config/google_token.pickle", "wb") as f:
    pickle.dump(creds, f)
print("✅ Google auth saved to config/google_token.pickle")
```

Run it once:
```bash
python scripts/auth_google.py
```

Then update `sheets_writer.py` and `gmail_sender.py` to use the pickle token
instead of service account (see the OAuth2 section at the bottom of this guide).

---

## Step 6 — Customize your target companies

Open `config/target_companies.py` and edit the lists to match your exact 60
companies. The file is organized by tier — climatetech companies get a score
bonus over general fintech/AI companies.

---

## Step 7 — Test with a dry run

```bash
python main.py --dry-run
```

This scrapes and scores jobs but doesn't write to Sheets or send email.
Review the output to make sure scores look reasonable.

---

## Step 8 — Full run

```bash
python main.py
```

You should see:
- Jobs scraped from Climatebase and LinkedIn
- Each job scored (printed to terminal)
- Results written to your Google Sheet
- Digest email sent to your Gmail

---

## Step 9 — Generate an application package

```bash
# See all available jobs
python scripts/apply.py --list

# Generate cover letter + short answers for a specific job
python scripts/apply.py --job-id abc123def456
```

Files are saved to `output/<company>_<title>_<id>/`.

---

## Step 10 — Schedule daily runs (optional)

### Mac/Linux — cron
```bash
crontab -e
```
Add this line to run every weekday at 7:30am:
```
30 7 * * 1-5 cd /path/to/job-agent && /usr/bin/python3 main.py >> output/cron.log 2>&1
```

### GitHub Actions (free, cloud-based)
Create `.github/workflows/job-agent.yml` — see the template in the repo.
Store your `ANTHROPIC_API_KEY` as a GitHub Secret.

---

## Troubleshooting

**"No jobs found from LinkedIn"**
LinkedIn blocks scrapers intermittently. Run again later, or reduce the number
of LinkedIn search URLs in `scraper.py`. Climatebase is more reliable.

**"Gmail auth failed"**
Personal Gmail requires OAuth2 (Option A). Service accounts only work with
Google Workspace accounts that have domain-wide delegation enabled.

**Scores seem too low/high**
Adjust `MIN_SCORE_TO_INCLUDE` and `SCORE_WEIGHTS` in `config/config.py`.
Run `--dry-run` to see scores before committing to a setting.

**"Module not found"**
Make sure you ran `pip install -r requirements.txt` in the job-agent directory.

---

## Gmail OAuth2 mode (for sheets_writer.py and gmail_sender.py)

If you used Option A (OAuth2), replace the `get_sheets_client()` function in
`sheets_writer.py` with:

```python
def get_sheets_client(credentials_path: str):
    import gspread, pickle
    with open("config/google_token.pickle", "rb") as f:
        creds = pickle.load(f)
    return gspread.authorize(creds)
```

And replace the Gmail auth block in `gmail_sender.py` with:
```python
import pickle
with open("config/google_token.pickle", "rb") as f:
    creds = pickle.load(f)
service = build("gmail", "v1", credentials=creds)
```

---

## File structure

```
job-agent/
├── main.py                    ← Run this daily
├── requirements.txt
├── SETUP.md                   ← This file
├── config/
│   ├── config.py              ← Your settings + resume
│   ├── target_companies.py    ← Your 60 companies
│   └── google_credentials.json  ← You create this
├── scripts/
│   ├── scraper.py             ← Pulls jobs from Climatebase + LinkedIn
│   ├── scorer.py              ← Claude scoring engine
│   ├── sheets_writer.py       ← Google Sheets integration
│   ├── gmail_sender.py        ← Email digest
│   ├── apply.py               ← Application package generator
│   └── auth_google.py         ← OAuth2 helper (create once)
└── output/
    ├── raw_jobs.json          ← Last scrape
    ├── scored_jobs.json       ← Last scored results
    ├── job_agent.log          ← Run history
    └── <company>_<title>/     ← Application packages
        ├── cover_letter.txt
        ├── short_answers.txt
        ├── form_fields.txt
        └── job_info.json
```
