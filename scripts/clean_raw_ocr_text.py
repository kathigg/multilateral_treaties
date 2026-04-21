#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


PAGE_HEADER_RE = re.compile(r"^\s*\d+\s+[A-Z][A-Z .,&'()/-]+\.?\s*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove page-number headers and table-like lines from OCR raw text."
    )
    parser.add_argument("input_path", type=Path, help="Path to raw_text.txt")
    parser.add_argument("output_path", type=Path, help="Path for cleaned output text")
    return parser.parse_args()


def numeric_groups(line: str) -> list[str]:
    return re.findall(r"\d[\d,]*", line)


def looks_like_page_header(line: str) -> bool:
    return bool(PAGE_HEADER_RE.fullmatch(line.strip()))


def looks_like_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if "Whence derived." in stripped:
        return True
    if stripped.count("Francs.") >= 2:
        return True
    if "|" in stripped:
        return True
    if "Increase." in stripped and "nution" in stripped:
        return True

    groups = numeric_groups(stripped)
    alpha = sum(char.isalpha() for char in stripped)

    if len(groups) >= 3:
        return True
    if len(groups) >= 2 and alpha <= 3:
        return True
    return False


def looks_like_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    alpha = sum(char.isalpha() for char in stripped)
    punctuation = sum(char in "._-—=:;[](){}~/\\|`" for char in stripped)
    digit_count = sum(char.isdigit() for char in stripped)

    if re.fullmatch(r"[\W_]+", stripped):
        return True
    if alpha < 8 and punctuation >= 3:
        return True
    if alpha == 0 and punctuation >= 2 and digit_count == 0:
        return True
    return False


def classify_line(line: str) -> str:
    if not line.strip():
        return "blank"
    if looks_like_page_header(line):
        return "page_header"
    if looks_like_table_line(line):
        return "table"
    if looks_like_noise(line):
        return "noise"
    return "keep"


def collapse_blank_runs(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        cleaned.append(line.rstrip())
        previous_blank = blank
    return cleaned


def clean_text_content(text: str) -> tuple[str, dict[str, object]]:
    lines = text.splitlines()

    kept_lines: list[str] = []
    counts: Counter[str] = Counter()

    for line in lines:
        label = classify_line(line)
        counts[label] += 1
        if label in {"blank", "keep"}:
            kept_lines.append(line)

    final_lines = collapse_blank_runs(kept_lines)
    output_text = "\n".join(final_lines).strip()
    if output_text:
        output_text += "\n"

    metadata = {
        "line_counts": dict(counts),
        "kept_nonblank_lines": sum(1 for line in final_lines if line.strip()),
    }
    return output_text, metadata


def main() -> None:
    args = parse_args()
    text = args.input_path.read_text(encoding="utf-8")
    output_text, summary = clean_text_content(text)

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(output_text, encoding="utf-8")

    metadata_path = args.output_path.with_suffix(args.output_path.suffix + ".metadata.json")
    metadata = {
        "input_path": str(args.input_path),
        "output_path": str(args.output_path),
        **summary,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
