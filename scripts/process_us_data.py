#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import fitz
except ModuleNotFoundError as exc:
    raise SystemExit(
        "PyMuPDF is required for PDF processing. Install it with `pip install -r requirements-ocr.txt`."
    ) from exc

try:
    import cv2
except ModuleNotFoundError as exc:
    raise SystemExit(
        "OpenCV is required for OCR preprocessing. Install it with `pip install -r requirements-ocr.txt`."
    ) from exc

from scripts.clean_raw_ocr_text import clean_text_content
from scripts.ocr_page import (
    build_prose_text,
    load_text,
    normalize_wrapped_lines,
    parse_tsv,
    preprocess_image,
    read_image,
    run_tesseract,
)


@dataclass
class PageResult:
    page_number: int
    source_method: str
    raw_text: str
    clean_text: str
    prose_text: str
    raw_char_count: int
    clean_char_count: int
    prose_char_count: int
    ocr_stats: dict[str, float | int | None] | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Process every PDF under us_data into cleaned text. The pipeline prefers embedded PDF text "
            "and falls back to OCR when extraction is sparse."
        )
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path("us_data"),
        help="Root directory containing source PDFs.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/us_data_cleaning"),
        help="Directory for cleaned outputs and metadata.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(8, os.cpu_count() or 4)),
        help="Maximum number of page workers to run per document.",
    )
    parser.add_argument(
        "--method",
        choices=("auto", "extract", "ocr"),
        default="auto",
        help="Page processing mode. 'auto' prefers embedded text and falls back to OCR.",
    )
    parser.add_argument(
        "--min-extracted-chars",
        type=int,
        default=80,
        help="Minimum non-whitespace character count required to trust embedded PDF text in auto mode.",
    )
    parser.add_argument(
        "--render-dpi",
        type=int,
        default=300,
        help="Render DPI for OCR fallback pages.",
    )
    parser.add_argument("--lang", default="eng", help="Tesseract language for OCR pages.")
    parser.add_argument("--psm", type=int, default=4, help="Tesseract page segmentation mode.")
    parser.add_argument("--oem", type=int, default=1, help="Tesseract OCR engine mode.")
    parser.add_argument(
        "--upscale",
        type=float,
        default=2.0,
        help="Image scale factor applied before OCR.",
    )
    parser.add_argument(
        "--keep-page-artifacts",
        action="store_true",
        help="Store page-level text, OCR metadata, and debug files under each document output directory.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reprocess documents even if document-level outputs already exist.",
    )
    parser.add_argument(
        "--match",
        help="Only process PDFs whose relative path contains this case-insensitive substring.",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        help="Maximum number of PDFs to process after filtering.",
    )
    parser.add_argument(
        "--max-pages-per-document",
        type=int,
        help="Limit processing to the first N pages of each document.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop the run immediately if any document or page fails.",
    )
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def ensure_trailing_newline(text: str) -> str:
    if not text:
        return ""
    return text if text.endswith("\n") else text + "\n"


def join_page_texts(texts: Iterable[str]) -> str:
    chunks = [text.rstrip() for text in texts if text.strip()]
    if not chunks:
        return ""
    return "\n\n".join(chunks) + "\n"


def document_complete(output_dir: Path) -> bool:
    required = ("raw_text.txt", "clean_text.txt", "prose_text.txt", "metadata.json")
    return all((output_dir / filename).exists() for filename in required)


def discover_pdfs(input_root: Path, match: str | None) -> list[Path]:
    pdf_paths = sorted(path for path in input_root.rglob("*.pdf") if path.is_file())
    if not match:
        return pdf_paths
    needle = match.lower()
    return [path for path in pdf_paths if needle in str(path.relative_to(input_root)).lower()]


def document_output_dir(input_root: Path, output_root: Path, pdf_path: Path) -> Path:
    relative = pdf_path.relative_to(input_root)
    return output_root / relative.with_suffix("")


