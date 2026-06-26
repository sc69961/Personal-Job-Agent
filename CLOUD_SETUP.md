# Cloud Setup Guide — GitHub Actions + Firebase Hosting

Follow these steps once to get the job agent running in the cloud.

---

## Step 1 — Create a private GitHub repo

1. Go to https://github.com/new
2. Name it `job-agent` (or anything you like)
3. Set it to **Private** (keeps your resume and config out of public view)
4. Do NOT initialize with README (we'll push existing code)
5. Click **Create repository**

Then in Terminal:

```bash
cd ~/Downloads/job-agent-cloud
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/job-agent.git
git push -u origin main
```

---

## Step 2 — Encode your secrets

Run these commands in Terminal — they base64-encode your credential files:

```bash
# Encode Google credentials JSON
base64 -i ~/Downloads/job-agent/config/google_credentials.json | pbcopy
echo "→ google_credentials.json copied to clipboard"

# Encode Google OAuth token
base64 -i ~/Downloads/job-agent/config/google_token.pickle | pbcopy
echo "→ google_token.pickle copied to clipboard"
```

---

## Step 3 — Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these four secrets:

| Secret Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key (from config.py) |
| `GOOGLE_CREDENTIALS_JSON` | Output of the first base64 command above |
| `GOOGLE_TOKEN_PICKLE` | Output of the second base64 command above |
| `FIREBASE_PROJECT_ID` | Your Firebase project ID (step 4) |

---

## Step 4 — Set up Firebase Hosting

### Create a Firebase project
1. Go to https://console.firebase.google.com
2. Click **Add project** → name it `job-agent-dashboard` (or similar)
3. Disable Google Analytics (not needed) → **Create project**
4. Note your **Project ID** (shown in the project settings page, looks like `job-agent-dashboard-abc12`)

### Install Firebase CLI (one-time)
```bash
npm install -g firebase-tools
firebase login
```

### Initialize hosting from the cloud folder
```bash
cd ~/Downloads/job-agent-cloud
firebase use YOUR_FIREBASE_PROJECT_ID
firebase deploy --only hosting
```

This deploys the placeholder page. You'll see a URL like `https://job-agent-dashboard-abc12.web.app`.

### Add Firebase to GitHub
1. Run: `firebase init hosting:github` — follow the prompts, link to your repo
2. This auto-creates a `FIREBASE_SERVICE_ACCOUNT` secret in your GitHub repo

---

## Step 5 — Trigger a test run

Go to your GitHub repo → **Actions** tab → **Job Agent — Daily Run** → **Run workflow** → **Run workflow**

Watch the logs live. After it completes (~10-15 min), visit your Firebase URL to see the dashboard.

---

## What runs automatically after this

- Every morning at 6:30 AM Mountain Time, GitHub runs the agent
- Dashboard at your Firebase URL updates with fresh results
- Email digest arrives at steve.christianmba@gmail.com
- GitHub Actions tab shows logs for every run (kept 14 days)

## Your two setups

| | Laptop version | Cloud version |
|---|---|---|
| **Location** | `~/Downloads/job-agent` | `~/Downloads/job-agent-cloud` |
| **Run command** | `python main.py` | Automatic via GitHub Actions |
| **Dashboard** | Opens in local browser | Live at Firebase URL |
| **Requires Mac on** | Yes | No |
| **Use for** | Testing, tweaking | Daily production runs |
