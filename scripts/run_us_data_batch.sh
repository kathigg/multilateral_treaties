#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$ROOT_DIR/artifacts/us_data_cleaning}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"
WORKERS="${WORKERS:-4}"

if [ ! -d "$VENV_DIR" ]; then
  echo "Virtual environment not found at $VENV_DIR" >&2
  echo "Run scripts/bootstrap_ocr_env.sh first." >&2
  exit 1
fi

cd "$ROOT_DIR"

mkdir -p "$LOG_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_PATH="$LOG_DIR/us_data_cleaning_$TIMESTAMP.log"

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

echo "Starting batch run..."
echo "Log: $LOG_PATH"
echo "Output root: $OUTPUT_ROOT"
echo "Workers: $WORKERS"

python scripts/process_us_data.py \
  --input-root us_data \
  --output-root "$OUTPUT_ROOT" \
  --workers "$WORKERS" \
  "$@" 2>&1 | tee "$LOG_PATH"

echo
echo "Run complete."
echo "Manifest: $OUTPUT_ROOT/run_manifest.json"
echo "Log: $LOG_PATH"
