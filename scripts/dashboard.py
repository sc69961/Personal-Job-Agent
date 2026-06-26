"""
dashboard.py — Generates a two-tab local HTML dashboard:
  Tab 1: Scored job results
  Tab 2: Application CRM (synced from Gmail)
"""

import json
import os
import webbrowser
from datetime import datetime


# ---------------------------------------------------------------------------
# CRM tab HTML builder
# ---------------------------------------------------------------------------

def _build_crm_tab(crm: dict) -> str:
    apps = crm.get("applications", [])
    last_synced = crm.get("last_synced", "")
    if last_synced:
        try:
            last_synced = datetime.fromisoformat(last_synced).strftime("%b %d at %I:%M %p")
        except Exception:
            pass

    total      = len(apps)
    interviews = sum(1 for a in apps if a.get("status") == "interview_requested")
    offers     = sum(1 for a in apps if a.get("status") == "offer")
    rejected   = sum(1 for a in apps if a.get("status") == "rejected")
    active     = total - rejected

    status_styles = {
        "applied":              ("🔵", "#60a5fa", "#1e3a5f", "#1e40af"),
        "response_received":    ("💬", "#a78bfa", "#2e1b5f", "#5b21b6"),
        "interview_requested":  ("📅", "#4ade80", "#0f2e1a", "#166534"),
        "rejected":             ("❌", "#f87171", "#2a0f0f", "#7f1d1d"),
        "offer":                ("🎉", "#fbbf24", "#2a1f00", "#78350f"),
        "withdrawn":            ("↩️",  "#94a3b8", "#1e2235", "#334155"),
    }

    rows = ""
    for app in apps:
        status    = app.get("status", "applied")
        emoji, color, bg, border = status_styles.get(status, ("🔵", "#60a5fa", "#1e3a5f", "#1e40af"))
        label     = app.get("status_label", "Applied")
        company   = app.get("company", "")
        title     = app.get("job_title", "")
        url       = app.get("job_url", "")
        applied   = app.get("applied_date", "—")
        last_act  = app.get("last_activity", "—")
        followup  = app.get("follow_up_date", "—")
        action    = app.get("recommended_action", "")
        notes     = app.get("notes", "")

        link_html = f'<a href="{url}" target="_blank" class="crm-link">View →</a>' if url else "—"

        # Highlight follow-up dates that are today or past
        followup_html = followup
        if followup and followup != "—":
            try:
                fu_date = datetime.strptime(followup, "%Y-%m-%d").date()
                today   = datetime.now().date()
                if fu_date <= today and status not in ("rejected", "offer", "withdrawn"):
                    followup_html = f'<span class="followup-due">{followup} ⚠️</span>'
            except Exception:
                pass

        rows += f"""
        <tr data-status="{status}">
          <td><strong>{company}</strong></td>
          <td>{title}</td>
          <td>{link_html}</td>
          <td>{applied}</td>
          <td>
            <span class="status-pill" style="color:{color};background:{bg};border:1px solid {border};">
              {emoji} {label}
            </span>
          </td>
          <td>{last_act}</td>
          <td>{followup_html}</td>
          <td class="action-cell">{action}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="8" style="text-align:center;color:#475569;padding:40px;">No applications found yet. Run a full sync to pull from Gmail.</td></tr>'

    return f"""
    <div class="crm-stats">
      <div class="stat-card"><span class="stat-num">{total}</span><span class="stat-label">Total Applied</span></div>
      <div class="stat-card"><span class="stat-num" style="color:#4ade80">{active}</span><span class="stat-label">Active</span></div>
      <div class="stat-card"><span class="stat-num" style="color:#60a5fa">{interviews}</span><span class="stat-label">Interviews</span></div>
      <div class="stat-card"><span class="stat-num" style="color:#fbbf24">{offers}</span><span class="stat-label">Offers</span></div>
      <div class="stat-card"><span class="stat-num" style="color:#f87171">{rejected}</span><span class="stat-label">Rejected</span></div>
    </div>

    <div class="crm-filters">
      <label>Filter by status</label>
      <select id="crmStatusFilter" onchange="filterCRM()">
        <option value="">All statuses</option>
        <option value="applied">Applied</option>
        <option value="response_received">Response Received</option>
        <option value="interview_requested">Interview Requested</option>
        <option value="offer">Offer</option>
        <option value="rejected">Rejected</option>
        <option value="withdrawn">Withdrawn</option>
      </select>
      <span class="crm-sync-time">Last Gmail sync: {last_synced or "never"}</span>
    </div>

    <div class="crm-table-wrap">
      <table class="crm-table" id="crmTable">
        <thead>
          <tr>
            <th>Company</th>
            <th>Job Title</th>
            <th>Link</th>
            <th>Applied</th>
            <th>Status</th>
            <th>Last Activity</th>
            <th>Follow Up</th>
            <th>Recommended Action</th>
          </tr>
        </thead>
        <tbody id="crmBody">
          {rows}
        </tbody>
      </table>
    </div>"""


# ---------------------------------------------------------------------------
# Jobs tab HTML builder
# ---------------------------------------------------------------------------

def _build_jobs_tab(jobs: list, run_time: str) -> str:
    total = len(jobs)
    cards_html = ""
    for j in jobs:
        score = j.get("score", 0)
        rec   = j.get("apply_recommendation", "maybe").lower()
        tier  = j.get("company_tier", "other")
        work  = j.get("work_type", "unknown")

        tier_emoji = {"climatetech": "⚡", "fintech_ai": "🤖", "other": "🏢"}.get(tier, "🏢")
        tier_label = {"climatetech": "Climate Tech", "fintech_ai": "Fintech / AI", "other": "Other"}.get(tier, "Other")
        work_emoji = {"remote": "🌐", "hybrid": "🔀", "on-site": "🏢"}.get(work, "❓")
        work_label = {"remote": "Remote", "hybrid": "Hybrid", "on-site": "On-site"}.get(work, "Unknown")
        rec_class  = {"strong yes": "rec-strong-yes", "yes": "rec-yes", "maybe": "rec-maybe", "no": "rec-no"}.get(rec, "rec-maybe")
        rec_label  = rec.upper().replace("STRONG YES", "STRONG YES ★")
        score_class = "score-high" if score >= 80 else ("score-mid" if score >= 65 else "score-low")

        strengths_html = "".join(f'<li>{s}</li>' for s in j.get("top_strengths", []))
        gaps_html      = "".join(f'<li>{g}</li>' for g in j.get("top_gaps", []))
        short_desc     = j.get("short_description", "")
        match_summary  = j.get("match_summary", "")
        salary         = j.get("salary_estimate", "Not available")
        url            = j.get("url", "#")

        cards_html += f"""
        <div class="card" data-score="{score}" data-tier="{tier}" data-work="{work}" data-rec="{rec}">
          <div class="card-header">
            <div class="score-badge {score_class}">{score}</div>
            <div class="card-title-block">
              <div class="job-title">{j.get('title','')}</div>
              <div class="company-name">{tier_emoji} {j.get('company','')}</div>
            </div>
            <span class="rec-badge {rec_class}">{rec_label}</span>
          </div>
          <div class="meta-row">
            <span class="meta-tag">{work_emoji} {work_label}</span>
            <span class="meta-tag">📍 {j.get('location','')}</span>
            <span class="meta-tag">💰 {salary}</span>
            <span class="meta-tag tier-tag">{tier_label}</span>
          </div>
          {f'<p class="short-desc">{short_desc}</p>' if short_desc else ''}
          <p class="match-summary">{match_summary}</p>
          <div class="strengths-gaps">
            {f'<div class="strengths"><strong>✅ Strengths</strong><ul>{strengths_html}</ul></div>' if strengths_html else ''}
            {f'<div class="gaps"><strong>⚠️ Gaps</strong><ul>{gaps_html}</ul></div>' if gaps_html else ''}
          </div>
          <div class="card-footer">
            <a href="{url}" target="_blank" class="apply-btn">Apply →</a>
          </div>
        </div>"""

    return f"""
    <div class="filters" id="jobFilters">
      <div class="filter-group">
        <label>Min score</label>
        <input type="range" id="scoreFilter" min="0" max="100" value="0" step="5"
               oninput="document.getElementById('scoreVal').textContent=this.value; applyFilters()">
        <span class="score-filter-val" id="scoreVal">0</span>
      </div>
      <div class="filter-group">
        <label>Recommendation</label>
        <select id="recFilter" onchange="applyFilters()">
          <option value="">All</option>
          <option value="strong yes">Strong Yes</option>
          <option value="yes">Yes</option>
          <option value="maybe">Maybe</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Work type</label>
        <select id="workFilter" onchange="applyFilters()">
          <option value="">All</option>
          <option value="remote">Remote</option>
          <option value="hybrid">Hybrid</option>
          <option value="on-site">On-site</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Sector</label>
        <select id="tierFilter" onchange="applyFilters()">
          <option value="">All</option>
          <option value="climatetech">Climate Tech</option>
          <option value="fintech_ai">Fintech / AI</option>
          <option value="other">Other</option>
        </select>
      </div>
      <span class="count-badge" id="countBadge">{total} jobs shown</span>
    </div>

    <div class="grid" id="grid">
      {cards_html}
      <div class="empty-state hidden" id="emptyState">No jobs match your filters.</div>
    </div>"""


# ---------------------------------------------------------------------------
# Full HTML page
# ---------------------------------------------------------------------------

def generate_dashboard(
    jobs: list,
    crm=None,
    output_path: str = "./output/dashboard.html",
) -> str:
    run_time  = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    crm       = crm or {}
    crm_count = len(crm.get("applications", []))

    jobs_tab_html = _build_jobs_tab(jobs, run_time)
    crm_tab_html  = _build_crm_tab(crm)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Job Agent</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }}

    /* ── Header ── */
    header {{ background: #1a1d27; border-bottom: 1px solid #2d3148; padding: 16px 32px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }}
    header h1 {{ font-size: 1.1rem; font-weight: 700; color: #fff; }}
    .run-info {{ font-size: 0.78rem; color: #64748b; }}

    /* ── Tabs ── */
    .tabs {{ display: flex; gap: 0; background: #13151f; border-bottom: 1px solid #2d3148; padding: 0 32px; }}
    .tab-btn {{
      padding: 12px 22px; font-size: 0.87rem; font-weight: 600; color: #64748b;
      background: none; border: none; border-bottom: 2px solid transparent;
      cursor: pointer; transition: all 0.2s; white-space: nowrap;
    }}
    .tab-btn:hover {{ color: #94a3b8; }}
    .tab-btn.active {{ color: #818cf8; border-bottom-color: #818cf8; }}
    .tab-content {{ display: none; }}
    .tab-content.active {{ display: block; }}

    /* ── Job filters ── */
    .filters {{ display: flex; gap: 10px; padding: 16px 32px; background: #13151f; border-bottom: 1px solid #1e2235; flex-wrap: wrap; align-items: center; }}
    .filters label {{ font-size: 0.78rem; color: #64748b; margin-right: 4px; }}
    select, input[type=range] {{ background: #1e2235; color: #e2e8f0; border: 1px solid #2d3148; border-radius: 6px; padding: 5px 10px; font-size: 0.82rem; cursor: pointer; }}
    .filter-group {{ display: flex; align-items: center; gap: 6px; }}
    .score-filter-val {{ font-size: 0.82rem; color: #94a3b8; min-width: 28px; }}
    .count-badge {{ margin-left: auto; font-size: 0.82rem; color: #64748b; }}

    /* ── Job cards grid ── */
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 18px; padding: 24px 32px; max-width: 1400px; margin: 0 auto; }}
    .card {{ background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 12px; transition: border-color 0.2s; }}
    .card:hover {{ border-color: #4f6ef7; }}
    .card-header {{ display: flex; align-items: flex-start; gap: 14px; }}
    .score-badge {{ font-size: 1.4rem; font-weight: 800; min-width: 52px; height: 52px; border-radius: 10px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }}
    .score-high {{ background: #0f2e1a; color: #4ade80; border: 1px solid #166534; }}
    .score-mid  {{ background: #1e2a0f; color: #a3e635; border: 1px solid #3f6212; }}
    .score-low  {{ background: #2a1f0f; color: #fb923c; border: 1px solid #7c2d12; }}
    .card-title-block {{ flex: 1; min-width: 0; }}
    .job-title {{ font-size: 0.98rem; font-weight: 700; color: #f1f5f9; line-height: 1.3; }}
    .company-name {{ font-size: 0.83rem; color: #94a3b8; margin-top: 3px; }}
    .rec-badge {{ font-size: 0.68rem; font-weight: 700; padding: 4px 8px; border-radius: 6px; white-space: nowrap; flex-shrink: 0; }}
    .rec-strong-yes {{ background: #0f2e1a; color: #4ade80; border: 1px solid #166534; }}
    .rec-yes        {{ background: #1e2a0f; color: #a3e635; border: 1px solid #3f6212; }}
    .rec-maybe      {{ background: #2a2200; color: #fbbf24; border: 1px solid #78350f; }}
    .rec-no         {{ background: #2a0f0f; color: #f87171; border: 1px solid #7f1d1d; }}
    .meta-row {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .meta-tag {{ font-size: 0.75rem; background: #0f1117; border: 1px solid #2d3148; border-radius: 5px; padding: 3px 8px; color: #94a3b8; }}
    .tier-tag {{ color: #818cf8; border-color: #3730a3; background: #1e1b4b; }}
    .short-desc {{ font-size: 0.83rem; color: #cbd5e1; font-style: italic; }}
    .match-summary {{ font-size: 0.82rem; color: #94a3b8; line-height: 1.55; }}
    .strengths-gaps {{ display: flex; gap: 16px; font-size: 0.78rem; }}
    .strengths, .gaps {{ flex: 1; }}
    .strengths strong {{ color: #4ade80; }}
    .gaps strong {{ color: #fbbf24; }}
    .strengths ul, .gaps ul {{ margin-top: 5px; padding-left: 14px; color: #94a3b8; line-height: 1.6; }}
    .card-footer {{ margin-top: auto; padding-top: 8px; border-top: 1px solid #2d3148; }}
    .apply-btn {{ display: inline-block; background: #4f6ef7; color: #fff; font-size: 0.82rem; font-weight: 600; padding: 8px 18px; border-radius: 7px; text-decoration: none; transition: background 0.2s; }}
    .apply-btn:hover {{ background: #3b55d4; }}
    .hidden {{ display: none !important; }}
    .empty-state {{ grid-column: 1/-1; text-align: center; color: #475569; padding: 60px 0; font-size: 1rem; }}

    /* ── CRM tab ── */
    .crm-stats {{ display: flex; gap: 16px; padding: 24px 32px 0; flex-wrap: wrap; }}
    .stat-card {{ background: #1a1d27; border: 1px solid #2d3148; border-radius: 10px; padding: 16px 24px; text-align: center; min-width: 100px; }}
    .stat-num {{ display: block; font-size: 2rem; font-weight: 800; color: #f1f5f9; }}
    .stat-label {{ display: block; font-size: 0.75rem; color: #64748b; margin-top: 2px; }}

    .crm-filters {{ display: flex; align-items: center; gap: 12px; padding: 16px 32px; background: #13151f; border-bottom: 1px solid #1e2235; margin-top: 20px; }}
    .crm-filters label {{ font-size: 0.78rem; color: #64748b; }}
    .crm-sync-time {{ margin-left: auto; font-size: 0.75rem; color: #475569; }}

    .crm-table-wrap {{ padding: 24px 32px; overflow-x: auto; }}
    .crm-table {{ width: 100%; border-collapse: collapse; font-size: 0.83rem; }}
    .crm-table th {{ text-align: left; padding: 10px 14px; color: #64748b; font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #2d3148; white-space: nowrap; }}
    .crm-table td {{ padding: 12px 14px; border-bottom: 1px solid #1e2235; vertical-align: top; color: #cbd5e1; }}
    .crm-table tr:hover td {{ background: #1a1d27; }}
    .status-pill {{ display: inline-block; font-size: 0.72rem; font-weight: 700; padding: 3px 9px; border-radius: 20px; white-space: nowrap; }}
    .crm-link {{ color: #818cf8; text-decoration: none; font-weight: 600; }}
    .crm-link:hover {{ color: #a5b4fc; }}
    .action-cell {{ max-width: 260px; color: #94a3b8; font-size: 0.8rem; line-height: 1.4; }}
    .followup-due {{ color: #fbbf24; font-weight: 600; }}
  </style>
</head>
<body>

<header>
  <h1>⚡ Job Agent</h1>
  <span class="run-info">Last run: {run_time} &nbsp;·&nbsp; {len(jobs)} jobs scored &nbsp;·&nbsp; {crm_count} applications tracked</span>
</header>

<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('jobs', this)">🔍 Job Results ({len(jobs)})</button>
  <button class="tab-btn" onclick="switchTab('crm', this)">📋 Application CRM ({crm_count})</button>
</div>

<div id="tab-jobs" class="tab-content active">
  {jobs_tab_html}
</div>

<div id="tab-crm" class="tab-content">
  {crm_tab_html}
</div>

<script>
  function switchTab(name, btn) {{
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    btn.classList.add('active');
  }}

  function applyFilters() {{
    const minScore = parseInt(document.getElementById('scoreFilter').value);
    const rec  = document.getElementById('recFilter').value;
    const work = document.getElementById('workFilter').value;
    const tier = document.getElementById('tierFilter').value;
    const cards = document.querySelectorAll('.card');
    let visible = 0;
    cards.forEach(c => {{
      const ok = (
        parseInt(c.dataset.score) >= minScore &&
        (!rec  || c.dataset.rec  === rec)  &&
        (!work || c.dataset.work === work) &&
        (!tier || c.dataset.tier === tier)
      );
      c.classList.toggle('hidden', !ok);
      if (ok) visible++;
    }});
    document.getElementById('countBadge').textContent = visible + ' jobs shown';
    document.getElementById('emptyState').classList.toggle('hidden', visible > 0);
  }}

  function filterCRM() {{
    const status = document.getElementById('crmStatusFilter').value;
    document.querySelectorAll('#crmBody tr').forEach(row => {{
      row.style.display = (!status || row.dataset.status === status) ? '' : 'none';
    }});
  }}
</script>

</body>
</html>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def open_dashboard(jobs: list, crm=None, output_path: str = "./output/dashboard.html"):
    # Auto-load CRM from file if not passed in
    if crm is None:
        crm_path = "./output/crm.json"
        if os.path.exists(crm_path):
            with open(crm_path) as f:
                crm = json.load(f)
        else:
            crm = {}
    path = generate_dashboard(jobs, crm, output_path)
    webbrowser.open(f"file://{os.path.abspath(path)}")
    return path
