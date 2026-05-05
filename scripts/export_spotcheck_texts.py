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


@dataclass
class TrimResult:
    text: str
    removed_toc_lines: int
    removed_prefix_lines: int


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


def strip_front_matter_and_toc(text: str) -> TrimResult:
    lines = text.splitlines()

    removed_toc = 0
    removed_prefix = 0

    out: list[str] = []
    in_toc = False
    toc_started = False
    toc_blank_run = 0

    for line in lines:
        stripped = line.strip()

        # Detect explicit TOC start.
        if TOC_START_RE.fullmatch(stripped):
            toc_started = True
            in_toc = True
            removed_prefix += 1
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
    return TrimResult(final, removed_toc, removed_prefix)


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

