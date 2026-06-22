# MATRS Spring 2026 Summary

Hello! It’s me, Kathleen. Here’s a quick wrap-up for where we ended up being for the
MATRS semester and long term study design.

You can find this identical (near-identical, at the least) writeup also on our Github
Readme: https://github.com/kathigg/multilateral_treaties

## The Path Forward

1. Make decisions on what we want the AI model to do. This is the most crucial
   element of the entire project. It requires you to envision what you want the final
   paper to talk about, and to fundamentally decide what questions you want
   answered. For example:

   a. What emotions do we want to give to the AI model?

      i. My opinion: The entire emotion wheel. Let the model figure it out
      and do what it does best.

   b. How do we want to feed the data to the AI model? Paragraph level,
      correspondence level, or article level?

      i. My opinion: I am strongly against trying multiple of these levels. I
      believe we should pick one level and run with it. The problem isn’t
      that the computer can’t do it, but that it will become so complicated
      that we won’t know what to do with it. I’d strongly recommend the
      correspondence level as the correct level of granularity.

   c. Who do we want to look at sentiment towards? Country to country?
      Country to self? Sentiment in the correspondence, generally?

      i. I’d recommend doing general correspondence sentiment and country
      to country sentiment analysis. The key is the general
      sentiment—having this, we can answer a question, like, “Does a
      hegemon become more aggressive in sentiment as it declines?”

2. Build the AI model. To be honest, I’m a lot less concerned about this part. What
   we’re doing here isn’t novel.

   a. In respect to Professor Silber’s concerns that if we used a pretrained
      model, we’d be incorporating bias (e.g. the model already knows what is
      going to happen), I think that is completely unavoidable. We cannot train
      our own model on this (a model with no knowledge of history), it would be
      massively computationally expensive. I think the goal should be to get this
      project out there, not to slowroll ourselves.

3. Data analysis and paper writing. This is where Professor Denemark heavily comes
   in. Professor Denemark, what big questions do you want answered in the
   paper? I’d recommend writing a list of the things you’re most curious about in
   really simple language, so poor computer science souls like I can understand. This
   is what you should be thinking about from the beginning.

## Study Design

Step 1: Decide on questions (described more above). This is the current step we are on.
We have an array of data in the form of documents, each of which are very long and can
be challenging to OCR. Our goal is to analyze how sentiment in treaties changes over
time through three relationships:

1. General sentiment (e.g. American is sad in this correspondence)
2. Hegemon sentiment toward another country (ex. America’s opinion of Japan)
3. And possibly, (Hasan) hegemon sentiment towards itself.

Step 2: OCR. Process all the PDFs into clean text that can be plugged into an AI model.
It doesn’t have to be great or glamorous.

- What we’ve done: Successfully written scripts that do OCR on a large level.
  Problem: They may still have issues. They will need a deeper read from someone
  like Alexa.

Step 3: Process the cleantext via the AI model. The output will be, on a large scale, all
of our documents annotated by the correspondence level for all of the data elements listed
(ex. Emotion, policy category, etc).

**Emotion**

What is the emotion of this specific communication?

**Target Country**

Which country is this communication directed toward or primarily discussing?

**Emotion Toward That Country**

What emotion is expressed toward that country?

**Time Period**

What time period is being discussed?

Please be specific when possible.

**Source**

Who is speaking or sending the communication?

Again, be as granular as possible:

- individual
- office
- organization
- country

**Treaty / Policy Category**

What category does this correspondence fall under? (Note: I don’t know what the
categories are in Global Politics research land. I made these example categories
up).

Examples:

- economic
- military
- diplomatic
- trade
- Intelligence

Step 4: Visualize and analyze the data. Using numpy, Seaborn, etc. Paper writing.

## Data

We are storing our data through an array of systems. Keith is the reference for the British
data. Alex Nolin (graduated) was the reference for the American data. The American data
is now stored in GitHub. https://github.com/kathigg/multilateral_treaties
Our data is separated into two groups:

- British
- American (us_data in GitHub)

Each of these folders has an array of subfolders, for example, in the American data:

- us_data
  - T Roosevelt, 1901-1909/Roosevelt
    - Annual Message 1904.pdf

Each president receives their own folder.

