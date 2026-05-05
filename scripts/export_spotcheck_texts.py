#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


TOC_START_RE = re.compile(
    r"^\s*(table of contents|contents|index|summary of contents)\s*$",
    re.IGNORECASE,
)

# Headings for sections we want to remove entirely (especially in front matter).
UNWANTED_SECTION_START_RE = re.compile(
    r"""^\s*(
        preface
        |foreword
        |introduction
        |about\s+the\s+series
        |about\s+the\s+electronic\s+edition
        |about\s+the\s+ebook
        |about\s+this\s+(?:book|volume|edition)
        |editor(?:'s)?\s+note
        |note\s+to\s+readers
        |acknowledg(?:ment|ments)
        |sources
        |source\s+notes?
        |bibliograph(?:y|ical)\s+note
        |list\s+of\s+abbreviations
        |abbreviations(?:\s+and\s+terms)?
        |glossary
        |terms\s+and\s+abbreviations
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

# Heuristic: an all-caps-ish line often indicates a major heading boundary.
ALL_CAPS_HEADING_RE = re.compile(r"^\s*[A-Z0-9][A-Z0-9 .,&'()/:;+-]{6,}\s*$")

# FRUS / publication-imprint style lines we want removed from the final text but preserved in metadata.
IMPRINT_KEYWORD_RE = re.compile(
    r"""^\s*(?:
        foreign\s+relations\s+of\s+the\s+united\s+states
        |united\s+states\s+government\s+(?:publishing|printing)\s+office
        |department\s+of\s+state
        |office\s+of\s+the\s+historian
        |bureau\s+of\s+administration
        |bureau\s+of\s+public\s+affairs
        |shared\s+knowledge\s+services
        |editor\b
        |general\s+editor\b
        |volume\s+[ivxlcdm0-9]+
        |washington\b
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

# Typical TOC entry patterns: dotted leaders + page number, or a title with a trailing page number.
TOC_LINE_RE = re.compile(
    r"""^
    \s*
    (?:[A-Z0-9][A-Z0-9 ,.'()/:;&-]{2,}|\w.*?)
    (?:\.{2,}\s*\d+\s*|\s+\d+\s*)  # dotted leaders or spaced page number
    $
    """,
    re.VERBOSE,
)

PAGE_NUMBER_ONLY_RE = re.compile(r"^\s*(?:\d+|[ivxlcdm]+)\s*$", re.IGNORECASE)
PAGE_WORD_NUMBER_RE = re.compile(r"^\s*(?:page|p\.?)\s*\d+\s*$", re.IGNORECASE)
LINK_LINE_RE = re.compile(r"^\s*(?:https?://\S+|www\.\S+)\s*$", re.IGNORECASE)
EMAIL_LINE_RE = re.compile(r"^\s*\S+@\S+\.\S+\s*$")

# Editorial/source-note footnotes frequently found in FRUS-style volumes.
SOURCE_NOTE_START_RE = re.compile(r"^\s*(?:\d+\s+)?Source:\s+", re.IGNORECASE)
REFERENCE_NOTE_START_RE = re.compile(r"^\s*\d+\s+Reference\s+is\s+to\b", re.IGNORECASE)
ARCHIVAL_CITATION_RE = re.compile(
    r"(?:\bLibrary\b|\bRecords\b|\bOA/ID\b|\bNo classification marking\b|\bSent through\b)",
    re.IGNORECASE,
)


@dataclass
class TrimResult:
    text: str
    removed_toc_lines: int
    removed_prefix_lines: int
    removed_unwanted_section_lines: int
    removed_page_number_lines: int
    removed_link_lines: int
    removed_imprint_lines: int
    imprint_lines: list[str]
    removed_source_note_lines: int
    source_note_blocks: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export spotcheck-ready per-document text from artifacts/us_data_cleaning by removing "
            "table-of-contents-like lines and light front matter."
        )
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path("artifacts/us_data_cleaning"),
        help="Root directory produced by scripts/process_us_data.py",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/us_data_spotcheck"),
        help="Output root for per-document final_text.txt exports",
    )
    parser.add_argument(
        "--source",
        choices=("clean_text", "prose_text"),
        default="clean_text",
        help="Which document-level file to export from each document directory.",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=40,
        help="Skip exporting documents with fewer than this many nonblank lines.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing final_text.txt outputs.",
    )
    return parser.parse_args()


