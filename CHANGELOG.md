# Changelog

All notable changes to the job agent are documented here.

---

## [Unreleased] — Sprint: CRM Smart Matching & Email Confidence Flagging

### 2026-07-16

#### CRM — Automated Email-to-Application Matching

The most impactful problem with the personal CRM was that recruiter replies
frequently arrive on *new* email threads with no job title in the subject.
This sprint replaces the single-layer company-name lookup with a four-layer
matching stack and adds confidence scoring so low-confidence matches are
flagged for review instead of silently committed.

**`scripts/gmail_crm.py`**

- **Recruiter email domain matching** (`_extract_sender_domains`, `_build_domain_map`,
  `_find_existing_by_domain`) — On each new thread, extract company-owned
  domains from all `From:` headers (filtering out Gmail, Yahoo, and 36 ATS
  platforms including Greenhouse, Lever, Ashby, Workday, and LinkedIn).
  Compare against domains stored on existing CRM entries. A domain hit is
  the most reliable match signal and is tried first.

- **Four-layer matching priority** (most → least reliable):
  1. Recruiter email domain — catches follow-ups with no role in subject.
  2. Claude's `matched_company` / `matched_title` suggestion — Claude is
     now shown Steve's full active-application list and asked to identify
     which role a vague email belongs to.
  3. Exact company + title hash — previous behaviour; unchanged.
  4. Company-name-only fallback — normalized company name match across all
     open entries.

- **Active applications context in Claude prompt** — The prompt now includes
  a formatted list of all non-terminal applications (`company | job_title |
  applied_date | status`) so Claude can identify "Following up on your
  application" emails even when the body never names the role. `max_tokens`
  raised 400 → 600 to accommodate the richer prompt.

- **Confidence scoring** — Claude returns an integer `confidence` (0–100)
  for each classification:
  - 90–100: role and company explicit in subject/body; status unambiguous
  - 70–89: company clear but role inferred; or one ambiguous status signal
  - 50–69: role or company inferred; recruiter reply with no job reference
  - <50: guessing from timing or partial signals
  If Claude omits the field the code defaults to 80. Confidence < 70 or
  an empty `job_title` auto-sets `needs_review = True`.

- **`needs_review` flag** — Stored on CRM entries when confidence is low.
  Cleared automatically if a subsequent high-confidence match updates the
  same entry. Logged as `⚠ Low confidence` at INFO level.

