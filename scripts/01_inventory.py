#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from pipeline_utils import PROJECT_ROOT, OUTPUTS_DIR, ensure_dirs, list_paper_files, paper_id_from_path, read_text


def guess_title(text: str, path: Path) -> str:
    for line in text.splitlines()[:80]:
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    for line in text.splitlines()[:80]:
        stripped = line.strip()
        if 8 <= len(stripped) <= 220 and not stripped.startswith(("!", "|", "-", "*")):
            return stripped
    return path.stem


def guess_year(text: str, path: Path) -> str:
    filename_match = re.search(r"(19|20)\d{2}", path.stem)
    if filename_match:
        return filename_match.group(0)
    content_match = re.search(r"\b(19|20)\d{2}\b", text[:12000])
    return content_match.group(0) if content_match else ""


def guess_doi_or_url(text: str) -> str:
    doi = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", text, re.IGNORECASE)
    if doi:
        return doi.group(0).rstrip(".,;)")
    url = re.search(r"https?://\S+", text)
    if url:
        return url.group(0).rstrip(".,;)")
    return ""


def has_reference_section(text: str) -> bool:
    return bool(
        re.search(r"(?im)^#{0,6}\s*(references|bibliography|works cited|参考文献)\s*$", text)
        or re.search(r"(?im)^\s*(references|bibliography|参考文献)\s*$", text)
    )


def likely_ocr_issue(text: str) -> bool:
    if not text.strip():
        return True
    replacement_count = text.count("�")
    very_short_lines = sum(1 for line in text.splitlines() if 0 < len(line.strip()) <= 2)
    total_lines = max(1, len(text.splitlines()))
    return replacement_count > 10 or very_short_lines / total_lines > 0.35


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an inventory of Markdown papers.")
    parser.add_argument("--force", action="store_true", help="Accepted for UI compatibility; inventory is always regenerated.")
    parser.parse_args()

    ensure_dirs()
    papers = list_paper_files()
    inventory_path = OUTPUTS_DIR / "paper_inventory.csv"
    review_path = OUTPUTS_DIR / "metadata_needs_review.csv"

    inventory_rows: list[dict[str, str | int | bool]] = []
    review_rows: list[dict[str, str]] = []

    for path in papers:
        text = read_text(path)
        paper_id = paper_id_from_path(path)
        title = guess_title(text, path)
        year = guess_year(text, path)
        doi_or_url = guess_doi_or_url(text)
        refs = has_reference_section(text)
        ocr_issue = likely_ocr_issue(text)
        row = {
            "paper_id": paper_id,
            "file_path": str(path.relative_to(PROJECT_ROOT)),
            "title_guess": title,
            "year_guess": year,
            "doi_or_url_guess": doi_or_url,
            "char_count": len(text),
            "line_count": len(text.splitlines()),
            "has_reference_section": refs,
            "possible_ocr_issue": ocr_issue,
        }
        inventory_rows.append(row)

        notes = []
        if not title:
            notes.append("missing title")
        if not year:
            notes.append("missing year")
        if not doi_or_url:
            notes.append("missing DOI/URL")
        if ocr_issue:
            notes.append("possible OCR issue")
        if notes:
            review_rows.append(
                {
                    "paper_id": paper_id,
                    "file_path": str(path.relative_to(PROJECT_ROOT)),
                    "notes": "; ".join(notes),
                }
            )

    inventory_fields = [
        "paper_id",
        "file_path",
        "title_guess",
        "year_guess",
        "doi_or_url_guess",
        "char_count",
        "line_count",
        "has_reference_section",
        "possible_ocr_issue",
    ]
    with inventory_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=inventory_fields)
        writer.writeheader()
        writer.writerows(inventory_rows)

    with review_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["paper_id", "file_path", "notes"])
        writer.writeheader()
        writer.writerows(review_rows)

    print(f"Found {len(papers)} Markdown papers.")
    print(f"Wrote {inventory_path}")
    print(f"Wrote {review_path}")


if __name__ == "__main__":
    main()
