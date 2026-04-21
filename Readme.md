# Multilateral Treaties OCR Pipeline

This repository now includes a batch pipeline for cleaning every PDF under `us_data`.

The pipeline is designed for CPU-only servers:

- It prefers embedded PDF text when a page already has usable text.
- It falls back to Tesseract OCR only for pages that need it.
- It is resumable at the document level, so rerunning the same command skips completed outputs.
- It keeps document-level outputs by default and only stores page-level debug artifacts when asked.

## Server Setup

The target machine needs free disk space first. If `df -h ~` shows `Avail 0`, the run will fail even before OCR starts.

Once storage is available, install the system dependency and create a virtual environment:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv tesseract-ocr
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-ocr.txt
```

## Run The Full `us_data` Batch

```bash
source .venv/bin/activate
python scripts/process_us_data.py \
  --input-root us_data \
  --output-root artifacts/us_data_cleaning \
  --workers 4
```

Useful variants:

```bash
python scripts/process_us_data.py --match Kennedy --max-docs 2
python scripts/process_us_data.py --keep-page-artifacts
python scripts/process_us_data.py --method ocr
```

## Output Layout

Each PDF gets a mirrored directory under `artifacts/us_data_cleaning`, for example:

```text
artifacts/us_data_cleaning/Carter, 1977-1980/Carter Soviet Union/
```

Each document directory contains:

- `raw_text.txt`: page text joined in document order
- `clean_text.txt`: line-filtered text with headers, table-like rows, and obvious noise removed
- `prose_text.txt`: more aggressively normalized prose output
- `metadata.json`: processing summary, method counts, failures, and OCR confidence summary

The run root also gets:

- `run_manifest.json`: one summary entry per processed document

If `--keep-page-artifacts` is enabled, each document also gets a `pages/` directory with per-page text and OCR debug files.
