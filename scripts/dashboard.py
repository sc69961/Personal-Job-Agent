"""
dashboard.py — Generates a two-tab local HTML dashboard:
  Tab 1: Scored job results
  Tab 2: Application CRM (synced from Gmail)
"""

import json
import os
import re
import webbrowser
from datetime import datetime, timedelta, timezone


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

def _normalize(name: str) -> str:
    """Normalize company name for CRM cross-reference."""
    import re
    name = re.sub(r'\b(inc\.?|llc\.?|corp\.?|co\.?|ltd\.?|incorporated|limited|company)\b[\s,]*', '', name, flags=re.I)
    name = re.sub(r'[^\w\s]', ' ', name)
    return ' '.join(name.lower().split())


def _normalize_title(title: str) -> str:
    """Normalize job title for loose matching: lowercase, collapse punctuation/spaces."""
    return re.sub(r'[\s\-–—,/|]+', ' ', title.lower()).strip()


_STATUS_RANK = ["applied", "ghosted", "withdrawn", "response_received",
                "rejected", "interview_requested", "offer"]

def _status_rank(status: str) -> int:
    try:
        return _STATUS_RANK.index(status)
    except ValueError:
        return -1

def _build_jobs_tab(jobs: list, run_time: str, crm: dict = None) -> str:
    now = datetime.now()

    # Build CRM lookup: (normalized_company, normalized_title) → (status, status_label)
    crm_by_title = {}
    for app in (crm or {}).get("applications", []):
        co_key    = _normalize(app.get("company", ""))
        title_key = _normalize_title(app.get("job_title", ""))
        if co_key and title_key:
            pair = (co_key, title_key)
            existing = crm_by_title.get(pair)
            if not existing or _status_rank(app.get("status")) > _status_rank(existing[0]):
                crm_by_title[pair] = (app.get("status", "applied"), app.get("status_label", "Applied"))

    crm_status_styles = {
        "offer":              ("🏆 Offer",        "#fbbf24", "#2a1f00", "#78350f"),
        "interview_requested":("🎯 Interviewing",  "#4ade80", "#0f2e1a", "#166534"),
        "response_received":  ("💬 Responded",     "#67e8f9", "#0c2233", "#0e4f66"),
        "applied":            ("✉️ Applied",       "#94a3b8", "#1a1d27", "#2d3148"),
        "ghosted":            ("👻 Ghosted",       "#475569", "#1a1d27", "#2d3148"),
        "rejected":           ("✗ Rejected",      "#f87171", "#2a0f0f", "#7f1d1d"),
        "withdrawn":          ("↩ Withdrawn",     "#64748b", "#1a1d27", "#2d3148"),
    }

    # ── Helpers ──

    def _is_new(j) -> bool:
        fs = j.get("first_seen", "")
        if not fs:
            return False
        try:
            return (now - datetime.fromisoformat(fs)) < timedelta(hours=24)
        except ValueError:
            return fs == now.strftime("%Y-%m-%d")

    def _age_label(j) -> str:
        fs = j.get("first_seen", "")
        if not fs:
            return ""
        try:
            delta = now - datetime.fromisoformat(fs)
            if delta.total_seconds() < 3600:
                return f"{int(delta.total_seconds() / 60)}m ago"
            if delta.total_seconds() < 86400:
                return f"{int(delta.total_seconds() / 3600)}h ago"
            return f"{delta.days}d ago"
        except Exception:
            return ""

    def _is_stale(j) -> bool:
        """True if first_seen is older than 7 days."""
        fs = j.get("first_seen", "")
        if not fs:
            return False
        try:
            return (now - datetime.fromisoformat(fs)) > timedelta(days=7)
        except ValueError:
            try:
                return (now - datetime.strptime(fs, "%Y-%m-%d")).days > 7
            except Exception:
                return False

    # ── Sort: NEW first (within 24h), then by score descending ──
    sorted_jobs = sorted(jobs, key=lambda j: (0 if _is_new(j) else 1, -j.get("score", 0)))

    # ── Split into action queue vs. archive ──
    # Archive = has CRM match (already applied) OR older than 7 days
    action_pairs = []   # (job, crm_match)
    archive_pairs = []  # (job, crm_match)

    for j in sorted_jobs:
        co_key    = _normalize(j.get("company", ""))
        title_key = _normalize_title(j.get("title", ""))
        crm_match = crm_by_title.get((co_key, title_key))
        if crm_match or _is_stale(j):
            archive_pairs.append((j, crm_match))
        else:
            action_pairs.append((j, crm_match))

    # ── Card builder ──
    def _card(j, crm_match, idx: int, archived: bool = False) -> str:
        score = j.get("score", 0)
        rec   = j.get("apply_recommendation", "maybe").lower()
        tier  = j.get("company_tier", "other")
        work  = j.get("work_type", "unknown")

        tier_emoji  = {"climatetech": "⚡", "fintech_ai": "🤖", "other": "🏢"}.get(tier, "🏢")
        tier_label  = {"climatetech": "Climate Tech", "fintech_ai": "Fintech / AI", "other": "Other"}.get(tier, "Other")
        work_emoji  = {"remote": "🌐", "hybrid": "🔀", "on-site": "🏢"}.get(work, "❓")
        work_label  = {"remote": "Remote", "hybrid": "Hybrid", "on-site": "On-site"}.get(work, "Unknown")
        rec_class   = {"strong yes": "rec-strong-yes", "yes": "rec-yes", "maybe": "rec-maybe", "no": "rec-no"}.get(rec, "rec-maybe")
        rec_label   = rec.upper().replace("STRONG YES", "STRONG YES ★")
        score_class = "score-high" if score >= 80 else ("score-mid" if score >= 65 else "score-low")

        confidence = j.get("confidence", 50)
        conf_color = "#4ade80" if confidence >= 80 else ("#fbbf24" if confidence >= 55 else "#f87171")
        conf_label = "High" if confidence >= 80 else ("Medium" if confidence >= 55 else "Low — review")
        salary     = j.get("salary_estimate", "Not available")
        url        = j.get("url", "#")
        age        = _age_label(j)
        is_new     = _is_new(j)

        new_badge = (
            '<span style="display:inline-block;font-size:0.68rem;font-weight:800;padding:3px 8px;'
            'border-radius:5px;background:#1e2a0f;color:#a3e635;border:1px solid #3f6212;'
            'margin-left:8px;letter-spacing:0.05em;">NEW</span>'
        ) if is_new else ""

        crm_badge      = ""
        left_border    = ""
        is_applied_str = "false"
        if crm_match:
            status, _ = crm_match
            style_label, text_c, bg_c, border_c = crm_status_styles.get(
                status, ("Applied", "#94a3b8", "#1a1d27", "#2d3148"))
            crm_badge = (
                f'<span style="display:inline-block;font-size:0.68rem;font-weight:700;padding:3px 8px;'
                f'border-radius:5px;background:{bg_c};color:{text_c};border:1px solid {border_c};'
                f'margin-left:6px;">{style_label}</span>'
            )
            left_border    = f"border-left: 4px solid {border_c};"
            is_applied_str = "true"

        new_border = "border-color:#166534;" if (is_new and not archived) else ""
        dim_style  = "opacity:0.65;" if archived else ""

        btn = (
            f'<a href="{url}" target="_blank" class="apply-btn apply-btn-dim">View →</a>'
            if archived else
            f'<a href="{url}" target="_blank" class="apply-btn">Apply →</a>'
        )

        # Collapsible body — hidden by default, revealed on card click
        body_html = ""
        if not archived:
            short_desc     = j.get("short_description", "")
            match_summary  = j.get("match_summary", "")
            reasons_html   = "".join(f'<li>{r}</li>' for r in j.get("top_reasons", []))
            strengths_html = "".join(f'<li>{s}</li>' for s in j.get("top_strengths", []))
            gaps_html      = "".join(f'<li>{g}</li>' for g in j.get("top_gaps", []))
            strengths_div = f'<div class="strengths"><strong>✅ Strengths</strong><ul>{strengths_html}</ul></div>' if strengths_html else ''
            gaps_div      = f'<div class="gaps"><strong>⚠️ Gaps</strong><ul>{gaps_html}</ul></div>' if gaps_html else ''
            sg_div        = f'<div class="strengths-gaps">{strengths_div}{gaps_div}</div>' if (strengths_html or gaps_html) else ''
            reasons_div   = f'<div class="reasons"><strong>📋 Why this score</strong><ul>{reasons_html}</ul></div>' if reasons_html else ''
            inner = (
                (f'<p class="short-desc">{short_desc}</p>' if short_desc else '') +
                (f'<p class="match-summary">{match_summary}</p>' if match_summary else '') +
                reasons_div + sg_div
            )
            if inner.strip():
                body_html = f'<div class="card-body">{inner}</div>'

        return f"""
        <div class="card" data-score="{score}" data-tier="{tier}" data-work="{work}"
             data-rec="{rec}" data-applied="{is_applied_str}" data-index="{idx}"
             onclick="toggleCard(event, this)"
             style="cursor:pointer;{left_border}{new_border}{dim_style}">
          <div class="card-header">
            <div class="score-badge {score_class}">{score}</div>
            <div class="card-title-block">
              <div class="job-title">{j.get('title', '')}{new_badge}{crm_badge}</div>
              <div class="company-name">{tier_emoji} {j.get('company', '')}</div>
            </div>
            <span class="rec-badge {rec_class}">{rec_label}</span>
          </div>
          <div class="meta-row">
            <span class="meta-tag">{work_emoji} {work_label}</span>
            <span class="meta-tag">📍 {j.get('location', '')}</span>
            <span class="meta-tag">💰 {salary}</span>
            <span class="meta-tag tier-tag">{tier_label}</span>
            <span class="meta-tag" style="color:{conf_color};border-color:{conf_color};"
                  title="Confidence in this score">🎯 {confidence}% — {conf_label}</span>
          </div>
          {body_html}
          <div class="card-footer">
            {btn}
            {f'<span style="font-size:0.72rem;color:#475569;">Seen {age}</span>' if age else ''}
          </div>
        </div>"""

    action_html  = "".join(_card(j, cm, i)              for i, (j, cm) in enumerate(action_pairs))
    archive_html = "".join(_card(j, cm, i, archived=True) for i, (j, cm) in enumerate(archive_pairs))

    action_count  = len(action_pairs)
    archive_count = len(archive_pairs)

    archive_section = ""
    if archive_pairs:
        archive_section = f"""
    <div class="archive-header" id="archiveToggleBtn" onclick="toggleArchive()">
      <span>📦 Archive — applied &amp; jobs older than 7 days
        <strong style="color:#94a3b8;">({archive_count})</strong></span>
      <span id="archiveArrow" style="font-size:0.75rem;">▼ Show</span>
    </div>
    <div id="archiveGrid" class="grid hidden" style="opacity:0.75;">
      {archive_html}
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
      <div class="filter-group">
        <label>Sort</label>
        <select id="sortOrder" onchange="applySort()">
          <option value="newest">Newest first</option>
          <option value="score">Best match</option>
        </select>
      </div>
      <button id="notAppliedBtn" class="not-applied-btn" onclick="toggleNotApplied()">
        ✉️ Not applied only
      </button>
      <span class="count-badge" id="countBadge">{action_count} jobs in queue</span>
    </div>

    <div class="section-label">
      ⚡ Action queue
      <span class="section-count" id="actionCountBadge">{action_count}</span>
      <span style="font-size:0.75rem;color:#475569;margin-left:6px;">· Unapplied · Seen within 7 days · Newest first</span>
    </div>

    <div class="grid" id="grid">
      {action_html or '<div class="empty-state">No new unapplied jobs right now — check back after the next run.</div>'}
      <div class="empty-state hidden" id="emptyState">No jobs match your filters.</div>
    </div>

    {archive_section}"""