def extracted_text_is_usable(text: str, min_chars: int) -> bool:
    condensed = re.sub(r"\s+", "", text or "")
    if len(condensed) < min_chars:
        return False

    alpha_count = sum(char.isalpha() for char in text)
    if alpha_count < 20:
        return False

    word_count = len(re.findall(r"[A-Za-z]{2,}", text))
    return word_count >= 10


def extract_embedded_text(pdf_path: Path, page_index: int) -> str:
    with fitz.open(pdf_path) as document:
        return document.load_page(page_index).get_text("text")


def render_page_to_png(pdf_path: Path, page_index: int, output_path: Path, dpi: int) -> None:
    with fitz.open(pdf_path) as document:
        page = document.load_page(page_index)
        scale = dpi / 72
        matrix = fitz.Matrix(scale, scale)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csGRAY)
        pixmap.save(output_path)


def write_page_artifacts(
    page_output_dir: Path,
    *,
    raw_text: str,
    clean_text: str,
    prose_text: str,
    metadata: dict[str, object],
    rendered_path: Path | None = None,
    preprocessed_path: Path | None = None,
    ocr_txt_path: Path | None = None,
    ocr_tsv_path: Path | None = None,
) -> None:
    page_output_dir.mkdir(parents=True, exist_ok=True)
    write_text(page_output_dir / "raw_text.txt", raw_text)
    write_text(page_output_dir / "clean_text.txt", clean_text)
    write_text(page_output_dir / "prose_text.txt", prose_text)
    write_json(page_output_dir / "metadata.json", metadata)

    if rendered_path and rendered_path.exists():
        shutil.copy2(rendered_path, page_output_dir / "rendered.png")
    if preprocessed_path and preprocessed_path.exists():
        shutil.copy2(preprocessed_path, page_output_dir / "preprocessed.png")
    if ocr_txt_path and ocr_txt_path.exists():
        shutil.copy2(ocr_txt_path, page_output_dir / "ocr.txt")
    if ocr_tsv_path and ocr_tsv_path.exists():
        shutil.copy2(ocr_tsv_path, page_output_dir / "ocr.tsv")


def page_output_path(base_dir: Path | None, page_number: int) -> Path | None:
    if base_dir is None:
        return None
    return base_dir / f"page_{page_number:04d}"


