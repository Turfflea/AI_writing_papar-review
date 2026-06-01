#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from typing import Any

from pipeline_utils import (
    OUTPUTS_DIR,
    as_list,
    ensure_dirs,
    get_in,
    load_cards,
    write_json,
    write_text,
)


REQUIRED_PATHS = [
    "paper_id",
    "bibliographic_info.title",
    "research_problem.summary",
    "research_problem.fit_to_review_topic",
    "methodology.method_type",
    "contribution_to_review.possible_use_in_review",
    "one_sentence_summary",
]


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().lower() in {"uncertain", "unknown", "n/a"}
    if isinstance(value, (list, dict)):
        return not value
    return False


def validate_card(card: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []

    for path in REQUIRED_PATHS:
        if is_empty(get_in(card, path)):
            issues.append(f"missing_or_uncertain:{path}")

    findings = as_list(card.get("main_findings"))
    if not findings:
        issues.append("missing:main_findings")
    elif len(findings) < 3:
        warnings.append("few_main_findings")

    evidence_count = 0
    for finding in findings:
        if isinstance(finding, dict) and not is_empty(finding.get("evidence_quote")):
            evidence_count += 1
    for quote in as_list(get_in(card, "methodology.evidence_quotes", [])):
        if not is_empty(quote):
            evidence_count += 1
    for quote in as_list(get_in(card, "theoretical_perspective.evidence_quotes", [])):
        if not is_empty(quote):
            evidence_count += 1

    if evidence_count == 0:
        issues.append("missing:evidence_quotes")
    elif evidence_count < 3:
        warnings.append("weak:evidence_quotes")

    scores = card.get("screening_scores", {})
    if not isinstance(scores, dict) or not scores:
        warnings.append("missing:screening_scores")
    else:
        for key, value in scores.items():
            try:
                number = int(value)
            except Exception:
                warnings.append(f"invalid_score:{key}")
                continue
            if number < 1 or number > 5:
                warnings.append(f"score_out_of_range:{key}")

    text_length = len(str(card))
    if text_length < 1500:
        warnings.append("card_may_be_too_short")

    status = "ok"
    if issues:
        status = "issue"
    elif warnings:
        status = "warning"

    return {
        "paper_id": card.get("paper_id", ""),
        "status": status,
        "issues": issues,
        "warnings": warnings,
        "evidence_count": evidence_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check generated literature cards for completeness.")
    parser.add_argument("--fail-on-issues", action="store_true", help="Exit with code 1 if issues are found.")
    parser.add_argument("--force", action="store_true", help="Accepted for UI compatibility; quality reports are always regenerated.")
    args = parser.parse_args()

    ensure_dirs()
    cards = load_cards(compact=False)
    reports = [validate_card(card) for card in cards]

    report_path = OUTPUTS_DIR / "quality_report.json"
    issues_path = OUTPUTS_DIR / "quality_issues.md"
    write_json(report_path, {"card_count": len(cards), "reports": reports})

    lines = ["# Literature Card Quality Report", ""]
    if not cards:
        lines.append("No card files found in `outputs/literature_cards/`.")
    else:
        issue_count = sum(1 for item in reports if item["status"] == "issue")
        warning_count = sum(1 for item in reports if item["status"] == "warning")
        lines.append(f"- Cards checked: {len(cards)}")
        lines.append(f"- Cards with issues: {issue_count}")
        lines.append(f"- Cards with warnings: {warning_count}")
        lines.append("")
        for item in reports:
            if item["status"] == "ok":
                continue
            lines.append(f"## {item['paper_id']}")
            lines.append("")
            for issue in item["issues"]:
                lines.append(f"- ISSUE: {issue}")
            for warning in item["warnings"]:
                lines.append(f"- WARNING: {warning}")
            lines.append("")

    write_text(issues_path, "\n".join(lines))
    print(f"Checked {len(cards)} cards.")
    print(f"Wrote {report_path}")
    print(f"Wrote {issues_path}")

    if args.fail_on_issues and any(item["status"] == "issue" for item in reports):
        sys.exit(1)


if __name__ == "__main__":
    main()