# ---------------------------------------------------------------------------
# Market Intelligence tab
# ---------------------------------------------------------------------------

def _build_market_tab(
    stats_path: str = "./output/market_stats.json",
    context_path: str = "./config/company_context.json",
) -> str:
    from datetime import timedelta

    history = []
    if os.path.exists(stats_path):
        try:
            with open(stats_path) as f:
                history = json.load(f)
        except Exception:
            pass

    if not history:
        return '<div style="padding:60px 32px;text-align:center;color:#475569;">No market data yet — run the agent at least once to populate stats.</div>'

    # Load company context profiles
    ctx_profiles = {}
    if os.path.exists(context_path):
        try:
            with open(context_path) as f:
                ctx_profiles = json.load(f)
        except Exception:
            pass

    latest = history[-1]
    companies = latest.get("companies", [])
    pm_companies = [c for c in companies if c.get("pm_roles", 0) > 0]

    # ── Build per-company history dict: name → {date: pm_count} ──
    co_history: dict = {}
    for snap in history:
        for c in snap.get("companies", []):
            name = c["company"]
            co_history.setdefault(name, {})[snap["date"]] = c.get("pm_roles", 0)

    latest_date = latest["date"]

    # ── New This Week: companies with PM roles now that had 0 (or were absent) last snapshot ──
    prev_pm_cos: set = set()
    if len(history) >= 2:
        prev = history[-2]
        prev_pm_cos = {c["company"] for c in prev.get("companies", []) if c.get("pm_roles", 0) > 0}
    new_this_week = [c for c in pm_companies if c["company"] not in prev_pm_cos]

    # ── Heating Up: companies whose PM count increased over last ~4 weeks ──
    # Look at earliest snapshot >= 21 days ago vs latest; require increase ≥ 1
    cutoff_date = (datetime.strptime(latest_date, "%Y-%m-%d") - timedelta(days=21)).strftime("%Y-%m-%d")
    heating_up = []
    seen_names = set()
    for c in pm_companies:
        name = c["company"]
        if name in seen_names:
            continue
        seen_names.add(name)
        h = co_history.get(name, {})
        old_dates = [d for d in sorted(h.keys()) if d <= cutoff_date]
        if not old_dates:
            continue  # not enough history yet
        old_count = h[old_dates[0]]
        now_count = c.get("pm_roles", 0)
        if now_count > old_count:
            heating_up.append({
                "company": name,
                "tier": c.get("tier", "other"),
                "titles": c.get("titles", []),
                "old_count": old_count,
                "now_count": now_count,
                "from_date": old_dates[0],
            })
    heating_up.sort(key=lambda x: x["now_count"] - x["old_count"], reverse=True)

    # ── Trend chart data ──
    dates_js   = json.dumps([s["date"] for s in history])
    total_js   = json.dumps([s.get("total_pm_roles", 0) for s in history])
    scraped_js = json.dumps([s.get("total_jobs_scraped", 0) for s in history])

    # ── Seniority breakdown ──
    seniority = latest.get("seniority_breakdown", {})
    seniority_order = ["VP", "Director/Head", "Principal/Staff", "Senior", "Lead", "Mid-level"]
    seniority_rows = ""
    total_pm = latest.get("total_pm_roles", 1) or 1
    for level in seniority_order:
        count = seniority.get(level, 0)
        if count == 0:
            continue
        pct = round(count / total_pm * 100)
        seniority_rows += f"""
        <div style="margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;font-size:0.82rem;margin-bottom:3px;">
            <span style="color:#cbd5e1;">{level}</span>
            <span style="color:#64748b;">{count} ({pct}%)</span>
          </div>
          <div style="background:#1e2235;border-radius:4px;height:8px;">
            <div style="background:#818cf8;height:8px;border-radius:4px;width:{pct}%;"></div>
          </div>
        </div>"""

    # ── Work type breakdown ──
    work_type = latest.get("work_type_breakdown", {})
    wt_colors = {"remote": "#4ade80", "hybrid": "#fbbf24", "on-site": "#f87171", "unknown": "#475569"}
    wt_rows = ""
    for wt, color in wt_colors.items():
        count = work_type.get(wt, 0)
        if count == 0:
            continue
        pct = round(count / total_pm * 100)
        wt_rows += f"""
        <div style="margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;font-size:0.82rem;margin-bottom:3px;">
            <span style="color:#cbd5e1;">{wt.title()}</span>
            <span style="color:#64748b;">{count} ({pct}%)</span>
          </div>
          <div style="background:#1e2235;border-radius:4px;height:8px;">
            <div style="background:{color};height:8px;border-radius:4px;width:{pct}%;"></div>
          </div>
        </div>"""

    # ── New This Week cards ──
    def _company_signal_card(c: dict, badge_html: str) -> str:
        name = c["company"]
        profile = ctx_profiles.get(name, {})
        tier = c.get("tier", "other")
        tier_emoji = {"climatetech": "⚡", "fintech_ai": "🤖", "other": "🏢"}.get(tier, "🏢")
        titles = c.get("titles", [])
        titles_html = " · ".join(f'<span style="color:#94a3b8;">{t}</span>' for t in titles[:3])
        stage    = profile.get("stage", "")
        funding  = profile.get("funding", "")
        headcount = profile.get("headcount", "")
        what     = profile.get("what_they_do", "")
        why      = profile.get("why_relevant", "")
        meta_bits = " &nbsp;·&nbsp; ".join(x for x in [stage, funding, headcount] if x)
        return f"""
        <div style="background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:16px;margin-bottom:12px;">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:6px;">
            <div>
              <span style="font-weight:700;color:#f1f5f9;font-size:0.95rem;">{tier_emoji} {name}</span>
              {badge_html}
            </div>
            <span style="font-size:0.75rem;color:#818cf8;white-space:nowrap;">{c.get('pm_roles',0)} PM role{'s' if c.get('pm_roles',1)!=1 else ''}</span>
          </div>
          {f'<div style="font-size:0.75rem;color:#64748b;margin-bottom:6px;">{meta_bits}</div>' if meta_bits else ''}
          {f'<div style="font-size:0.8rem;color:#cbd5e1;margin-bottom:4px;">{what}</div>' if what else ''}
          {f'<div style="font-size:0.75rem;color:#4ade80;">→ {why}</div>' if why else ''}
          {f'<div style="font-size:0.75rem;color:#475569;margin-top:6px;">{titles_html}</div>' if titles_html else ''}
        </div>"""

    def _heating_card(h: dict) -> str:
        name = h["company"]
        profile = ctx_profiles.get(name, {})
        tier = h.get("tier", "other")
        tier_emoji = {"climatetech": "⚡", "fintech_ai": "🤖", "other": "🏢"}.get(tier, "🏢")
        delta = h["now_count"] - h["old_count"]
        delta_html = f'<span style="color:#fbbf24;font-weight:700;">+{delta} PM role{"s" if delta!=1 else ""}</span> since {h["from_date"]}'
        stage    = profile.get("stage", "")
        funding  = profile.get("funding", "")
        headcount = profile.get("headcount", "")
        what     = profile.get("what_they_do", "")
        why      = profile.get("why_relevant", "")
        meta_bits = " &nbsp;·&nbsp; ".join(x for x in [stage, funding, headcount] if x)
        titles_html = " · ".join(f'<span style="color:#94a3b8;">{t}</span>' for t in h.get("titles", [])[:3])
        return f"""
        <div style="background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:16px;margin-bottom:12px;">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:6px;">
            <span style="font-weight:700;color:#f1f5f9;font-size:0.95rem;">{tier_emoji} {name}</span>
            <span style="font-size:0.75rem;">{delta_html}</span>
          </div>
          {f'<div style="font-size:0.75rem;color:#64748b;margin-bottom:6px;">{meta_bits}</div>' if meta_bits else ''}
          {f'<div style="font-size:0.8rem;color:#cbd5e1;margin-bottom:4px;">{what}</div>' if what else ''}
          {f'<div style="font-size:0.75rem;color:#4ade80;">→ {why}</div>' if why else ''}
          {f'<div style="font-size:0.75rem;color:#475569;margin-top:6px;">{titles_html}</div>' if titles_html else ''}
        </div>"""

    new_cards_html = "".join(
        _company_signal_card(c, '<span style="display:inline-block;font-size:0.68rem;font-weight:800;padding:2px 7px;border-radius:4px;background:#1e2a0f;color:#a3e635;border:1px solid #3f6212;margin-left:8px;">NEW</span>')
        for c in new_this_week
    ) or '<div style="color:#475569;font-size:0.82rem;padding:12px 0;">No new companies since last run.</div>'

    heating_cards_html = "".join(
        _heating_card(h) for h in heating_up
    ) or '<div style="color:#475569;font-size:0.82rem;padding:12px 0;">Not enough history yet — check back after a few weeks of daily runs.</div>'

    # ── Full company table with context ──
    company_rows = ""
    for c in pm_companies:
        name = c["company"]
        profile = ctx_profiles.get(name, {})
        titles_html = "<br>".join(f"<span style='font-size:0.75rem;color:#94a3b8;'>· {t}</span>" for t in c.get("titles", []))
        tier = c.get("tier", "other")
        tier_badge = {"climatetech": "⚡", "fintech_ai": "🤖", "other": "🏢"}.get(tier, "")
        stage   = profile.get("stage", "—")
        funding = profile.get("funding", "—")
        what    = profile.get("what_they_do", "")
        company_rows += f"""
        <tr>
          <td>
            <span style="font-weight:600;color:#f1f5f9;">{tier_badge} {name}</span>
            {f'<div style="font-size:0.72rem;color:#475569;margin-top:2px;">{what[:80]}{"…" if len(what)>80 else ""}</div>' if what else ''}
          </td>
          <td style="text-align:center;color:#818cf8;font-weight:700;">{c['pm_roles']}</td>
          <td style="text-align:center;color:#64748b;">{c['total_roles']}</td>
          <td>{titles_html}</td>
          <td style="color:#64748b;font-size:0.75rem;white-space:nowrap;">{stage}</td>
          <td style="color:#64748b;font-size:0.75rem;">{funding}</td>
        </tr>"""

    # ── Source breakdown ──
    source = latest.get("source_breakdown", {})
    source_rows = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #1e2235;font-size:0.82rem;">'
        f'<span style="color:#cbd5e1;">{src}</span><span style="color:#818cf8;font-weight:600;">{cnt}</span></div>'
        for src, cnt in sorted(source.items(), key=lambda x: -x[1])
    )

    return f"""
<div style="padding:24px 32px;max-width:1400px;margin:0 auto;">

  <!-- Top stat cards -->
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px;">
    <div class="stat-card"><span class="stat-num">{latest.get('total_jobs_scraped',0)}</span><span class="stat-label">Total roles scraped</span></div>
    <div class="stat-card"><span class="stat-num" style="color:#818cf8;">{latest.get('total_pm_roles',0)}</span><span class="stat-label">PM roles found</span></div>
    <div class="stat-card"><span class="stat-num">{latest.get('companies_hiring',0)}</span><span class="stat-label">Companies hiring</span></div>
    <div class="stat-card"><span class="stat-num" style="color:#4ade80;">{latest.get('companies_with_pm_roles',0)}</span><span class="stat-label">With PM openings</span></div>
    <div class="stat-card"><span class="stat-num" style="color:#fbbf24;">{len(history)}</span><span class="stat-label">Days tracked</span></div>
  </div>

  <!-- Signals row: New + Heating Up side by side -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:28px;">

    <div style="background:#13151f;border:1px solid #2d3148;border-radius:12px;padding:20px;">
      <div style="font-size:0.85rem;font-weight:700;color:#a3e635;margin-bottom:14px;">🆕 New This Run ({len(new_this_week)})</div>
      <div style="font-size:0.75rem;color:#475569;margin-bottom:12px;">Companies with PM openings that had none in the previous snapshot</div>
      {new_cards_html}
    </div>

    <div style="background:#13151f;border:1px solid #2d3148;border-radius:12px;padding:20px;">
      <div style="font-size:0.85rem;font-weight:700;color:#fbbf24;margin-bottom:14px;">🔥 Heating Up ({len(heating_up)})</div>
      <div style="font-size:0.75rem;color:#475569;margin-bottom:12px;">PM role count increased over the last 3+ weeks</div>
      {heating_cards_html}
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-bottom:28px;">

    <!-- Trend chart -->
    <div style="background:#1a1d27;border:1px solid #2d3148;border-radius:12px;padding:20px;">
      <div style="font-size:0.85rem;font-weight:700;color:#94a3b8;margin-bottom:14px;">📈 PM Roles Over Time</div>
      <canvas id="trendChart" height="160"></canvas>
    </div>

    <!-- Seniority -->
    <div style="background:#1a1d27;border:1px solid #2d3148;border-radius:12px;padding:20px;">
      <div style="font-size:0.85rem;font-weight:700;color:#94a3b8;margin-bottom:14px;">🎓 Seniority Mix</div>
      {seniority_rows if seniority_rows else '<div style="color:#475569;font-size:0.82rem;">No data yet</div>'}
    </div>

    <!-- Work type -->
    <div style="background:#1a1d27;border:1px solid #2d3148;border-radius:12px;padding:20px;">
      <div style="font-size:0.85rem;font-weight:700;color:#94a3b8;margin-bottom:14px;">🌐 Work Type (PM roles)</div>
      {wt_rows if wt_rows else '<div style="color:#475569;font-size:0.82rem;">No data yet</div>'}
    </div>
  </div>

  <div style="display:grid;grid-template-columns:3fr 1fr;gap:20px;">

    <!-- Full company table -->
    <div style="background:#1a1d27;border:1px solid #2d3148;border-radius:12px;overflow:hidden;">
      <div style="padding:16px 20px;border-bottom:1px solid #2d3148;font-size:0.85rem;font-weight:700;color:#94a3b8;">
        🏢 All Companies With PM Openings ({len(pm_companies)})
      </div>
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:0.82rem;">
          <thead>
            <tr style="border-bottom:1px solid #2d3148;">
              <th style="text-align:left;padding:10px 16px;color:#64748b;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;">Company</th>
              <th style="text-align:center;padding:10px 16px;color:#64748b;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;">PM</th>
              <th style="text-align:center;padding:10px 16px;color:#64748b;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;">All</th>
              <th style="text-align:left;padding:10px 16px;color:#64748b;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;">Titles</th>
              <th style="text-align:left;padding:10px 16px;color:#64748b;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;">Stage</th>
              <th style="text-align:left;padding:10px 16px;color:#64748b;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;">Funding</th>
            </tr>
          </thead>
          <tbody>{company_rows}</tbody>
        </table>
      </div>
    </div>

    <!-- Source breakdown -->
    <div style="background:#1a1d27;border:1px solid #2d3148;border-radius:12px;padding:20px;">
      <div style="font-size:0.85rem;font-weight:700;color:#94a3b8;margin-bottom:14px;">📡 Job Sources</div>
      {source_rows}
    </div>

  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
(function() {{
  const ctx = document.getElementById('trendChart');
  if (!ctx) return;
  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: {dates_js},
      datasets: [
        {{
          label: 'PM Roles',
          data: {total_js},
          borderColor: '#818cf8',
          backgroundColor: 'rgba(129,140,248,0.1)',
          fill: true,
          tension: 0.3,
          pointRadius: 4,
        }},
        {{
          label: 'All Roles',
          data: {scraped_js},
          borderColor: '#4ade80',
          backgroundColor: 'transparent',
          borderDash: [4,4],
          tension: 0.3,
          pointRadius: 3,
        }}
      ]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }} }},
      scales: {{
        x: {{ ticks: {{ color: '#475569', font: {{ size: 10 }} }}, grid: {{ color: '#1e2235' }} }},
        y: {{ ticks: {{ color: '#475569', font: {{ size: 10 }} }}, grid: {{ color: '#1e2235' }}, beginAtZero: true }}
      }}
    }}
  }});
}})();
</script>"""


