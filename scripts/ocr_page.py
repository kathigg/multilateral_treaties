#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

import cv2
import numpy as np


@dataclass
class OcrStats:
    mean_confidence: float | None
    low_confidence_ratio: float | None
    word_count: int
    low_confidence_word_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preprocess a page image, OCR it with Tesseract, and write raw plus cleaned outputs."
    )
    parser.add_argument("input_path", type=Path, help="Path to the page image.")
    parser.add_argument("output_dir", type=Path, help="Directory for OCR artifacts.")
    parser.add_argument("--lang", default="eng", help="Tesseract language.")
    parser.add_argument("--psm", type=int, default=4, help="Tesseract page segmentation mode.")
    parser.add_argument("--oem", type=int, default=1, help="Tesseract OCR engine mode.")
    parser.add_argument(
        "--upscale",
        type=float,
        default=2.0,
        help="Image scale factor applied before OCR.",
    )
    return parser.parse_args()


def read_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return image


def crop_margins(image: np.ndarray, threshold: int = 245, padding: int = 12) -> np.ndarray:
    mask = image < threshold
    coords = np.argwhere(mask)
    if coords.size == 0:
        return image

    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0)
    y0 = max(0, y0 - padding)
    x0 = max(0, x0 - padding)
    y1 = min(image.shape[0], y1 + padding + 1)
    x1 = min(image.shape[1], x1 + padding + 1)
    return image[y0:y1, x0:x1]


def deskew(image: np.ndarray) -> np.ndarray:
    inverted = cv2.bitwise_not(image)
    _, thresh = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(thresh > 0))
    if coords.size == 0:
        return image

    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.1:
        return image

    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        image,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def preprocess_image(image: np.ndarray, upscale: float) -> np.ndarray:
    image = crop_margins(image)
    image = deskew(image)

    if upscale != 1.0:
        image = cv2.resize(image, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)

    image = cv2.GaussianBlur(image, (3, 3), 0)
    _, image = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return image


def run_tesseract(image_path: Path, output_base: Path, lang: str, psm: int, oem: int) -> None:
    command = [
        "tesseract",
        str(image_path),
        str(output_base),
        "-l",
        lang,
        "--oem",
        str(oem),
        "--psm",
        str(psm),
        "txt",
        "tsv",
    ]
    subprocess.run(command, check=True)


def parse_tsv(tsv_path: Path) -> OcrStats:
    confidences: list[float] = []
    low_confidences = 0

    with tsv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            text = (row.get("text") or "").strip()
            conf = row.get("conf", "")
            if not text or conf in {"", "-1"}:
                continue
            value = float(conf)
            confidences.append(value)
            if value < 70:
                low_confidences += 1

    if not confidences:
        return OcrStats(None, None, 0, 0)

    return OcrStats(
        mean_confidence=mean(confidences),
        low_confidence_ratio=low_confidences / len(confidences),
        word_count=len(confidences),
        low_confidence_word_count=low_confidences,
    )


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_wrapped_lines(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    blocks: list[str] = []
    current: list[str] = []

    for line in lines:
        if not line.strip():
            if current:
                blocks.append(join_block(current))
                current = []
            continue
        current.append(line.strip())

    if current:
        blocks.append(join_block(current))

    return "\n\n".join(blocks).strip() + "\n"


def join_block(lines: list[str]) -> str:
    text = " ".join(lines)
    text = re.sub(r"(?<=\w)- (?=[a-z])", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_table_like(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if "|" in stripped:
        return True
    if "Whence derived." in stripped:
        return True
    if stripped.count("Francs.") >= 2:
        return True
    number_groups = re.findall(r"\d[\d,]*", stripped)
    if len(number_groups) >= 3:
        return True
    alpha = sum(char.isalpha() for char in stripped)
    if len(number_groups) >= 2 and alpha <= 3:
        return True
    digits = sum(char.isdigit() for char in stripped)
    punctuation = sum(char in "._-—=:;[](){}" for char in stripped)
    if alpha == 0 and punctuation > 2:
        return True
    return False


def is_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) <= 3 and not any(char.isalpha() for char in stripped):
        return True
    alpha = sum(char.isalpha() for char in stripped)
    punctuation = sum(char in "._-—=:;[](){}~/\\|" for char in stripped)
    if alpha < 8 and punctuation >= 3:
        return True
    if re.fullmatch(r"[\W_]+", stripped):
        return True
    return False


def build_prose_text(raw_text: str) -> str:
    kept_lines: list[str] = []
    in_table = False

    for line in raw_text.splitlines():
        if not line.strip():
            if kept_lines and kept_lines[-1] != "":
                kept_lines.append("")
            in_table = False
            continue
        if in_table:
            continue
        if is_noise_line(line):
            continue
        if is_table_like(line):
            in_table = True
            continue
        kept_lines.append(line)

    prose = "\n".join(kept_lines)
    prose = re.sub(r"\n{3,}", "\n\n", prose).strip()
    return normalize_wrapped_lines(prose)


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    image = read_image(args.input_path)
    processed = preprocess_image(image, upscale=args.upscale)

    preprocessed_path = args.output_dir / "preprocessed.png"
    cv2.imwrite(str(preprocessed_path), processed)

    output_base = args.output_dir / "ocr"
    run_tesseract(preprocessed_path, output_base, args.lang, args.psm, args.oem)

    raw_text = load_text(output_base.with_suffix(".txt"))
    raw_text_path = args.output_dir / "raw_text.txt"
    raw_text_path.write_text(raw_text, encoding="utf-8")

    clean_text = normalize_wrapped_lines(raw_text)
    write_text(args.output_dir / "clean_text.txt", clean_text)
    write_text(args.output_dir / "prose_text.txt", build_prose_text(raw_text))

    stats = parse_tsv(output_base.with_suffix(".tsv"))
    metadata = {
        "input_path": str(args.input_path),
        "preprocessed_image_path": str(preprocessed_path),
        "lang": args.lang,
        "psm": args.psm,
        "oem": args.oem,
        "upscale": args.upscale,
        "image_shape": {"height": int(image.shape[0]), "width": int(image.shape[1])},
        "ocr_stats": {
            "mean_confidence": stats.mean_confidence,
            "low_confidence_ratio": stats.low_confidence_ratio,
            "word_count": stats.word_count,
            "low_confidence_word_count": stats.low_confidence_word_count,
        },
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