def process_page(
    pdf_path: Path,
    page_number: int,
    args: argparse.Namespace,
    page_output_dir: Path | None,
) -> PageResult:
    page_index = page_number - 1
    extracted_text = extract_embedded_text(pdf_path, page_index)

    use_extracted_text = False
    if args.method == "extract":
        use_extracted_text = True
    elif args.method == "auto" and extracted_text_is_usable(extracted_text, args.min_extracted_chars):
        use_extracted_text = True

    if use_extracted_text:
        raw_text = ensure_trailing_newline(extracted_text.rstrip())
        clean_text = normalize_wrapped_lines(raw_text) if raw_text.strip() else ""
        prose_text = build_prose_text(raw_text) if raw_text.strip() else ""
        metadata = {
            "page_number": page_number,
            "source_method": "embedded_text",
            "raw_char_count": len(raw_text),
            "clean_char_count": len(clean_text),
            "prose_char_count": len(prose_text),
        }

        if page_output_dir is not None:
            write_page_artifacts(
                page_output_dir,
                raw_text=raw_text,
                clean_text=clean_text,
                prose_text=prose_text,
                metadata=metadata,
            )

        return PageResult(
            page_number=page_number,
            source_method="embedded_text",
            raw_text=raw_text,
            clean_text=clean_text,
            prose_text=prose_text,
            raw_char_count=len(raw_text),
            clean_char_count=len(clean_text),
            prose_char_count=len(prose_text),
            ocr_stats=None,
        )

    with tempfile.TemporaryDirectory(prefix=f"ocr_page_{page_number:04d}_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        rendered_path = temp_dir / "rendered.png"
        render_page_to_png(pdf_path, page_index, rendered_path, args.render_dpi)

        image = read_image(rendered_path)
        processed = preprocess_image(image, upscale=args.upscale)

        preprocessed_path = temp_dir / "preprocessed.png"
        if not cv2.imwrite(str(preprocessed_path), processed):
            raise RuntimeError(f"Failed to write preprocessed image for page {page_number}")

        output_base = temp_dir / "ocr"
        run_tesseract(preprocessed_path, output_base, args.lang, args.psm, args.oem)

        raw_text = ensure_trailing_newline(load_text(output_base.with_suffix(".txt")).rstrip())
        clean_text = normalize_wrapped_lines(raw_text) if raw_text.strip() else ""
        prose_text = build_prose_text(raw_text) if raw_text.strip() else ""
        stats = parse_tsv(output_base.with_suffix(".tsv"))
        ocr_stats = {
            "mean_confidence": stats.mean_confidence,
            "low_confidence_ratio": stats.low_confidence_ratio,
            "word_count": stats.word_count,
            "low_confidence_word_count": stats.low_confidence_word_count,
        }
        metadata = {
            "page_number": page_number,
            "source_method": "ocr",
            "lang": args.lang,
            "psm": args.psm,
            "oem": args.oem,
            "upscale": args.upscale,
            "render_dpi": args.render_dpi,
            "raw_char_count": len(raw_text),
            "clean_char_count": len(clean_text),
            "prose_char_count": len(prose_text),
            "ocr_stats": ocr_stats,
        }

        if page_output_dir is not None:
            write_page_artifacts(
                page_output_dir,
                raw_text=raw_text,
                clean_text=clean_text,
                prose_text=prose_text,
                metadata=metadata,
                rendered_path=rendered_path,
                preprocessed_path=preprocessed_path,
                ocr_txt_path=output_base.with_suffix(".txt"),
                ocr_tsv_path=output_base.with_suffix(".tsv"),
            )

    return PageResult(
        page_number=page_number,
        source_method="ocr",
        raw_text=raw_text,
        clean_text=clean_text,
        prose_text=prose_text,
        raw_char_count=len(raw_text),
        clean_char_count=len(clean_text),
        prose_char_count=len(prose_text),
        ocr_stats=ocr_stats,
    )


def process_document(
    pdf_path: Path,
    input_root: Path,
    output_root: Path,
    args: argparse.Namespace,
) -> dict[str, object]:
    output_dir = document_output_dir(input_root, output_root, pdf_path)
    relative_path = str(pdf_path.relative_to(input_root))

    if not args.overwrite and document_complete(output_dir):
        return {
            "relative_path": relative_path,
            "status": "skipped",
            "output_dir": str(output_dir),
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.time()

    with fitz.open(pdf_path) as document:
        discovered_pages = len(document)

    target_pages = discovered_pages
    if args.max_pages_per_document is not None:
        target_pages = min(target_pages, args.max_pages_per_document)

    page_results: list[PageResult] = []
    failed_pages: list[dict[str, object]] = []
    pages_dir = output_dir / "pages" if args.keep_page_artifacts else None

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_page = {
            executor.submit(
                process_page,
                pdf_path,
                page_number,
                args,
                page_output_path(pages_dir, page_number),
            ): page_number
            for page_number in range(1, target_pages + 1)
        }

        for future in as_completed(future_to_page):
            page_number = future_to_page[future]
            try:
                page_results.append(future.result())
            except Exception as exc:
                failed_pages.append({"page_number": page_number, "error": str(exc)})
                if args.fail_fast:
                    raise

    page_results.sort(key=lambda result: result.page_number)

    raw_text = join_page_texts(result.raw_text for result in page_results)
    clean_text, clean_summary = clean_text_content(raw_text)
    prose_text = join_page_texts(result.prose_text for result in page_results)

    write_text(output_dir / "raw_text.txt", raw_text)
    write_text(output_dir / "clean_text.txt", clean_text)
    write_text(output_dir / "prose_text.txt", prose_text)

    ocr_confidences = [
        result.ocr_stats["mean_confidence"]
        for result in page_results
        if result.ocr_stats and result.ocr_stats["mean_confidence"] is not None
    ]
    page_method_counts: dict[str, int] = {}
    for result in page_results:
        page_method_counts[result.source_method] = page_method_counts.get(result.source_method, 0) + 1

    status = "completed"
    if failed_pages:
        status = "partial"
    if not page_results and failed_pages:
        status = "failed"

    metadata = {
        "source_pdf": str(pdf_path),
        "relative_path": relative_path,
        "output_dir": str(output_dir),
        "status": status,
        "started_at": datetime.fromtimestamp(started_at, tz=timezone.utc).replace(microsecond=0).isoformat(),
        "completed_at": now_iso(),
        "duration_seconds": round(time.time() - started_at, 2),
        "page_count": discovered_pages,
        "processed_pages": len(page_results),
        "failed_page_count": len(failed_pages),
        "page_method_counts": page_method_counts,
        "mean_ocr_confidence": mean(ocr_confidences) if ocr_confidences else None,
        "failed_pages": failed_pages,
        "document_cleaning_summary": clean_summary,
        "output_files": {
            "raw_text": str(output_dir / "raw_text.txt"),
            "clean_text": str(output_dir / "clean_text.txt"),
            "prose_text": str(output_dir / "prose_text.txt"),
        },
    }
    write_json(output_dir / "metadata.json", metadata)

    return {
        "relative_path": relative_path,
        "status": status,
        "output_dir": str(output_dir),
        "page_count": discovered_pages,
        "processed_pages": len(page_results),
        "failed_page_count": len(failed_pages),
        "page_method_counts": page_method_counts,
        "mean_ocr_confidence": metadata["mean_ocr_confidence"],
    }


def main() -> None:
    args = parse_args()
    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()

    if not input_root.exists():
        raise SystemExit(f"Input root does not exist: {input_root}")

    output_root.mkdir(parents=True, exist_ok=True)

    pdf_paths = discover_pdfs(input_root, args.match)
    if args.max_docs is not None:
        pdf_paths = pdf_paths[: args.max_docs]

    if not pdf_paths:
        raise SystemExit(f"No PDFs found under {input_root}")

    print(f"Discovered {len(pdf_paths)} PDFs under {input_root}")

    started_at = time.time()
    document_results: list[dict[str, object]] = []

    for index, pdf_path in enumerate(pdf_paths, start=1):
        relative_path = pdf_path.relative_to(input_root)
        print(f"[{index}/{len(pdf_paths)}] {relative_path}")
        try:
            result = process_document(pdf_path, input_root, output_root, args)
        except Exception as exc:
            result = {
                "relative_path": str(relative_path),
                "status": "failed",
                "error": str(exc),
            }
            if args.fail_fast:
                document_results.append(result)
                break

        document_results.append(result)
        print(f"  -> {result['status']}")

    summary = {
        "input_root": str(input_root),
        "output_root": str(output_root),
        "started_at": datetime.fromtimestamp(started_at, tz=timezone.utc).replace(microsecond=0).isoformat(),
        "completed_at": now_iso(),
        "duration_seconds": round(time.time() - started_at, 2),
        "documents_discovered": len(pdf_paths),
        "documents_completed": sum(1 for result in document_results if result["status"] == "completed"),
        "documents_partial": sum(1 for result in document_results if result["status"] == "partial"),
        "documents_skipped": sum(1 for result in document_results if result["status"] == "skipped"),
        "documents_failed": sum(1 for result in document_results if result["status"] == "failed"),
        "documents": document_results,
    }
    write_json(output_root / "run_manifest.json", summary)
    print(f"Wrote run manifest to {output_root / 'run_manifest.json'}")


if __name__ == "__main__":
    main()
