#!/usr/bin/env bash
set -euo pipefail

# Cron-friendly helper:
# - checks if a recorded batch PID is still running
# - writes a heartbeat/progress file into run_status/
# - commits + pushes those small status files
#
# This is designed to avoid ever pushing large generated artifacts.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUN_PID_FILE="${RUN_PID_FILE:-$ROOT_DIR/run_status/batch.pid}"
RUN_STATUS_FILE="${RUN_STATUS_FILE:-$ROOT_DIR/run_status/heartbeat.txt}"
PROGRESS_FILE="${PROGRESS_FILE:-$ROOT_DIR/run_status/progress.txt}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$ROOT_DIR/artifacts/us_data_cleaning}"
BRANCH="${BRANCH:-main}"

now_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

require_git_auth() {
  # Ensure we are configured to push without prompting.
  # We support GitHub SSH remotes only, because HTTPS often prompts for credentials.
  local url
  url="$(git remote get-url origin 2>/dev/null || true)"
  if [[ -z "$url" ]]; then
    echo "origin remote is not configured" >&2
    exit 2
  fi
  if [[ "$url" != git@github.com:* ]]; then
    echo "origin is not an SSH GitHub remote (expected git@github.com:...): $url" >&2
    echo "Fix with: git remote set-url origin git@github.com:<user>/<repo>.git" >&2
    exit 2
  fi

  # Best-effort auth check; this will fail fast if the key is missing/blocked.
  GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes}" git ls-remote -h origin "$BRANCH" >/dev/null
}

pid_is_running() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

write_progress() {
  mkdir -p "$(dirname "$RUN_STATUS_FILE")"

  local page_files=0
  if [[ -d "$OUTPUT_ROOT" ]]; then
    # Cheap proxy for progress when --keep-page-artifacts is enabled.
    page_files="$(find "$OUTPUT_ROOT" -type f -path '*/pages/page_*/*' 2>/dev/null | wc -l | tr -d ' ')"
  fi

  printf "heartbeat_utc=%s\n" "$(now_iso)" > "$RUN_STATUS_FILE"
  printf "page_artifact_files=%s\n" "$page_files" > "$PROGRESS_FILE"
}

commit_and_push() {
  # Only commit when there is something new.
  if git diff --quiet -- run_status; then
    return 0
  fi

  git add run_status
  git commit -m "heartbeat: $(now_iso)" >/dev/null
  git push origin "$BRANCH" >/dev/null
}

main() {
  if [[ ! -f "$RUN_PID_FILE" ]]; then
    echo "No PID file found at $RUN_PID_FILE; nothing to do." >&2
    exit 0
  fi

  local pid
  pid="$(tr -d ' \n\r\t' < "$RUN_PID_FILE")"
  if ! pid_is_running "$pid"; then
    echo "Recorded PID $pid is not running; stopping heartbeats." >&2
    exit 0
  fi

  require_git_auth
  write_progress
  commit_and_push
}

main "$@"

