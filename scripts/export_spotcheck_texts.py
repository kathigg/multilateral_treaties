#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median


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
SOURCE_NOTE_START_RE = re.compile(r"^\s*(?:\d+\s+)?\[?Source:\s+", re.IGNORECASE)
REFERENCE_NOTE_START_RE = re.compile(r"^\s*\d+\s+Reference\s+is\s+to\b", re.IGNORECASE)
ARCHIVAL_CITATION_RE = re.compile(
    r"(?:\bLibrary\b|\bRecords\b|\bOA/ID\b|\bNo classification marking\b|\bSent through\b)",
    re.IGNORECASE,
)
ORPHAN_SOURCE_NOTE_RE = re.compile(
    r"""^\s*(?:
        .*?\b(?:records|files),\s+Box\s+\d+\b.*?\b(?:Secret|Confidential|Top\s+Secret)\b
        |.*?\b(?:Secret|Confidential|Top\s+Secret)\.\s+Prepared\s+by\b
        |.*?\bSent\s+by\s+air\s+pouch\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)
DOCUMENT_MARKER_RE = re.compile(r"^\s*\[Document\s+\d+[A-Za-z]?\]\s*$", re.IGNORECASE)
MODERN_DOCUMENT_MARKER_RE = re.compile(r"^\s*\d{1,4}\.\s*$")
DOCUMENT_TITLE_START_RE = re.compile(
    r"""^\s*(?:
        Memorandum
        |Telegram
        |Editorial\s+Note
        |Letter
        |Message
        |Paper
        |Report
        |Despatch
        |Dispatch
        |Summary
        |Minutes
        |Record
        |Conversation
        |Instruction
        |Circular\s+Telegram
        |National\s+Intelligence\s+Estimate
        |Special\s+National\s+Intelligence\s+Estimate
        |Intelligence\s+Memorandum
        |Statement
        |Agreement
        |Convention
        |Treaty
        |Excerpts?\s+From
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)
DOCUMENT_LIST_ENTRY_RE = re.compile(r"^\s*\[(\d+)\]\s+(.+)")
DOCUMENT_LIST_ENTRY_TEXT_RE = re.compile(
    r"\b(?:to|from)\s+the\b|\bMemorandum\b|\bConvention\b|\bAgreement\b|\bTreaty\b|\bTelegram\b|\bDespatch\b|\bDispatch\b|\bNote\b",
    re.IGNORECASE,
)
BRACKETED_INLINE_FOOTNOTE_RE = re.compile(r"(?<=[A-Za-z])\d{1,3}(?=\s*\])")
PUNCT_INLINE_FOOTNOTE_RE = re.compile(
    r'(?:(?<=[\]\)”";:])\d{1,3}|(?<=,)\d{1,2}|(?<!\d)(?<=\.)\d{1,3})(?=\s)'
)
LINE_END_INLINE_FOOTNOTE_RE = re.compile(r"(?<=[A-Za-z\]\)”\".])\d{1,3}(?=\s*$)")
FRUS_FOOTNOTE_START_RE = re.compile(
    r"""^\s*\d+\s+(?:
        Source:
        |File\s+translation\s+revised
        |The\s+pertinent\s+clauses\b
        |Not\s+printed\b
        |Neither\s+printed\b
        |None\s+printed\b
        |For\s+(?:text|the\s+text|the\s+fiscal|fiscal)\b
        |See\b
        |Supra\.?$
        |Ibid\.?\b
        |Copy\s+(?:handed|transmitted|sent)\b
        |Transmitted\s+by\b
        |Annual\s+report\b
        |John\s+W\.\s+Davis\b
        |In\s+view\s+of\b
        |Census\s+of\s+Manufactures\b
        |League\s+of\s+Nations\b
        |Plan\s+not\s+printed\b
        |Edwin\s+L\.\s+Neville\b
        |Department\s+of\s+State\b
        |Marginal\s+notation\b
        |Telegram\b
        |Memorandum\b
        |Reference\s+is\s+to\b
        |Document\s+\d+\.?$
        |According\s+to\b
        |A\s+handwritten\b
        |Printed\s+from\b
        |Drafted\s+by\b
        |Sent\s+by\b
        |Attached\b
        |No\s+minutes\b
        |Laingen[’']s\s+message\b
        |The\s+Iran\s+Working\s+Group\b
        |The\s+New\s+York\s+Hospital\b
        |Carter\s+was\b
        |Executive\s+Order\b
        |Public\s+Law\b
        |(?:Carter|Reagan|Nixon|Ford|Kennedy|Johnson|Eisenhower|Truman|Bush|Clinton)\s+Library\b
        |National\s+Archives\b
        |Central\s+Intelligence\s+Agency\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)
INDEX_PAGE_REF_RE = re.compile(r"\[(?:Pg|Pgs)\.?\s", re.IGNORECASE)
INDEX_DOC_REF_RE = re.compile(r"\bDoc\.?\s*\d+", re.IGNORECASE)
INDEX_SEE_RE = re.compile(r"\bSee(?:\s+also|\s+under)?\b|\bsupra\b|\binfra\b", re.IGNORECASE)
INDEX_REFERENCE_NOTE_RE = re.compile(
    r"^\s*References\s+are\s+to\s+document\s+numbers\s*$",
    re.IGNORECASE | re.MULTILINE,
)
INDEX_HEADING_RE = re.compile(r"^\s*Index\s*$", re.IGNORECASE)
SHORT_DOCUMENT_NOTE_RE = re.compile(r"^\s*\d+,\s+Document\s+\d+\.?\s*$", re.IGNORECASE)
PAGE_ARTIFACT_RE = re.compile(r"^\s*\d+/\d+:\s+\w+\s*$")
NUMBERED_FOOTNOTE_LINE_RE = re.compile(r"^\s*\d+\s+\S+")
FOOTNOTE_PARAGRAPH_START_RE = re.compile(r"^\s*\d+\s+[A-Z(]")
EMBEDDED_SINGLE_LINE_FOOTNOTE_RE = re.compile(
    r"^\s*\d+\s+(?:Not\s+found\s+and\s+not\s+further\s+identified\.?)\s*$",
    re.IGNORECASE,
)
ORIGINAL_FOOTNOTE_MARKER_RE = re.compile(r"\[Footnote\s+in\s+(?:the\s+)?original\.", re.IGNORECASE)
MODERN_RUNNING_HEADER_RE = re.compile(r"^\s*Foreign\s+Relations,\s+\d{4}", re.IGNORECASE)


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
    first_document_found: bool
    removed_before_first_document_lines: int
    removed_frus_footnote_blocks: int
    removed_frus_footnote_lines: int
    frus_footnote_blocks: list[str]
    removed_navigation_blocks: int
    removed_navigation_lines: int
    navigation_blocks: list[str]
    removed_table_blocks: int
    removed_table_lines: int
    table_blocks: list[str]
    removed_back_matter_blocks: int
    removed_back_matter_lines: int
    back_matter_blocks: list[str]
    removed_inline_footnote_markers: int


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
    # Document dirs contain document-level metadata.json + clean_text.txt. Page-level
    # artifact dirs have the same filenames under a pages/ subtree, so skip those.
    dirs: list[Path] = []
    for path in input_root.rglob("metadata.json"):
        relative_parts = path.relative_to(input_root).parts
        if "pages" in relative_parts:
            continue
        if (path.parent / "clean_text.txt").exists():
            dirs.append(path.parent)
    return sorted(dirs)


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
    if ORPHAN_SOURCE_NOTE_RE.match(stripped):
        return True
    # Some notes omit "Source:" but are clearly archival citations.
    if re.match(r"^\s*\d+\s+", stripped) and ARCHIVAL_CITATION_RE.search(stripped):
        return True
    return False


def looks_like_frus_footnote_start(line: str) -> bool:
    stripped = line.strip()
    return bool(FRUS_FOOTNOTE_START_RE.match(stripped) or SHORT_DOCUMENT_NOTE_RE.match(stripped))


def looks_like_document_title_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(DOCUMENT_TITLE_START_RE.match(stripped))


def is_modern_document_marker_at(lines: list[str], index: int) -> bool:
    if not MODERN_DOCUMENT_MARKER_RE.fullmatch(lines[index].strip()):
        return False

    # Standalone page numbers look identical to modern FRUS document numbers.
    # Treat them as document markers only when the next few nonblank lines form
    # a FRUS-style supplied heading.
    lookahead = 0
    for next_line in lines[index + 1 :]:
        next_stripped = next_line.strip()
        if not next_stripped:
            continue
        lookahead += 1
        if looks_like_document_title_line(next_stripped):
            return True
        if lookahead >= 6:
            return False
    return False


def block_contains_document_marker(block: list[str]) -> bool:
    if any(DOCUMENT_MARKER_RE.fullmatch(line.strip()) for line in block):
        return True
    return any(is_modern_document_marker_at(block, index) for index in range(len(block)))


def first_document_marker_index(block: list[str]) -> int | None:
    for index, line in enumerate(block):
        if DOCUMENT_MARKER_RE.fullmatch(line.strip()) or is_modern_document_marker_at(block, index):
            return index
    return None


def document_marker_indexes(block: list[str]) -> list[int]:
    return [
        index
        for index, line in enumerate(block)
        if DOCUMENT_MARKER_RE.fullmatch(line.strip()) or is_modern_document_marker_at(block, index)
    ]


def looks_like_document_list_entry(line: str) -> bool:
    stripped = line.strip()
    if DOCUMENT_MARKER_RE.fullmatch(stripped):
        return False
    match = DOCUMENT_LIST_ENTRY_RE.match(stripped)
    if not match:
        return False
    return bool(DOCUMENT_LIST_ENTRY_TEXT_RE.search(match.group(2)))


def looks_like_navigation_heading_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False
    if DOCUMENT_MARKER_RE.fullmatch(stripped) or looks_like_document_list_entry(stripped):
        return False
    if stripped.isupper() and len(stripped.split()) <= 4:
        return False
    return not bool(re.search(r"[.!?][\"')\]]?$", stripped))


def looks_like_embedded_navigation_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^\d+/\d+:\s+\w+", stripped):
        return True
    if re.search(r"\(Documents?\s+\d+", stripped, re.IGNORECASE):
        return True
    return looks_like_back_matter_start_line(stripped)


def numeric_groups(line: str) -> list[str]:
    return re.findall(r"\d[\d,]*", line)


def looks_like_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if "|" in stripped:
        return True
    if re.search(r"\.{2,}\s*(?:\[?Pg\.?\]?|\d+)", stripped, re.IGNORECASE):
        return True
    if re.search(r"\b(?:amount|total|increase|decrease|value|tonnage|exports?|imports?)\b", stripped, re.IGNORECASE):
        if len(numeric_groups(stripped)) >= 3:
            return True
    if len(numeric_groups(stripped)) >= 4 and len(stripped) <= 180:
        return True
    alpha = sum(char.isalpha() for char in stripped)
    punctuation = sum(char in "._-—=:;[](){}~/\\|" for char in stripped)
    if alpha < 12 and punctuation >= 4 and len(numeric_groups(stripped)) >= 1:
        return True
    return False


def split_nonblank_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.rstrip())
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def block_preview(block: list[str], limit: int = 500) -> str:
    preview = "\n".join(block).strip()
    if len(preview) <= limit:
        return preview
    return preview[: limit - 3] + "..."


def looks_like_table_block(block: list[str]) -> bool:
    lines = [line for line in block if line.strip()]
    if len(lines) < 3:
        return False
    table_line_count = sum(1 for line in lines if looks_like_table_line(line))
    if table_line_count >= 3:
        return True
    if len(lines) >= 5 and table_line_count / len(lines) >= 0.5:
        return True
    return False


def looks_like_index_heading_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return False
    if stripped.upper() in {"SIR:", "SUBJECT:", "PARTICIPANTS:"}:
        return False
    return stripped.endswith(":") and bool(re.match(r"^[A-Z][A-Za-z .,'()–-]+:$", stripped))


def looks_like_back_matter_block(block: list[str]) -> bool:
    if block_contains_document_marker(block):
        return False

    lines = [line.strip() for line in block if line.strip()]
    if not lines:
        return False

    text = "\n".join(lines)
    if any(INDEX_REFERENCE_NOTE_RE.match(line) for line in lines):
        return True
    if INDEX_SEE_RE.search(text):
        return True
    if INDEX_PAGE_REF_RE.search(text):
        return True
    if len(INDEX_DOC_REF_RE.findall(text)) >= 2:
        return True

    colon_headings = sum(1 for line in lines if looks_like_index_heading_line(line))
    if colon_headings >= 2:
        return True

    # Index blocks often consist of short entry fragments rather than full prose.
    sentence_like = sum(1 for line in lines if re.search(r"[.!?][\"')\]]?$", line))
    if len(lines) >= 4 and colon_headings >= 1 and sentence_like <= 1:
        return True

    return False


def looks_like_back_matter_start_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^[A-Z][A-Za-z .'-]{2,60},\s+[a-z]", stripped):
        return True
    return bool(
        INDEX_REFERENCE_NOTE_RE.match(stripped)
        or looks_like_index_heading_line(stripped)
        or INDEX_SEE_RE.search(stripped)
        or INDEX_PAGE_REF_RE.search(stripped)
    )


def has_sustained_back_matter_evidence(
    tail: list[list[str]],
    *,
    require_modern_index_signal: bool = False,
) -> bool:
    removed_lines = sum(len(block) for block in tail)
    if removed_lines < 25:
        return False

    evidence_blocks = sum(1 for block in tail if looks_like_back_matter_block(block))
    evidence_text = "\n".join("\n".join(block) for block in tail)
    has_modern_index_signal = bool(
        INDEX_REFERENCE_NOTE_RE.search(evidence_text)
        or INDEX_HEADING_RE.search(evidence_text)
    )
    if require_modern_index_signal and not has_modern_index_signal:
        return False

    evidence_hits = (
        len(INDEX_SEE_RE.findall(evidence_text))
        + len(INDEX_PAGE_REF_RE.findall(evidence_text))
        + len(INDEX_DOC_REF_RE.findall(evidence_text))
        + len(INDEX_REFERENCE_NOTE_RE.findall(evidence_text))
    )

    return evidence_blocks >= 3 or evidence_blocks / max(len(tail), 1) >= 0.25 or evidence_hits >= 8


def trim_modern_trailing_index(
    blocks: list[list[str]],
    last_document_index: int,
) -> tuple[list[list[str]], int, int, list[str]]:
    # Modern FRUS volumes use plain numeric document markers, so avoid broad
    # index-like scanning inside the final document. Only trim once a strong
    # end-index marker appears after the last document marker.
    for index in range(last_document_index, len(blocks)):
        first_line_index = 0
        if index == last_document_index:
            marker_index = first_document_marker_index(blocks[index])
            if marker_index is not None:
                first_line_index = marker_index + 1

        for line_index, line in enumerate(blocks[index][first_line_index:], start=first_line_index):
            stripped = line.strip()
            if not (INDEX_REFERENCE_NOTE_RE.match(stripped) or INDEX_HEADING_RE.match(stripped)):
                continue

            tail = [blocks[index][line_index:]] + blocks[index + 1 :]
            if not has_sustained_back_matter_evidence(tail, require_modern_index_signal=True):
                continue

            kept_blocks = blocks[:index]
            if line_index > 0:
                kept_blocks.append(blocks[index][:line_index])
            removed_lines = sum(len(block) for block in tail)
            return kept_blocks, len(tail), removed_lines, [block_preview(block) for block in tail]

    return blocks, 0, 0, []


def trim_trailing_back_matter(blocks: list[list[str]]) -> tuple[list[list[str]], int, int, list[str]]:
    has_bracketed_document_markers = any(
        DOCUMENT_MARKER_RE.fullmatch(line.strip()) for block in blocks for line in block
    )
    has_document_markers = has_bracketed_document_markers or any(block_contains_document_marker(block) for block in blocks)
    if not has_document_markers:
        return blocks, 0, 0, []

    last_document_index: int | None = None
    for index, block in enumerate(blocks):
        if block_contains_document_marker(block):
            last_document_index = index

    if last_document_index is None:
        return blocks, 0, 0, []

    if not has_bracketed_document_markers:
        return trim_modern_trailing_index(blocks, last_document_index)

    for index in range(last_document_index, len(blocks)):
        if not looks_like_back_matter_block(blocks[index]):
            first_line_index = 0
            if index == last_document_index:
                marker_index = first_document_marker_index(blocks[index])
                if marker_index is not None:
                    first_line_index = marker_index + 1

            for line_index, line in enumerate(blocks[index][first_line_index:], start=first_line_index):
                if not looks_like_back_matter_start_line(line):
                    continue

                tail = [blocks[index][line_index:]] + blocks[index + 1 :]
                if not has_sustained_back_matter_evidence(tail):
                    continue

                kept_blocks = blocks[:index]
                if line_index > 0:
                    kept_blocks.append(blocks[index][:line_index])
                removed_lines = sum(len(block) for block in tail)
                return kept_blocks, len(tail), removed_lines, [block_preview(block) for block in tail]
            continue

        tail = blocks[index:]
        if not has_sustained_back_matter_evidence(tail):
            continue

        removed_lines = sum(len(block) for block in tail)
        return blocks[:index], len(tail), removed_lines, [block_preview(block) for block in tail]

    return blocks, 0, 0, []


def split_embedded_document_blocks(blocks: list[list[str]]) -> tuple[list[list[str]], int, list[str]]:
    normalized: list[list[str]] = []
    removed_navigation_lines = 0
    navigation_blocks: list[str] = []

    for block in blocks:
        marker_indexes = document_marker_indexes(block)
        if len(marker_indexes) <= 1:
            normalized.append(block)
            continue

        segment_start = marker_indexes[0]
        if segment_start > 0:
            normalized.append(block[:segment_start])

        for next_marker_index in marker_indexes[1:]:
            segment = block[segment_start:next_marker_index]
            cut_index: int | None = None
            for line_index, line in enumerate(segment[1:], start=1):
                if looks_like_embedded_navigation_start(line):
                    cut_index = line_index
                    break

            if cut_index is None:
                normalized.append(segment)
            else:
                kept = segment[:cut_index]
                removed = segment[cut_index:]
                if kept:
                    normalized.append(kept)
                if removed:
                    navigation_blocks.append(block_preview(removed))
                    removed_navigation_lines += len(removed)

            segment_start = next_marker_index

        normalized.append(block[segment_start:])

    return normalized, removed_navigation_lines, navigation_blocks


def looks_like_pre_document_navigation_block(
    block: list[str],
    *,
    require_strong_signal: bool = False,
) -> bool:
    if block_contains_document_marker(block):
        return False

    lines = [line.strip() for line in block if line.strip()]
    if not lines or len(lines) > 12:
        return False

    text = "\n".join(lines)
    if re.search(r"\bForeign\s+Relations,\s+\d{4}.*\bp{1,2}\.", text, re.IGNORECASE):
        return True
    if any(looks_like_document_list_entry(line) for line in lines):
        return True
    if re.search(r"\(Documents?\s+\d+", text, re.IGNORECASE):
        return True
    if require_strong_signal:
        return False

    sentence_like = sum(1 for line in lines if re.search(r"[.!?][\"')\]]?$", line))
    heading_like = sum(1 for line in lines if looks_like_navigation_heading_line(line))
    return len(lines) >= 2 and sentence_like == 0 and heading_like / len(lines) >= 0.75


def looks_like_strong_pre_document_navigation_line(line: str) -> bool:
    stripped = line.strip()
    return bool(
        re.search(r"\bForeign\s+Relations,\s+\d{4}.*\bp{1,2}\.", stripped, re.IGNORECASE)
        or looks_like_document_list_entry(stripped)
        or re.search(r"\(Documents?\s+\d+", stripped, re.IGNORECASE)
    )


def drop_pre_document_navigation_blocks(blocks: list[list[str]]) -> tuple[list[list[str]], int, list[str]]:
    kept: list[list[str]] = []
    removed_lines = 0
    removed_blocks: list[str] = []

    for index, block in enumerate(blocks):
        next_block = blocks[index + 1] if index + 1 < len(blocks) else None
        if (
            next_block is not None
            and block_contains_document_marker(next_block)
            and looks_like_pre_document_navigation_block(block)
        ):
            removed_lines += len(block)
            removed_blocks.append(block_preview(block))
            continue
        if next_block is not None and block_contains_document_marker(next_block):
            strong_line_index = next(
                (
                    line_index
                    for line_index, line in enumerate(block)
                    if looks_like_strong_pre_document_navigation_line(line)
                ),
                None,
            )
            if strong_line_index is not None:
                start_index = strong_line_index
                while start_index > 0 and looks_like_navigation_heading_line(block[start_index - 1]):
                    start_index -= 1

                tail = block[start_index:]
                if not looks_like_pre_document_navigation_block(tail, require_strong_signal=True):
                    kept.append(block)
                    continue

                kept_head = block[:start_index]
                if kept_head:
                    kept.append(kept_head)
                removed_lines += len(tail)
                removed_blocks.append(block_preview(tail))
                continue
            else:
                kept.append(block)
            continue
        kept.append(block)

    return kept, removed_lines, removed_blocks


def strip_footnote_tail_from_block(block: list[str]) -> tuple[list[str], list[str]]:
    for index, line in enumerate(block):
        if looks_like_frus_footnote_start(line):
            return block[:index], block[index:]
    return block, []


def strip_navigation_tail_from_block(block: list[str]) -> tuple[list[str], list[str]]:
    for index, line in enumerate(block):
        if index == 0 or not looks_like_document_list_entry(line):
            continue

        tail = block[index:]
        nav_count = sum(1 for tail_line in tail if looks_like_document_list_entry(tail_line))
        if nav_count < 2:
            tail_has_prose = any(looks_like_prose(tail_line) for tail_line in tail[1:])
            if len(tail) > 8 or tail_has_prose:
                continue

        start = index
        while start > 0 and looks_like_navigation_heading_line(block[start - 1]):
            start -= 1
        return block[:start], block[start:]

    return block, []


def remove_embedded_footnote_lines(block: list[str]) -> tuple[list[str], list[str], int]:
    cleaned: list[str] = []
    removed_blocks: list[str] = []
    removed_line_count = 0
    index = 0

    while index < len(block):
        line = block[index]
        stripped = line.strip()

        original_footnote_match = ORIGINAL_FOOTNOTE_MARKER_RE.search(line)
        if original_footnote_match:
            marker_index = original_footnote_match.start()
            prefix = line[:marker_index].rstrip()
            removed = [line[marker_index:]]
            candidate_index = index
            found_close = "]" in line[marker_index:]

            while not found_close and candidate_index + 1 < len(block) and len(removed) < 8:
                candidate_index += 1
                removed.append(block[candidate_index])
                found_close = "]" in block[candidate_index]

            if prefix and not FOOTNOTE_PARAGRAPH_START_RE.match(prefix):
                cleaned.append(prefix)
            removed_blocks.append(block_preview(removed))
            removed_line_count += candidate_index - index + 1
            index = candidate_index + 1
            continue

        if EMBEDDED_SINGLE_LINE_FOOTNOTE_RE.match(stripped):
            removed_blocks.append(block_preview([line]))
            removed_line_count += 1
            index += 1
            continue

        if FOOTNOTE_PARAGRAPH_START_RE.match(stripped):
            removed = [line]
            index += 1
            while index < len(block) and len(removed) < 12:
                next_stripped = block[index].strip()
                if not next_stripped:
                    break
                if DOCUMENT_MARKER_RE.fullmatch(next_stripped) or is_modern_document_marker_at(block, index):
                    break
                if FOOTNOTE_PARAGRAPH_START_RE.match(next_stripped):
                    break
                if MODERN_RUNNING_HEADER_RE.match(next_stripped):
                    break

                removed.append(block[index])
                index += 1

            removed_blocks.append(block_preview(removed))
            removed_line_count += len(removed)
            continue

        if NUMBERED_FOOTNOTE_LINE_RE.match(stripped):
            candidate = [line]
            candidate_index = index
            found_original_marker = bool(ORIGINAL_FOOTNOTE_MARKER_RE.search(line))

            while not found_original_marker and candidate_index + 1 < len(block) and len(candidate) < 4:
                next_line = block[candidate_index + 1]
                next_stripped = next_line.strip()
                if not next_stripped:
                    break
                if DOCUMENT_MARKER_RE.fullmatch(next_stripped) or re.match(r"^\d+[.)]\s+", next_stripped):
                    break

                candidate.append(next_line)
                candidate_index += 1
                found_original_marker = bool(ORIGINAL_FOOTNOTE_MARKER_RE.search(next_line))

            if found_original_marker:
                removed_blocks.append(block_preview(candidate))
                removed_line_count += len(candidate)
                index = candidate_index + 1
                continue

        cleaned.append(line)
        index += 1

    return cleaned, removed_blocks, removed_line_count


def strip_inline_footnote_markers(line: str) -> tuple[str, int]:
    total = 0
    line, count = BRACKETED_INLINE_FOOTNOTE_RE.subn("", line)
    total += count
    line, count = PUNCT_INLINE_FOOTNOTE_RE.subn("", line)
    total += count
    line, count = LINE_END_INLINE_FOOTNOTE_RE.subn("", line)
    total += count
    return line, total


def expand_tab_paragraph_breaks(line: str) -> list[str]:
    if "\t" not in line:
        return [line]

    # Tabs often encode visual spacing from PDF extraction. Promote non-label
    # tab breaks to paragraph breaks while keeping numbered/bulleted labels inline.
    parts = [part.strip() for part in re.split(r"\t+", line) if part.strip()]
    if len(parts) <= 1:
        return [line.replace("\t", " ").rstrip()]

    label = parts[0]
    if re.fullmatch(r"(?:[-—•*]|\d{1,4}[.)]|[IVXLCM]{1,8}\.)", label):
        return [" ".join(parts)]

    expanded: list[str] = [parts[0]]
    for part in parts[1:]:
        expanded.append("")
        expanded.append(part)
    return expanded


def looks_like_paragraph_break(line: str, next_line: str, wrap_width: int) -> bool:
    stripped = line.rstrip()
    next_stripped = next_line.strip()
    if not stripped or not next_stripped:
        return False
    if stripped.endswith(("-", "\xad")):
        return False
    if not re.search(r'[.!?]["\')\]]?$', stripped):
        return False
    if not re.match(r'^[A-Z("“\'\[]', next_stripped):
        return False
    return len(stripped) <= max(40, wrap_width - 12)


def render_block_with_paragraph_spacing(block: list[str]) -> str:
    lines = [line.rstrip() for line in block]
    nonempty_lines = [line for line in lines if line.strip()]
    if not nonempty_lines:
        return ""

    wrap_width = int(median(len(line) for line in nonempty_lines))
    rendered: list[str] = []

    for index, line in enumerate(lines):
        if not line.strip():
            if rendered and rendered[-1] != "":
                rendered.append("")
            continue

        rendered.append(line)
        if index == len(lines) - 1:
            continue

        next_line = lines[index + 1]
        if not next_line.strip():
            if rendered[-1] != "":
                rendered.append("")
            continue

        if looks_like_paragraph_break(line, next_line, wrap_width):
            rendered.append("")

    return "\n".join(rendered).strip()


def trim_to_first_document(lines: list[str]) -> tuple[list[str], bool, int]:
    for index, line in enumerate(lines):
        if DOCUMENT_MARKER_RE.fullmatch(line.strip()) or is_modern_document_marker_at(lines, index):
            return lines[index:], True, index
    return lines, False, 0


def apply_frus_structural_cleaning(
    text: str,
) -> tuple[
    str,
    bool,
    int,
    int,
    int,
    list[str],
    int,
    int,
    list[str],
    int,
    int,
    list[str],
    int,
    int,
    int,
    list[str],
    int,
]:
    lines, first_document_found, removed_before_first_document = trim_to_first_document(text.splitlines())
    blocks = split_nonblank_blocks(lines)

    kept_blocks: list[list[str]] = []
    footnote_blocks: list[str] = []
    navigation_blocks: list[str] = []
    table_blocks: list[str] = []
    back_matter_blocks: list[str] = []
    removed_footnote_lines = 0
    removed_navigation_lines = 0
    removed_table_lines = 0
    removed_back_matter_lines = 0
    removed_inline_footnote_markers = 0

    blocks, embedded_navigation_lines, embedded_navigation_blocks = split_embedded_document_blocks(blocks)
    removed_navigation_lines += embedded_navigation_lines
    navigation_blocks.extend(embedded_navigation_blocks)

    blocks, pre_document_navigation_lines, pre_document_navigation_blocks = drop_pre_document_navigation_blocks(blocks)
    removed_navigation_lines += pre_document_navigation_lines
    navigation_blocks.extend(pre_document_navigation_blocks)

    for block in blocks:
        marker_index = first_document_marker_index(block)
        if marker_index is not None and marker_index > 0:
            leading = block[:marker_index]
            navigation_blocks.append(block_preview(leading))
            removed_navigation_lines += len(leading)
            block = block[marker_index:]

        first = block[0].strip()
        contains_document_marker = block_contains_document_marker(block)
        contains_navigation_entry = any(looks_like_document_list_entry(line) for line in block)

        if looks_like_frus_footnote_start(first):
            footnote_blocks.append(block_preview(block))
            removed_footnote_lines += len(block)
            continue

        if contains_navigation_entry and not contains_document_marker:
            navigation_blocks.append(block_preview(block))
            removed_navigation_lines += len(block)
            continue

        if not contains_document_marker and looks_like_table_block(block):
            table_blocks.append(block_preview(block))
            removed_table_lines += len(block)
            continue

        cleaned_block, embedded_footnote_blocks, embedded_footnote_line_count = remove_embedded_footnote_lines(block)
        if embedded_footnote_blocks:
            footnote_blocks.extend(embedded_footnote_blocks)
            removed_footnote_lines += embedded_footnote_line_count
        if not cleaned_block:
            continue

        cleaned_block, footnote_tail = strip_footnote_tail_from_block(cleaned_block)
        if footnote_tail:
            footnote_blocks.append(block_preview(footnote_tail))
            removed_footnote_lines += len(footnote_tail)
        cleaned_block, navigation_tail = strip_navigation_tail_from_block(cleaned_block)
        if navigation_tail:
            navigation_blocks.append(block_preview(navigation_tail))
            removed_navigation_lines += len(navigation_tail)
        if cleaned_block:
            marker_cleaned_block: list[str] = []
            for line in cleaned_block:
                if PAGE_ARTIFACT_RE.match(line.strip()):
                    navigation_blocks.append(block_preview([line]))
                    removed_navigation_lines += 1
                    continue
                cleaned_line, marker_count = strip_inline_footnote_markers(line)
                removed_inline_footnote_markers += marker_count
                marker_cleaned_block.extend(expand_tab_paragraph_breaks(cleaned_line))
            kept_blocks.append(marker_cleaned_block)

    (
        kept_blocks,
        removed_back_matter_blocks,
        removed_back_matter_lines,
        back_matter_blocks,
    ) = trim_trailing_back_matter(kept_blocks)

    final = "\n\n".join(
        rendered
        for rendered in (render_block_with_paragraph_spacing(block) for block in kept_blocks)
        if rendered
    ).strip()
    if final:
        final += "\n"

    return (
        final,
        first_document_found,
        removed_before_first_document,
        len(footnote_blocks),
        removed_footnote_lines,
        footnote_blocks,
        len(navigation_blocks),
        removed_navigation_lines,
        navigation_blocks,
        len(table_blocks),
        removed_table_lines,
        table_blocks,
        removed_back_matter_blocks,
        removed_back_matter_lines,
        back_matter_blocks,
        removed_inline_footnote_markers,
    )


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

    for index, line in enumerate(lines):
        stripped = line.strip()
        modern_document_marker = is_modern_document_marker_at(lines, index)

        # Strip editorial/source-note footnotes anywhere (save them in metadata).
        if in_source_note:
            if modern_document_marker:
                if current_source_note:
                    source_note_blocks.append("\n".join(current_source_note).strip())
                    current_source_note = []
                in_source_note = False
            elif not stripped:
                # End of the note block.
                if current_source_note:
                    source_note_blocks.append("\n".join(current_source_note).strip())
                    current_source_note = []
                in_source_note = False
                removed_source_notes += 1
                continue
            else:
                current_source_note.append(stripped)
                removed_source_notes += 1
                continue

        if looks_like_source_note_start(line) or looks_like_frus_footnote_start(line):
            in_source_note = True
            current_source_note = [stripped]
            removed_source_notes += 1
            continue

        if modern_document_marker:
            in_toc = False
            in_unwanted_section = False
            unwanted_section_name = None
            in_imprint = False

        # Drop links/emails anywhere.
        if looks_like_link_or_email(line):
            removed_links += 1
            continue

        # Drop page-number-only lines anywhere.
        if looks_like_page_number_line(line) and not modern_document_marker:
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

    if current_source_note:
        source_note_blocks.append("\n".join(current_source_note).strip())
        current_source_note = []

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

    (
        final,
        first_document_found,
        removed_before_first_document,
        removed_frus_footnote_blocks,
        removed_frus_footnote_lines,
        frus_footnote_blocks,
        removed_navigation_blocks,
        removed_navigation_lines,
        navigation_blocks,
        removed_table_blocks,
        removed_table_lines,
        table_blocks,
        removed_back_matter_blocks,
        removed_back_matter_lines,
        back_matter_blocks,
        removed_inline_footnote_markers,
    ) = apply_frus_structural_cleaning(final)

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
        first_document_found,
        removed_before_first_document,
        removed_frus_footnote_blocks,
        removed_frus_footnote_lines,
        frus_footnote_blocks,
        removed_navigation_blocks,
        removed_navigation_lines,
        navigation_blocks,
        removed_table_blocks,
        removed_table_lines,
        table_blocks,
        removed_back_matter_blocks,
        removed_back_matter_lines,
        back_matter_blocks,
        removed_inline_footnote_markers,
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
                    f"first_document_found={trimmed.first_document_found}",
                    f"removed_before_first_document_lines={trimmed.removed_before_first_document_lines}",
                    f"removed_frus_footnote_blocks={trimmed.removed_frus_footnote_blocks}",
                    f"removed_frus_footnote_lines={trimmed.removed_frus_footnote_lines}",
                    f"removed_navigation_blocks={trimmed.removed_navigation_blocks}",
                    f"removed_navigation_lines={trimmed.removed_navigation_lines}",
                    f"removed_table_blocks={trimmed.removed_table_blocks}",
                    f"removed_table_lines={trimmed.removed_table_lines}",
                    f"removed_back_matter_blocks={trimmed.removed_back_matter_blocks}",
                    f"removed_back_matter_lines={trimmed.removed_back_matter_lines}",
                    f"removed_inline_footnote_markers={trimmed.removed_inline_footnote_markers}",
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
                    "first_document_found": trimmed.first_document_found,
                    "removed_before_first_document_lines": trimmed.removed_before_first_document_lines,
                    "removed_frus_footnote_blocks": trimmed.removed_frus_footnote_blocks,
                    "removed_frus_footnote_lines": trimmed.removed_frus_footnote_lines,
                    "frus_footnote_blocks": trimmed.frus_footnote_blocks,
                    "removed_navigation_blocks": trimmed.removed_navigation_blocks,
                    "removed_navigation_lines": trimmed.removed_navigation_lines,
                    "navigation_blocks": trimmed.navigation_blocks,
                    "removed_table_blocks": trimmed.removed_table_blocks,
                    "removed_table_lines": trimmed.removed_table_lines,
                    "table_blocks": trimmed.table_blocks,
                    "removed_back_matter_blocks": trimmed.removed_back_matter_blocks,
                    "removed_back_matter_lines": trimmed.removed_back_matter_lines,
                    "back_matter_blocks": trimmed.back_matter_blocks,
                    "removed_inline_footnote_markers": trimmed.removed_inline_footnote_markers,
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
