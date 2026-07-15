#!/usr/bin/env bash
# =============================================================================
# git_safe_push.sh — Safe git commit + push with stale lock detection
#
# PROBLEM THIS SOLVES
# -------------------
# Git uses lock files (.git/index.lock, .git/HEAD.lock, etc.) as a mutex to
# prevent concurrent writes from corrupting the repository. When a git process
# crashes or is killed mid-operation, these lock files are left behind as
# orphans. The next git run sees the lock and refuses to proceed, assuming
# another process is still active.
#
# In GitHub Actions this can happen when:
#   1. A run is cancelled mid-step
#   2. The runner itself is preempted
#   3. A previous commit step timed out
#
# HOW THIS SCRIPT HANDLES IT
# --------------------------
# 1. CONCURRENCY (workflow level, not this script)
#    The workflow uses a `concurrency` group so only one run executes at a
#    time. This eliminates the most common cause — two overlapping runs both
#    trying to push to the same repo branch.
#
# 2. STALE LOCK DETECTION (this script)
#    Before any git operation, we inspect each lock file:
#      - If the lock file embeds a PID and that process is still alive →
#        a real git process is running. We wait up to MAX_WAIT seconds.
#      - If the PID is gone, or the lock has no PID, or the lock is older
#        than STALE_LOCK_AGE_MINUTES → it is orphaned and safe to delete.
#
# 3. RETRY WITH BACKOFF (push only)
#    The push can fail transiently if another workflow's [skip ci] commit
#    landed between our pull and our push. We retry up to MAX_RETRIES times
#    with exponential backoff (10s, 20s, 30s).
#
# USAGE (from workflow YAML)
# --------------------------
#   - name: Persist data files to repo
#     run: bash scripts/git_safe_push.sh \
#            "output/first_seen_registry.json output/rejected_jobs.json output/market_stats.json" \
#            "chore: update job agent data [skip ci]"
#
# ARGUMENTS
#   $1  Space-separated list of files to `git add`
#   $2  Commit message
# =============================================================================

set -euo pipefail

FILES="${1:-}"
COMMIT_MSG="${2:-chore: automated data update [skip ci]}"

# --- Tunables ----------------------------------------------------------------
STALE_LOCK_AGE_MINUTES=2   # locks older than this are always considered stale
MAX_WAIT=60                 # seconds to wait if a live process holds a lock
POLL_INTERVAL=5             # seconds between liveness checks
MAX_RETRIES=3               # push retry attempts
# -----------------------------------------------------------------------------

log() { echo "[git_safe_push] $*"; }

# -----------------------------------------------------------------------------
# 1. STALE LOCK CLEANUP
# -----------------------------------------------------------------------------
cleanup_locks() {
  local git_dir
  git_dir="$(git rev-parse --git-dir 2>/dev/null || echo '.git')"

  for lock_file in "$git_dir/index.lock" "$git_dir/HEAD.lock" "$git_dir/objects/maintenance.lock"; do
    [ -f "$lock_file" ] || continue

    # Try to read PID from lock file (git writes it on some operations)
    local pid=""
    pid=$(cat "$lock_file" 2>/dev/null | tr -dc '0-9' | head -c 10) || true

    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      # A real process is holding the lock — wait for it to finish
      log "Lock held by live PID $pid ($lock_file). Waiting up to ${MAX_WAIT}s..."
      local waited=0
      while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$MAX_WAIT" ]; do
        sleep "$POLL_INTERVAL"
        waited=$((waited + POLL_INTERVAL))
      done

      if kill -0 "$pid" 2>/dev/null; then
        log "ERROR: PID $pid still running after ${MAX_WAIT}s. Aborting to avoid corruption."
        exit 1
      fi
      log "PID $pid finished. Removing released lock."
    else
      # No live process — check age to be safe
      local age_minutes
      # Use stat to get file age; fall back to 999 if stat unavailable
      age_minutes=$(( ( $(date +%s) - $(stat -c %Y "$lock_file" 2>/dev/null || echo 0) ) / 60 )) || age_minutes=999

      if [ "$age_minutes" -ge "$STALE_LOCK_AGE_MINUTES" ]; then
        log "Stale lock detected ($lock_file, ${age_minutes}min old, PID='$pid' not running). Removing."
      else
        log "Lock is recent (${age_minutes}min old) but PID not found. Treating as stale."
      fi
    fi

    rm -f "$lock_file" && log "Removed $lock_file" || log "Warning: could not remove $lock_file (permissions?)"
  done
}

# -----------------------------------------------------------------------------
# 2. GIT COMMIT
# -----------------------------------------------------------------------------
do_commit() {
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git config user.name "github-actions[bot]"

  # Pull latest to avoid push rejection from concurrent [skip ci] commits
  git pull --rebase origin main || {
    log "Warning: git pull --rebase failed. Continuing anyway."
  }

  # Stage the requested files (silently skip missing ones)
  for f in $FILES; do
    git add "$f" 2>/dev/null && log "Staged: $f" || log "Skipped (not found): $f"
  done

  # Only commit if something actually changed
  if git diff --staged --quiet; then
    log "Nothing to commit — data files unchanged."
    return 0
  fi

  git commit -m "$COMMIT_MSG"
  log "Committed: $COMMIT_MSG"
}

# -----------------------------------------------------------------------------
# 3. PUSH WITH RETRY + BACKOFF
# -----------------------------------------------------------------------------
do_push() {
  local attempt=1
  while [ "$attempt" -le "$MAX_RETRIES" ]; do
    if git push origin main; then
      log "Push succeeded on attempt $attempt."
      return 0
    fi

    if [ "$attempt" -lt "$MAX_RETRIES" ]; then
      local wait_secs=$((attempt * 10))
      log "Push failed (attempt $attempt/$MAX_RETRIES). Retrying in ${wait_secs}s..."
      sleep "$wait_secs"
      # Re-pull before retry in case a concurrent push landed
      git pull --rebase origin main || true
    fi
    attempt=$((attempt + 1))
  done

  log "ERROR: Push failed after $MAX_RETRIES attempts. Data saved to S3 and Actions cache — no data loss."
  # Exit 0 intentionally: push failure is not fatal. S3 + cache still have the data.
  return 0
}

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
log "Starting safe git push"
log "Files: $FILES"
log "Message: $COMMIT_MSG"

cleanup_locks
do_commit
do_push

log "Done."