# ---------------------------------------------------------------------------
# Performance tab — scraped jobs that never made it to Job Results
# ---------------------------------------------------------------------------

def _build_performance_tab(rejected_path: str = "./output/rejected_jobs.json") -> str:
    """Shows all jobs filtered out before or after scoring."""
    rejected = []
    if os.path.exists(rejected_path):
        try:
            with open(rejected_path) as f:
                rejected = json.load(f)
        except Exception:
            pass

    if not rejected:
        return (
            '<div style="padding:60px 32px;text-align:center;color:#475569;">'
            'No pipeline data yet — run the agent at least once to populate this tab.'
            '</div>'
        )

    # Sort newest first by first_analyzed
    rejected_sorted = sorted(rejected, key=lambda r: r.get("first_analyzed", ""), reverse=True)

    total            = len(rejected)
    pre_filter_count = sum(1 for r in rejected if r.get("rejection_type") == "pre_filter")
    low_score_count  = sum(1 for r in rejected if r.get("rejection_type") == "low_score")
    unique_companies = len({r.get("company", "") for r in rejected if r.get("company")})

    # ── Build table rows ──
    rows_html = ""
    for r in rejected_sorted:
        first_analyzed = r.get("first_analyzed", "")
        date_display = ""
        date_title_attr = ""
        if first_analyzed:
            try:
                dt = datetime.fromisoformat(first_analyzed)
                date_display    = dt.strftime("%b %d")
                date_title_attr = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_display    = first_analyzed[:10]
                date_title_attr = first_analyzed

        rtype = r.get("rejection_type", "")
        if rtype == "pre_filter":
            type_badge = (
                '<span style="display:inline-block;font-size:0.68rem;font-weight:700;'
                'padding:2px 8px;border-radius:5px;background:#1e1b4b;color:#818cf8;'
                'border:1px solid #3730a3;white-space:nowrap;">Pre-filter</span>'
            )
        else:
            type_badge = (
                '<span style="display:inline-block;font-size:0.68rem;font-weight:700;'
                'padding:2px 8px;border-radius:5px;background:#2a1f00;color:#fbbf24;'
                'border:1px solid #78350f;white-space:nowrap;">Low score</span>'
            )

        score = r.get("score")
        score_display = str(score) if score is not None else "—"
        score_color   = "#f87171" if score is not None else "#475569"

        url     = r.get("url", "#")
        company = r.get("company", "")
        title   = r.get("title", "")
        reason  = r.get("rejection_reason", "")
        loc_raw = r.get("location", "")
        location = (loc_raw[:34] + "…") if len(loc_raw) > 35 else loc_raw
        source  = r.get("source", "")
        search_text = (company + " " + title + " " + reason).lower().replace('"', '')

        rows_html += f"""
        <tr data-type="{rtype}" data-search="{search_text}">
          <td title="{date_title_attr}" style="white-space:nowrap;color:#64748b;font-size:0.8rem;">{date_display}</td>
          <td style="font-weight:600;color:#f1f5f9;">{company}</td>
          <td>
            <a href="{url}" target="_blank" onclick="event.stopPropagation()"
               style="color:#818cf8;text-decoration:none;font-size:0.85rem;">{title}</a>
          </td>
          <td>{type_badge}</td>
          <td style="color:#94a3b8;font-size:0.78rem;max-width:260px;line-height:1.4;">{reason}</td>
          <td style="text-align:center;color:{score_color};font-weight:600;">{score_display}</td>
          <td style="color:#64748b;font-size:0.75rem;">{location}</td>
          <td style="color:#475569;font-size:0.75rem;">{source}</td>
        </tr>"""

    return f"""
<div style="padding:24px 32px;max-width:1400px;margin:0 auto;">

  <!-- Stats row -->
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px;">
    <div class="stat-card">
      <span class="stat-num">{total}</span>
      <span class="stat-label">Total logged</span>
    </div>
    <div class="stat-card">
      <span class="stat-num" style="color:#818cf8;">{pre_filter_count}</span>
      <span class="stat-label">Pre-filtered</span>
    </div>
    <div class="stat-card">
      <span class="stat-num" style="color:#fbbf24;">{low_score_count}</span>
      <span class="stat-label">Low score</span>
    </div>
    <div class="stat-card">
      <span class="stat-num" style="color:#4ade80;">{unique_companies}</span>
      <span class="stat-label">Companies seen</span>
    </div>
  </div>

  <!-- Filter bar -->
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap;">
    <div style="display:flex;gap:6px;">
      <button onclick="filterPerf('')"           id="perfAll" class="perf-filter-btn active">All ({total})</button>
      <button onclick="filterPerf('pre_filter')" id="perfPre" class="perf-filter-btn">Pre-filter ({pre_filter_count})</button>
      <button onclick="filterPerf('low_score')"  id="perfLow" class="perf-filter-btn">Low Score ({low_score_count})</button>
    </div>
    <input type="text" id="perfSearch" placeholder="Search company, title, reason…"
           oninput="filterPerf(currentPerfFilter())"
           style="flex:1;min-width:200px;max-width:360px;padding:6px 12px;background:#1e2235;
                  border:1px solid #2d3148;border-radius:6px;color:#e2e8f0;font-size:0.82rem;">
    <span style="margin-left:auto;font-size:0.78rem;color:#475569;" id="perfCount">{total} rows</span>
  </div>

  <!-- Table -->
  <div style="background:#1a1d27;border:1px solid #2d3148;border-radius:12px;overflow:hidden;">
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:0.83rem;" id="perfTable">
        <thead>
          <tr style="border-bottom:1px solid #2d3148;background:#13151f;">
            <th style="text-align:left;padding:10px 14px;color:#64748b;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;white-space:nowrap;">First Analyzed</th>
            <th style="text-align:left;padding:10px 14px;color:#64748b;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;">Company</th>
            <th style="text-align:left;padding:10px 14px;color:#64748b;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;">Title</th>
            <th style="text-align:left;padding:10px 14px;color:#64748b;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;">Type</th>
            <th style="text-align:left;padding:10px 14px;color:#64748b;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;">Why Excluded</th>
            <th style="text-align:center;padding:10px 14px;color:#64748b;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;">Score</th>
            <th style="text-align:left;padding:10px 14px;color:#64748b;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;">Location</th>
            <th style="text-align:left;padding:10px 14px;color:#64748b;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;">Source</th>
          </tr>
        </thead>
        <tbody id="perfBody">
          {rows_html}
        </tbody>
      </table>
    </div>
  </div>
</div>

<script>
(function() {{
  let _activeType = '';
  window.currentPerfFilter = function() {{ return _activeType; }};
  window.filterPerf = function(type) {{
    _activeType = type;
    ['perfAll','perfPre','perfLow'].forEach(function(id) {{
      const el = document.getElementById(id);
      if (el) el.classList.remove('active');
    }});
    const btnMap = {{'': 'perfAll', 'pre_filter': 'perfPre', 'low_score': 'perfLow'}};
    const active = document.getElementById(btnMap[type]);
    if (active) active.classList.add('active');
    const search = (document.getElementById('perfSearch')?.value || '').toLowerCase();
    let visible = 0;
    document.querySelectorAll('#perfBody tr').forEach(function(row) {{
      const typeOk   = !type   || row.dataset.type   === type;
      const searchOk = !search || (row.dataset.search || '').includes(search);
      row.style.display = (typeOk && searchOk) ? '' : 'none';
      if (typeOk && searchOk) visible++;
    }});
    const c = document.getElementById('perfCount');
    if (c) c.textContent = visible + ' rows';
  }};
}})();
</script>"""


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

    jobs_tab_html   = _build_jobs_tab(jobs, run_time, crm=crm)
    crm_tab_html    = _build_crm_tab(crm)
    market_tab_html = _build_market_tab()
    perf_tab_html   = _build_performance_tab()

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
    .reasons {{ font-size: 0.78rem; margin-bottom: 10px; }}
    .reasons strong {{ color: #a78bfa; }}
    .reasons ul {{ margin-top: 5px; padding-left: 14px; color: #94a3b8; line-height: 1.6; }}
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

    /* ── Collapsible card body ── */
    .card-body {{ display: none; }}
    .card.expanded .card-body {{ display: flex; flex-direction: column; gap: 10px; }}
    .card.expanded {{ border-color: #4f6ef7 !important; }}

    /* ── Job tab: action queue / archive sections ── */
    .section-label {{ display: flex; align-items: center; gap: 8px; padding: 14px 32px 6px; font-size: 0.82rem; font-weight: 600; color: #94a3b8; }}
    .section-count {{ font-size: 0.72rem; background: #1e2235; color: #64748b; border: 1px solid #2d3148; border-radius: 20px; padding: 2px 8px; }}
    .archive-header {{ display: flex; align-items: center; justify-content: space-between; padding: 12px 32px; cursor: pointer; background: #13151f; border-top: 1px solid #2d3148; border-bottom: 1px solid #2d3148; color: #64748b; font-size: 0.82rem; margin-top: 8px; transition: background 0.15s, color 0.15s; }}
    .archive-header:hover {{ color: #94a3b8; background: #1a1d27; }}
    .apply-btn-dim {{ display: inline-block; background: #1e2235; color: #64748b; font-size: 0.82rem; font-weight: 600; padding: 8px 18px; border-radius: 7px; text-decoration: none; border: 1px solid #2d3148; }}
    .not-applied-btn {{ font-size: 0.78rem; font-weight: 600; padding: 5px 12px; border-radius: 6px; border: 1px solid #2d3148; background: #1e2235; color: #94a3b8; cursor: pointer; transition: all 0.2s; }}
    .not-applied-btn.active {{ background: #0f2e1a; color: #4ade80; border-color: #166534; }}

    /* ── Performance tab filter buttons ── */
    .perf-filter-btn {{ font-size: 0.78rem; font-weight: 600; padding: 5px 12px; border-radius: 6px; border: 1px solid #2d3148; background: #1e2235; color: #94a3b8; cursor: pointer; transition: all 0.2s; }}
    .perf-filter-btn.active {{ background: #1e1b4b; color: #818cf8; border-color: #3730a3; }}
    .perf-filter-btn:hover {{ color: #c7d2fe; }}
    #perfBody tr td {{ padding: 10px 14px; border-bottom: 1px solid #1e2235; vertical-align: top; }}
    #perfBody tr:hover td {{ background: #1e2235; }}
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
  <button class="tab-btn" onclick="switchTab('market', this)">📊 Market Intel</button>
  <button class="tab-btn" onclick="switchTab('perf', this)">📈 Performance</button>
</div>

<div id="tab-jobs" class="tab-content active">
  {jobs_tab_html}
</div>

<div id="tab-crm" class="tab-content">
  {crm_tab_html}
</div>

<div id="tab-market" class="tab-content">
  {market_tab_html}
</div>

<div id="tab-perf" class="tab-content">
  {perf_tab_html}
</div>

<script>
  function switchTab(name, btn) {{
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    btn.classList.add('active');
  }}

  function toggleCard(event, el) {{
    if (event.target.closest('.apply-btn, .apply-btn-dim')) return;
    el.classList.toggle('expanded');
  }}

  let notAppliedActive = false;
  let archiveOpen = false;

  function toggleNotApplied() {{
    notAppliedActive = !notAppliedActive;
    const btn = document.getElementById('notAppliedBtn');
    btn.classList.toggle('active', notAppliedActive);
    btn.textContent = notAppliedActive ? '✅ Not applied only' : '✉️ Not applied only';
    applyFilters();
  }}

  function toggleArchive() {{
    archiveOpen = !archiveOpen;
    const grid = document.getElementById('archiveGrid');
    if (grid) grid.classList.toggle('hidden', !archiveOpen);
    const arrow = document.getElementById('archiveArrow');
    if (arrow) arrow.textContent = archiveOpen ? '▲ Hide' : '▼ Show';
  }}

  function applySort() {{
    const order = document.getElementById('sortOrder').value;
    const grid  = document.getElementById('grid');
    const cards = Array.from(grid.querySelectorAll('.card'));
    if (order === 'score') {{
      cards.sort((a, b) => parseInt(b.dataset.score) - parseInt(a.dataset.score));
    }} else {{
      cards.sort((a, b) => parseInt(a.dataset.index || 0) - parseInt(b.dataset.index || 0));
    }}
    cards.forEach(c => grid.appendChild(c));
  }}

  function applyFilters() {{
    const minScore = parseInt(document.getElementById('scoreFilter').value);
    const rec  = document.getElementById('recFilter').value;
    const work = document.getElementById('workFilter').value;
    const tier = document.getElementById('tierFilter').value;
    const cards = document.querySelectorAll('#grid .card');
    let visible = 0;
    cards.forEach(c => {{
      const ok = (
        parseInt(c.dataset.score) >= minScore &&
        (!rec  || c.dataset.rec  === rec)  &&
        (!work || c.dataset.work === work) &&
        (!tier || c.dataset.tier === tier) &&
        (!notAppliedActive || c.dataset.applied !== 'true')
      );
      c.classList.toggle('hidden', !ok);
      if (ok) visible++;
    }});
    document.getElementById('countBadge').textContent = visible + ' jobs in queue';
    const badge = document.getElementById('actionCountBadge');
    if (badge) badge.textContent = visible;
    document.getElementById('emptyState').classList.toggle('hidden', visible > 0);
    applySort();
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
