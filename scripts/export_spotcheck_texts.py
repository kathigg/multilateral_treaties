#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


@dataclass
class TrimResult:
    text: str
    removed_toc_lines: int
    removed_prefix_lines: int
    removed_unwanted_section_lines: int
    removed_page_number_lines: int
    removed_link_lines: int


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


def strip_front_matter_and_toc(text: str) -> TrimResult:
    lines = text.splitlines()

    removed_toc = 0
    removed_prefix = 0
    removed_unwanted = 0
    removed_page_numbers = 0
    removed_links = 0

    out: list[str] = []
    in_toc = False
    toc_started = False
    toc_blank_run = 0
    in_unwanted_section = False
    unwanted_blank_run = 0
    unwanted_section_name: str | None = None

    for line in lines:
        stripped = line.strip()

        # Drop links/emails anywhere.
        if looks_like_link_or_email(line):
            removed_links += 1
            continue

        # Drop page-number-only lines anywhere.
        if looks_like_page_number_line(line):
            removed_page_numbers += 1
            continue

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

        meta_path = out_dir / "final_text.metadata.txt"
        meta_path.write_text(
            "\n".join(
                [
                    f"source={source_path}",
                    f"removed_prefix_lines={trimmed.removed_prefix_lines}",
                    f"removed_toc_lines={trimmed.removed_toc_lines}",
                    f"removed_unwanted_section_lines={trimmed.removed_unwanted_section_lines}",
                    f"removed_page_number_lines={trimmed.removed_page_number_lines}",
                    f"removed_link_lines={trimmed.removed_link_lines}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        exported += 1

    print(f"Exported {exported} documents to {output_root}")
    print(f"Skipped {skipped} documents")


if __name__ == "__main__":
    main()
