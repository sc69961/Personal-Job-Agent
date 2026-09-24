# Personal Job Agent

An autonomous job-search system that scrapes 70+ job boards daily, scores every opportunity against my resume and preferences using Claude AI, maintains a live Gmail-synced CRM, and delivers a curated email digest — all running on a zero-cost serverless stack.

**Live dashboard →** [stevechristianmba-jobs.web.app](https://stevechristianmba-jobs.web.app)

---

## What It Does

Every weekday at 5 AM MT, a GitHub Actions workflow:

1. **Scrapes** 70+ sources — company career pages (Lever, Greenhouse, Workday, iCIMS, Ashby, BambooHR), job boards (LinkedIn, Indeed, Climatebase, Lynceus), and a custom list of 100+ target companies in climate tech, energy, and AI
2. **Scores** each new role with Claude (Haiku) against my resume, career goals, location preferences, and salary targets — producing a 0–100 score, strengths/gaps summary, and apply recommendation
3. **Emails** a curated digest of new (last 7 days), unapplied, 40+ scored roles — sorted by score, with inline apply and cover-letter-draft buttons
4. **Syncs the CRM** by scanning my Gmail for application confirmations, recruiter replies, and interview requests — classifying them with Claude and updating application status automatically
5. **Deploys** the live dashboard to Firebase Hosting with the latest scored jobs and CRM pipeline

A separate CRM-only workflow runs at 9 AM and 2 PM MT to catch same-day email responses.

---

## Architecture

```
GitHub Actions (cron: 5 AM MT weekdays)
│
├── scraper.py          → fetches job listings from 70+ sources
│     ├── Lever / Greenhouse / Ashby / iCIMS / Workday JSON APIs
│     ├── BambooHR / Phenom People HTML scrapers
│     ├── Climatebase API
│     └── Company career pages (HTML fallback)
│
├── scorer.py           → Claude Haiku scores each new job 0–100
│     ├── Pre-filter: drops international / non-remote non-Denver roles (no tokens)
│     ├── Prompt caching: system prompt cached across batch
│     └── Outputs: score, recommendation, strengths, gaps, match summary
│
├── gmail_crm.py        → Gmail OAuth → thread classification → CRM updates
│     ├── Classifies: applied / response_received / interview_requested / offer / rejected
│     ├── ATS domain blacklist: prevents cross-company misattribution on shared domains
│     └── Confidence scoring: flags low-confidence matches for manual review
│
├── gmail_sender.py     → SMTP digest email (App Password, no OAuth)
│     └── Filters: new (7-day) + unapplied + score ≥ 40
│
└── dashboard.py        → generates public/index.html → Firebase Hosting
      ├── Job Results tab: scored cards with apply/archive/cover-letter actions
      ├── Application CRM tab: pipeline snapshot with status tracking
      ├── Market Intel tab: role trend analysis and market stats
      └── Performance tab: scoring accuracy and pipeline metrics
```

**Persistence:** Amazon S3 (primary state store) + git-committed JSON files (cache-expiry fallback)

---

## Tech Stack

| Layer | Technology |
|---|---|
| AI scoring & CRM classification | Anthropic Claude (Haiku 4.5) |
| Orchestration | GitHub Actions (3 workflows) |
| Scraping | Python `requests` + `BeautifulSoup`, ATS JSON APIs |
| State storage | Amazon S3 |
| Email | Gmail OAuth (CRM) + SMTP App Password (digest) |
| Dashboard hosting | Firebase Hosting |
| Language | Python 3.11 |

---

## Key Engineering Decisions

**ATS domain blacklisting** — Shared ATS platforms (Lever, Greenhouse, Workday, etc.) send email from a single domain on behalf of hundreds of companies. Naive sender-domain matching causes cross-company misattribution. A domain blacklist + subdomain-aware check prevents this.

**Prompt caching** — The scorer system prompt (resume, preferences, scoring rubric) is cached across all jobs in a batch via Anthropic's prompt caching API, cutting token costs by ~80% on large runs.

**S3 as authoritative state** — GitHub Actions cache expires after 7 days. S3 is the permanent source of truth for scored jobs, the first-seen registry, CRM state, and the OAuth token. `crm.json` is force-restored from S3 on every run to prevent stale repo checkouts from overwriting live data.

**Deduplication layers** — Jobs are deduplicated by ID at scrape time, by company+title hash before scoring, and by a 30-day seen-ID registry to avoid re-scoring previously processed roles.

**Skip-if-ran-today** — The scheduled workflow checks whether `first_seen_registry.json` was committed today before proceeding. If a manual run already happened, the scheduled run exits cleanly — no wasted API calls or double emails.

---

## Security

- All secrets (API keys, OAuth tokens, App Passwords) are stored in GitHub Secrets — never committed
- `config/google_credentials.json` and `config/google_token.pickle` are gitignored and S3-backed
- Firebase deploys use a service account key (via `GOOGLE_APPLICATION_CREDENTIALS`) — not the deprecated `--token` flag
- Workflow `permissions` default to `{}` (read-nothing); `contents: write` is granted only to jobs that push data back to the repo
- Dependabot monitors both GitHub Actions versions and Python package dependencies weekly

---

## Project Status

Active daily use. Tracks 70+ applications across climate tech, energy, and AI companies. The CRM has processed 200+ email threads with ~95% classification accuracy.

---

*This is a personal tool built for my own job search. It is not designed for general use — credentials, target companies, resume content, and scoring rubrics are all specific to my situation.*
