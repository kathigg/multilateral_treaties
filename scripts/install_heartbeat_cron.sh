#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="${BRANCH:-main}"

if ! command -v crontab >/dev/null 2>&1; then
  echo "crontab not found; install cron (or use systemd timers) and rerun." >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/run_status"

CRON_LINE="*/30 * * * * cd \"$ROOT_DIR\" && BRANCH=\"$BRANCH\" bash scripts/push_heartbeat.sh >> \"$ROOT_DIR/logs/heartbeat_cron.log\" 2>&1"

mkdir -p "$ROOT_DIR/logs"

existing="$(crontab -l 2>/dev/null || true)"
if echo "$existing" | grep -Fq "bash scripts/push_heartbeat.sh"; then
  echo "Heartbeat cron entry already installed." >&2
  exit 0
fi

{
  echo "$existing"
  echo "$CRON_LINE"
} | crontab -

echo "Installed cron entry:"
echo "$CRON_LINE"
