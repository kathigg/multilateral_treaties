# Multilateral Treaties OCR Pipeline

## May 15th, 10:20am:
- A quick note to self that I think we should feed in abbreviations into the model. That is something we cannot risk the model having to infer. They are contained in the preface to most of the documents. Example: ICBMs. 


Note to self: To ssh, use ```ssh kathigg@128.4.20.143```.

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

Or use the repo bootstrap script:

```bash
bash scripts/bootstrap_ocr_env.sh
```

## Run The Full `us_data` Batch

```bash
source .venv/bin/activate
python scripts/process_us_data.py \
  --input-root us_data \
  --output-root artifacts/us_data_cleaning \
  --workers 4
```

Or use the wrapper script with logging:

```bash
bash scripts/run_us_data_batch.sh
```

Useful variants:

```bash
python scripts/process_us_data.py --match Kennedy --max-docs 2
python scripts/process_us_data.py --keep-page-artifacts
python scripts/process_us_data.py --method ocr
bash scripts/run_us_data_batch.sh --match Kennedy --max-docs 2
```

## Remote Workflow

For a new server, the clean path is:

```bash
ssh kathigg@128.4.20.143
git clone https://github.com/kathigg/multilateral_treaties.git
cd multilateral_treaties
bash scripts/bootstrap_ocr_env.sh
```

Then start the full run inside `tmux` so it survives disconnects:

```bash
tmux new -s treaties
cd ~/multilateral_treaties
bash scripts/run_us_data_batch.sh
```

Detach from `tmux` with `Ctrl-b` then `d`, and reattach with:

```bash
tmux attach -t treaties
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

## Spotcheck Exports (Remove TOC/Front Matter)

For sharing/spot-checking, you can export a per-document `final_text.txt` that removes table-of-contents-like lines and light front matter from the document-level output.

```bash
source .venv/bin/activate
python scripts/export_spotcheck_texts.py \
  --input-root artifacts/us_data_cleaning \
  --output-root artifacts/us_data_spotcheck \
  --source clean_text
```

Each document gets:

- `final_text.txt`
- `final_text.metadata.txt` (removal counts)
- `final_text.metadata.json` (removal counts + the stripped imprint block)

### What Gets Removed

This exporter is intentionally aggressive about removing front matter and publishing metadata so humans can spot-check the substantive body text:

- Publication/imprint blocks (e.g., FRUS title pages: `FOREIGN RELATIONS OF THE UNITED STATES`, `VOLUME ...`, `DEPARTMENT OF STATE`, `United States Government Publishing Office`, editors, `Office of the Historian`, `Washington`, etc.). These lines are saved under `imprint_lines` in `final_text.metadata.json`.
- Entire front-matter sections when the exporter sees headings like `Preface`, `About the series`, `About the electronic edition`, `Sources`, `Abbreviations and terms`, `Glossary`, etc.
- Table-of-contents / index headings and TOC-like rows (dotted leaders + page numbers).
- Page-number-only lines anywhere (including roman numerals and forms like `Page 12` or `p. 12`).
- Link/email lines anywhere (URLs, `www.*`, `user@domain`).
- Editorial/source-note footnotes (e.g., `Source: ...`, archival citations like `Library`, `Records`, `OA/ID`, `No classification marking`, etc.). These are saved under `source_note_blocks` in `final_text.metadata.json`.