def iter_document_dirs(input_root: Path) -> list[Path]:
    # Document dirs contain metadata.json + clean_text.txt by construction.
    return sorted(path.parent for path in input_root.rglob("metadata.json"))


def looks_like_toc_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if PAGE_NUMBER_ONLY_RE.fullmatch(stripped):
        return True
    if TOC_LINE_RE.fullmatch(stripped):
        return True
    return False


def looks_like_page_number_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(PAGE_NUMBER_ONLY_RE.fullmatch(stripped) or PAGE_WORD_NUMBER_RE.fullmatch(stripped))


def looks_like_link_or_email(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if LINK_LINE_RE.fullmatch(stripped):
        return True
    if "http://" in stripped.lower() or "https://" in stripped.lower():
        return True
    if EMAIL_LINE_RE.fullmatch(stripped):
        return True
    return False


def looks_like_abbreviation_entry(line: str) -> bool:
    # Common patterns:
    # - "ABC  ... explanation"
    # - "ABC—explanation"
    # - "ABC - explanation"
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > 200:
        return False
    if re.match(r"^[A-Z]{2,10}\s{1,6}\S", stripped):
        return True
    if re.match(r"^[A-Z]{2,10}\s*[-—:]\s+\S", stripped):
        return True
    return False


def looks_like_imprint_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if IMPRINT_KEYWORD_RE.fullmatch(stripped):
        return True
    # Many FRUS title-page lines are all-caps, short, and not prose.
    if ALL_CAPS_HEADING_RE.fullmatch(stripped) and not re.search(r"[a-z]{3,}", stripped):
        return True
    return False


def looks_like_prose(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    # Consider it "prose" when it contains a reasonable amount of lowercase text.
    return bool(re.search(r"[a-z]{4,}", stripped)) and len(stripped) >= 40


def looks_like_source_note_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if SOURCE_NOTE_START_RE.match(stripped):
        return True
    if REFERENCE_NOTE_START_RE.match(stripped):
        return True
    # Some notes omit "Source:" but are clearly archival citations.
    if re.match(r"^\s*\d+\s+", stripped) and ARCHIVAL_CITATION_RE.search(stripped):
        return True
    return False


def looks_like_source_note_continuation(line: str) -> bool:
    # Continuations tend to be indented or wrap as plain text without starting a new paragraph.
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("-", "—")):
        return True
    if re.match(r"^\s{2,}\S", line):
        return True
    if ARCHIVAL_CITATION_RE.search(stripped):
        return True
    # Wrapped citation lines often start with punctuation/quotes/parenthetical.
    if stripped[0] in "([\"'":
        return True
    return False


def strip_front_matter_and_toc(text: str) -> TrimResult:
    lines = text.splitlines()

    removed_toc = 0
    removed_prefix = 0
    removed_unwanted = 0
    removed_page_numbers = 0
    removed_links = 0
    removed_imprint = 0
    imprint_lines: list[str] = []
    removed_source_notes = 0
    source_note_blocks: list[str] = []

    out: list[str] = []
    in_toc = False
    toc_started = False
    toc_blank_run = 0
    in_unwanted_section = False
    unwanted_blank_run = 0
    unwanted_section_name: str | None = None
    in_imprint = True
    imprint_blank_run = 0
    saw_imprint_signal = False
    in_source_note = False
    current_source_note: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Strip editorial/source-note footnotes anywhere (save them in metadata).
        if in_source_note:
            if not stripped:
                # End of the note block.
                if current_source_note:
                    source_note_blocks.append("\n".join(current_source_note).strip())
                    current_source_note = []
                in_source_note = False
                removed_source_notes += 1
                continue

            if looks_like_source_note_continuation(line) or looks_like_source_note_start(line):
                current_source_note.append(stripped)
                removed_source_notes += 1
                continue

            # A non-continuation line ends the note block and gets processed normally.
            if current_source_note:
                source_note_blocks.append("\n".join(current_source_note).strip())
                current_source_note = []
            in_source_note = False

        if looks_like_source_note_start(line):
            in_source_note = True
            current_source_note = [stripped]
            removed_source_notes += 1
            continue

        # Drop links/emails anywhere.
        if looks_like_link_or_email(line):
            removed_links += 1
            continue

        # Drop page-number-only lines anywhere.
        if looks_like_page_number_line(line):
            removed_page_numbers += 1
            continue

        # Strip FRUS/publication imprint blocks at the very start of the document.
        # We only treat imprint as a prefix phenomenon: once we see real prose, we stop.
        if in_imprint:
            if not stripped:
                imprint_blank_run += 1
                # Keep a little whitespace in the imprint block for readability in metadata.
                imprint_lines.append("")
                removed_imprint += 1
                # Too much blank space before any signal: stop imprint mode.
                if imprint_blank_run >= 8 and not saw_imprint_signal:
                    in_imprint = False
                continue

            imprint_blank_run = 0

            if looks_like_imprint_line(line):
                saw_imprint_signal = True
                imprint_lines.append(stripped)
                removed_imprint += 1
                continue

            # If we've already seen imprint signals and we keep seeing heading-ish lines,
            # treat them as part of the imprint until prose appears.
            if saw_imprint_signal and (ALL_CAPS_HEADING_RE.fullmatch(stripped) or stripped in {"-", "—"}):
                imprint_lines.append(stripped)
                removed_imprint += 1
                continue

            # First real prose means imprint/title-page is over.
            if looks_like_prose(line):
                in_imprint = False
            else:
                # Before prose begins, treat short non-prose lines as imprint noise.
                if saw_imprint_signal and len(stripped) <= 80:
                    imprint_lines.append(stripped)
                    removed_imprint += 1
                    continue
                in_imprint = False

        # Detect explicit TOC start.
        if TOC_START_RE.fullmatch(stripped):
            toc_started = True
            in_toc = True
            removed_prefix += 1
            continue

        # Detect other unwanted sections (typically in front matter).
        if UNWANTED_SECTION_START_RE.fullmatch(stripped):
            in_unwanted_section = True
            unwanted_blank_run = 0
            unwanted_section_name = stripped.lower()
            removed_prefix += 1
            continue

        if in_unwanted_section:
            if not stripped:
                unwanted_blank_run += 1
                removed_unwanted += 1
                # Allow blank padding before deciding if section ended.
                if unwanted_blank_run >= 4:
                    in_unwanted_section = False
                    unwanted_section_name = None
                continue

            unwanted_blank_run = 0

            # For abbreviations sections, drop abbreviation-entry runs aggressively.
            if unwanted_section_name and "abbrev" in unwanted_section_name:
                if looks_like_abbreviation_entry(line):
                    removed_unwanted += 1
                    continue

            # TOC-style lines are also unwanted inside most front matter sections.
            if looks_like_toc_line(line):
                removed_unwanted += 1
                continue

            # An all-caps heading often marks the end of a front matter section.
            # Also end on lines that look like a normal paragraph.
            if ALL_CAPS_HEADING_RE.fullmatch(stripped) and not UNWANTED_SECTION_START_RE.fullmatch(stripped):
                in_unwanted_section = False
                unwanted_section_name = None
                # Keep this heading (it might be the first real section heading).
                out.append(line.rstrip())
                continue

            # Otherwise, drop the section line.
            removed_unwanted += 1
            continue

        if in_toc:
            if not stripped:
                toc_blank_run += 1
                # After a few blank lines, assume TOC section ended.
                if toc_blank_run >= 3:
                    in_toc = False
                removed_toc += 1
                continue

            toc_blank_run = 0

            # If it still looks like TOC/index material, drop it.
            if looks_like_toc_line(line):
                removed_toc += 1
                continue

            # A line that looks like a normal paragraph or heading ends TOC.
            in_toc = False

        # Light prefix trimming: before we hit any real content, drop obvious TOC-ish lines.
        if not out and not stripped:
            removed_prefix += 1
            continue
        if not out and toc_started and looks_like_toc_line(line):
            removed_prefix += 1
            continue

        out.append(line.rstrip())

    # Second pass: if the first substantial chunk is still TOC-ish (common in some scans),
    # drop leading runs of TOC-like lines up to the first "normal" paragraph.
    trimmed: list[str] = []
    dropping = True
    for line in out:
        stripped = line.strip()
        if dropping:
            if not stripped:
                removed_prefix += 1
                continue
            if looks_like_toc_line(line) and not re.search(r"[a-z]{3,}", stripped):
                removed_prefix += 1
                continue
            dropping = False
        trimmed.append(line)

    final = "\n".join(trimmed).strip()
    if final:
        final += "\n"
    return TrimResult(
        final,
        removed_toc,
        removed_prefix,
        removed_unwanted,
        removed_page_numbers,
        removed_links,
        removed_imprint,
        imprint_lines,
        removed_source_notes,
        source_note_blocks,
    )


def count_nonblank_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def main() -> None:
    args = parse_args()
    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()

    if not input_root.exists():
        raise SystemExit(f"Input root does not exist: {input_root}")

    output_root.mkdir(parents=True, exist_ok=True)

    source_filename = "clean_text.txt" if args.source == "clean_text" else "prose_text.txt"
    doc_dirs = iter_document_dirs(input_root)
    if not doc_dirs:
        raise SystemExit(f"No documents found under {input_root}")

    exported = 0
    skipped = 0

    for doc_dir in doc_dirs:
        source_path = doc_dir / source_filename
        if not source_path.exists():
            skipped += 1
            continue

        relative = doc_dir.relative_to(input_root)
        out_dir = output_root / relative
        out_path = out_dir / "final_text.txt"

        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue

        raw = source_path.read_text(encoding="utf-8", errors="replace")
        if count_nonblank_lines(raw) < args.min_lines:
            skipped += 1
            continue

        trimmed = strip_front_matter_and_toc(raw)

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(trimmed.text, encoding="utf-8")

        meta_txt_path = out_dir / "final_text.metadata.txt"
        meta_txt_path.write_text(
            "\n".join(
                [
                    f"source={source_path}",
                    f"removed_prefix_lines={trimmed.removed_prefix_lines}",
                    f"removed_toc_lines={trimmed.removed_toc_lines}",
                    f"removed_unwanted_section_lines={trimmed.removed_unwanted_section_lines}",
                    f"removed_page_number_lines={trimmed.removed_page_number_lines}",
                    f"removed_link_lines={trimmed.removed_link_lines}",
                    f"removed_imprint_lines={trimmed.removed_imprint_lines}",
                    f"removed_source_note_lines={trimmed.removed_source_note_lines}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        meta_json_path = out_dir / "final_text.metadata.json"
        meta_json_path.write_text(
            json.dumps(
                {
                    "source": str(source_path),
                    "removed_prefix_lines": trimmed.removed_prefix_lines,
                    "removed_toc_lines": trimmed.removed_toc_lines,
                    "removed_unwanted_section_lines": trimmed.removed_unwanted_section_lines,
                    "removed_page_number_lines": trimmed.removed_page_number_lines,
                    "removed_link_lines": trimmed.removed_link_lines,
                    "removed_imprint_lines": trimmed.removed_imprint_lines,
                    # Saved for audit/spot-checking what was stripped.
                    "imprint_lines": trimmed.imprint_lines,
                    "removed_source_note_lines": trimmed.removed_source_note_lines,
                    # Saved for audit/spot-checking what was stripped.
                    "source_note_blocks": trimmed.source_note_blocks,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        exported += 1

    print(f"Exported {exported} documents to {output_root}")
    print(f"Skipped {skipped} documents")


if __name__ == "__main__":
    main()