I have approached data cleaning via a slightly fancier version of OCR. The code used to
data clean can be found here:
https://github.com/kathigg/multilateral_treaties/tree/main/scripts

## Code

All of our code can currently be found in scripts/. Here is what each file in
scripts/ does. I would suggest using this as an index reference, rather than
reading all of it. A lot of the code are helpers. Commands to run scripts will be
documented in the next section.

- [process_us_data.py](/Users/kathleenhiggins/multilateral_treaties/scripts/process_us_data.py) is the main pipeline. It walks us_data/, processes each PDF,
  prefers embedded PDF text when available, falls back to OCR when needed, and
  writes document-level outputs to artifacts/us_data_cleaning/. This is
  the script you run for bulk data cleaning.

- [ocr_page.py](/Users/kathleenhiggins/multilateral_treaties/scripts/ocr_page.py)
  handles one page image at a time. It preprocesses the image, calls Tesseract, parses
  OCR confidence info, and helps build page-level text.

- [clean_raw_ocr_text.py](/Users/kathleenhiggins/multilateral_treaties/scripts/clean_raw_ocr_text.py) is the low-level line cleaner for raw OCR text. It removes
  obvious page headers, table-like rows, and noisy lines.

- [export_spotcheck_texts.py](/Users/kathleenhiggins/multilateral_treaties/scripts/export_spotcheck_texts.py) takes the document outputs from
  artifacts/us_data_cleaning/ and produces more human-readable
  final_text.txt files in artifacts/us_data_spotcheck/. This is
  where the front matter / footnote / navigation stripping happens.

- [run_us_data_batch.sh](/Users/kathleenhiggins/multilateral_treaties/scripts/run_us_data_batch.sh) is a shell wrapper around process_us_data.py. It
  activates the venv, runs the batch job, and writes a timestamped log file.

- [bootstrap_ocr_env.sh](/Users/kathleenhiggins/multilateral_treaties/scripts/bootstrap_ocr_env.sh) sets up the environment: checks Python, installs
  tesseract-ocr if needed, creates .venv, and installs Python dependencies.

- [push_heartbeat.sh](/Users/kathleenhiggins/multilateral_treaties/scripts/push_heartbeat.sh) is a cron-friendly helper for long remote runs. It writes small progress
  files under run_status/ and pushes those status updates.

- [install_heartbeat_cron.sh](/Users/kathleenhiggins/multilateral_treaties/scripts/install_heartbeat_cron.sh) installs the cron entry that runs push_heartbeat.sh
  periodically.

- [__init__.py](/Users/kathleenhiggins/multilateral_treaties/scripts/__init__.py) just
  makes scripts importable as a Python package.

## Useful Commands

If you want to data-clean all documents into artifacts/us_data_cleaning/:

```bash
source .venv/bin/activate
python scripts/process_us_data.py \
   --input-root us_data \
   --output-root artifacts/us_data_cleaning \
   --workers 4
```

If you want the more human-readable final_text.txt exports for all cleaned
documents after that:

```bash
source .venv/bin/activate
python scripts/export_spotcheck_texts.py \
   --input-root artifacts/us_data_cleaning \
   --output-root artifacts/us_data_spotcheck \
   --source clean_text
```

If you want to clean one specific document, use --match with a distinctive substring
from its path or filename. Example for Bush start.pdf:

```bash
source .venv/bin/activate
python scripts/process_us_data.py \
   --input-root us_data \
   --output-root artifacts/us_data_cleaning \
   --match "Bush start" \
   --workers 4
```

If you then want the spotcheck/final export for just that cleaned document:

```bash
source .venv/bin/activate
python scripts/export_spotcheck_texts.py \
   --input-root artifacts/us_data_cleaning \
   --output-root artifacts/us_data_spotcheck \
   --match "Bush start" \
   --source clean_text
```

## Practical note

process_us_data.py skips already-completed document outputs unless you add
--overwrite.


# Multilateral Treaties OCR Pipeline

## May 15th, 10:20am:
- A quick note to self that I think we should feed in abbreviations into the model. That is something we cannot risk the model having to infer. They are contained in the preface to most of the documents. Example: ICBMs.
- Also, we ought to include the names of the people, as well. 


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