- **`match_reasoning`** — 1-sentence Claude explanation of how it identified
  the application match (or why it's uncertain). Shown in dashboard and
  email tooltips.

- **`sender_domains` persistence** — Domains discovered on each thread are
  stored on the CRM entry and accumulated across runs. Future recruiter
  replies on new threads are found by domain without needing Claude.

**`scripts/dashboard.py`** — CRM tab additions

- Orange **⚠ Review** badge on any CRM row where `needs_review=True`.
  Hovering reveals `match_reasoning` and the confidence percentage.
- Amber **Needs Review** banner at the top of the CRM tab listing all
  flagged entries with company, title, and reasoning.
- **"Need Review (N)"** orange stat card in the CRM header.
- **"⚠ Needs Review (N)"** toggle filter button — click to show only
  flagged entries; click again to clear.
- Extracted `_review_item(a)` helper to avoid Python 3.10 backslash-in-
  f-string limitation.

**`scripts/gmail_sender.py`** — Daily digest additions

- Amber **"N CRM matches need your review"** block in the Pipeline
  Snapshot section of the daily email. Lists up to 5 flagged entries
  with company, title, and Claude's `match_reasoning`. Directs Steve to
  the CRM tab to verify.

#### Testing — 34 new tests (all passing, 79 total in test_crm.py)

- **`TestExtractSenderDomains`** (12 tests) — angle-bracket format,
  bare email, gmail excluded, greenhouse/lever/ashby excluded, empty
  messages, multiple domains, deduplication, malformed header, generic
  domain set membership.
- **`TestBuildDomainMap`** (5 tests) — no sender_domains, single domain,
  multiple domains from one app, multiple apps, empty dict.
- **`TestFindExistingByDomain`** (6 tests) — empty sender set, empty
  domain map, no intersection, match found, highest-priority-status
  preference, partial domain overlap.
- **`TestAnalyzeThreadConfidence`** (11 tests) — high confidence
  passthrough, low confidence forces needs_review, empty title forces
  needs_review, null response, null with whitespace, markdown fence
  stripping, matched_company/title fields, API exception returns None,
  active_applications in prompt, no context when None, boundary at
  exactly 70 (no review), 69 triggers review.

---

## [2026-07-15] — Sprint: Git Reliability, Persistence, Scoring, & Test Coverage

### 2026-07-15

#### Git Reliability
- **`scripts/git_safe_push.sh`** — New reusable helper used by both workflow files for all git commit/push operations. Implements three layers of protection:
  1. *Stale lock detection:* Before any git operation, inspects `.git/index.lock`, `.git/HEAD.lock`, and `.git/objects/maintenance.lock`. Reads the PID embedded in each lock file; if the process is still alive, waits up to 60 seconds. If the PID is gone or the lock is older than 2 minutes, removes it as an orphan.
  2. *Live process guard:* If a real process holds the lock and doesn't release within `MAX_WAIT` seconds, exits with an error rather than risk corrupting the repo.
  3. *Push retry with backoff:* Retries the push up to 3 times with 10s/20s/30s delays, re-pulling before each retry to absorb any concurrent `[skip ci]` commits that landed in between.
- **`concurrency` groups in both workflows** — `job-agent.yml` uses group `job-agent-main`; `sync-crm.yml` uses group `sync-crm-main`. A manual trigger queued while an automatic run is in progress will wait rather than race. `cancel-in-progress: false` ensures no run is dropped — every run persists its data.
- Both workflow "Persist data files to repo" steps now delegate to `git_safe_push.sh` instead of inline shell commands.

#### Features
- **Force email override** — Added `force_email` boolean input to the `workflow_dispatch` trigger in `job-agent.yml`. When checked on a manual GitHub Actions run, it bypasses the daily email deduplication flag so you always get a digest. Previously, running the workflow manually after the 6:30 AM automatic run silently skipped the email.
- **Maybe section on dashboard** — Jobs scoring 40–54 now appear in a collapsible "Maybe" section below the main action queue instead of being dropped entirely. The display threshold for the action queue remains 55+. `MIN_SCORE_TO_INCLUDE` lowered to 40.
- **ESG / sustainability software signal** — Added +8 pts positive signal for carbon accounting, ESG data platforms, climate reporting, net-zero management, and supply chain sustainability companies.
- **IoT / smart building signal** — Added +3 pts for IoT and smart building software roles with genuine PM ownership scope.
- **Adjacent domain clarification** — Enterprise SaaS, data platforms, IoT/smart building, logistics, and construction tech now explicitly get 0 pts domain penalty. Steve's platform and API skills transfer well to these industries.
- **Expanded target title list** — Added Chief Product Officer (CPO), Head of Digital Products, and Director of Innovation to the title match list (+8 pts).
- **Removed large PM org penalty** — The -5 pts penalty for highly matrixed 50+ PM organizations was removed. These roles still get scored; the penalty was filtering out otherwise strong matches.
- **Expanded company list** — Added ~25 new companies across three categories:
  - *ESG / Sustainability Software:* Watershed, Persefoni, Measurabl, Sweep, Greenly, Terrascope, Sphera, Sustain.Life, EcoVadis, Workiva, Diligent, Intelex
  - *Data Platform & Analytics:* dbt Labs, Amplitude, Monte Carlo, Fivetran, Retool, Rippling, Figma
  - *IoT / Smart Building:* Honeywell Forge, Johnson Controls OpenBlue, Turntide Technologies, Willow, Gridium

#### Persistence & Reliability
- **`first_seen_registry.json`** — New file (`output/first_seen_registry.json`) maps job_id → ISO timestamp independently of `scored_jobs.json`. Job "first seen" dates now survive cache wipes. Three-layer persistence: Actions cache (fast, 7-day) → git repo (permanent for 3 files) → S3 (permanent for all 4).
- **Git-commit persistence** — Both `job-agent.yml` and `sync-crm.yml` commit `first_seen_registry.json`, `rejected_jobs.json`, and `market_stats.json` back to the repo after each run using `[skip ci]` commits. Survives GitHub Actions cache expiry.
- **Amazon S3 storage** — `scripts/s3_storage.py` added. Bucket `stevechristian-job-agent` (us-east-2). `restore()` downloads missing files at run start; `backup()` uploads all four data files at run end. IAM user `job-agent-s3` with minimal policy.
- **`.gitignore` exceptions** — Added `!output/first_seen_registry.json`, `!output/rejected_jobs.json`, `!output/market_stats.json` so the git persistence step can commit these files even though `output/` is otherwise gitignored.

#### Bug Fixes
- **S3 `restore()` exception handling** — Fixed invalid `except expr if ... else Exception` ternary syntax that raised `TypeError` when the S3 client was a mock. Replaced with standard `except Exception` + string check for `NoSuchKey`/`404`.
- **S3 `restore()` directory creation** — `os.makedirs` now runs per-file using the actual file path, not a hardcoded `"output/"`. Fixes directory creation when tests pass `tmp_path`-based paths.
- **FORCE_EMAIL env var** — `main.py` now reads `FORCE_EMAIL` from the environment (set by the workflow's `force_email` input) alongside the existing `--email-only` CLI flag.

#### Testing — 69 new tests (all passing)
- **`test_s3_storage.py`** (20 tests) — `_is_configured`, `restore` (skip existing, download missing, handle NoSuchKey, handle bad client, create dirs), `backup` (skip unconfigured, upload files, skip missing, handle failures, all 4 files)
- **`test_scorer.py::TestScoringPromptNewSignals`** (9 tests) — Locks in: ESG +8 signal present, carbon accounting named, no large PM org penalty, adjacent domain = 0 pts, CPO/Head of Digital/Director of Innovation in title list, domain mismatch still penalizes healthcare/pharma, IoT + smart building present
- **`test_first_seen_registry.py`** (9 tests) — `_load_first_seen_registry`, `_save_first_seen_registry`, `score_all_jobs` registry integration (cache wipe survival, cache hit populates registry, new job registered, registry wins over re-scored date)
- **`test_rejection_tracking.py`** (9 tests) — Pre-filter rejections written, no score for pre-filter, `first_analyzed` timestamp, international rejection, low-score rejection, reason mentions threshold, qualifying job not in rejected, `first_analyzed` preserved across runs, multiple rejection types in same run
- **`test_dashboard.py`** (22 tests) — Action queue / Maybe / Archive splitting, display threshold = 55, stale routing, applied job routing, empty states, action count badge, performance tab stats/badges/table/filter buttons

---

## [2026-07-01] — Sprint: CRM, Email & Cloud Stability

- Switched email to SMTP App Password (no OAuth required for sending)
- Self-refreshing Google OAuth token cached in GitHub Actions (no manual Secret updates)
- CRM sync standalone workflow (`sync-crm.yml`) — refreshes CRM without scraping/scoring
- Collapsible job cards on dashboard (click to expand details)
- Action queue / archive split with NEW-first sort
- `--crm-only` flag for CRM-only runs

---

## [2026-06-15] — Sprint: Dashboard & Intelligence

- Market Intelligence tab with PM role trends, salary benchmarks, and company activity
- "New This Week" and "Heating Up" sections in Market Intel
- NEW and APPLIED badges on job cards
- `company_context.json` with profiles for all target companies
- `first_seen` date stamped on each scored job

---

## [2026-06-01] — Sprint: Core Agent

- Job scraper across 70+ company career sites (Greenhouse, Lever, Ashby, Workday, custom)
- Claude-powered scoring with resume fit, company tier, title, location, salary signals
- Gmail CRM: auto-classifies applications, responses, rejections, offers from inbox
- Firebase Hosting deployment via GitHub Actions (daily 6:30 AM MT cron)
- Local dashboard with Job Results, Application CRM, and Market Intel tabs
- Rejection tracking: pre-filter and low-score rejections logged to `rejected_jobs.json`
- Performance tab showing full pipeline funnel
