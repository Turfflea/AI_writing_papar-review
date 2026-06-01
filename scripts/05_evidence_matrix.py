#!/usr/bin/env python3
from __future__ import annotations

import argparse

from pipeline_utils import (
    EVIDENCE_DIR,
    SCREENING_DIR,
    SYNTHESIS_DIR,
    as_list,
    author_year,
    card_by_id,
    chat_completion,
    ensure_dirs,
    get_in,
    json_dumps,
    load_cards,
    load_prompt,
    load_review_brief,
    log_event,
    markdown_table_to_csv,
    md_escape,
    read_all_markdown,
    read_json,
    render_template,
    review_dimensions_text,
    write_text,
)


def ids_from_selection(selection: dict) -> set[str]:
    ids: set[str] = set()
    for key in ["final_core_papers", "supporting_papers"]:
        for item in selection.get(key, []):
            paper_id = item.get("paper_id")
            if paper_id:
                ids.add(str(paper_id))
    return ids


def local_matrix(cards: list[dict]) -> str:
    lines = [
        "| evidence_id | paper_id | author_year | 综述维度 | 主题标签 | 研究方法 | 主要判断 | 证据摘要 | 原文摘录或定位 | 可用于章节 | 证据强度 | 备注 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    counter = 1
    for card in cards:
        paper_id = str(card.get("paper_id", ""))
        method = get_in(card, "methodology.method_type")
        sections = ", ".join(map(str, as_list(get_in(card, "contribution_to_review.can_support_sections", []))))
        concepts = as_list(card.get("key_concepts"))
        topic = ""
        if concepts and isinstance(concepts[0], dict):
            topic = concepts[0].get("concept", "")
        elif concepts:
            topic = str(concepts[0])

        method_summary = "; ".join(map(str, as_list(get_in(card, "methodology.specific_methods", []))))
        if method_summary:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"E{counter:04d}",
                        md_escape(paper_id),
                        md_escape(author_year(card)),
                        "研究方法",
                        md_escape(topic),
                        md_escape(method),
                        md_escape(method_summary),
                        md_escape(get_in(card, "methodology.sample_or_cases")),
                        md_escape("; ".join(map(str, as_list(get_in(card, "methodology.evidence_quotes", []))))),
                        md_escape(sections),
                        "medium",
                        "local fallback generated from card",
                    ]
                )
                + " |"
            )
            counter += 1

        for finding in as_list(card.get("main_findings")):
            if isinstance(finding, dict):
                claim = finding.get("finding", "")
                evidence = finding.get("evidence_quote", "")
            else:
                claim = str(finding)
                evidence = ""
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"E{counter:04d}",
                        md_escape(paper_id),
                        md_escape(author_year(card)),
                        "研究发现",
                        md_escape(topic),
                        md_escape(method),
                        md_escape(claim),
                        md_escape(claim),
                        md_escape(evidence),
                        md_escape(sections),
                        "high" if evidence else "low",
                        "" if evidence else "需要回看全文",
                    ]
                )
                + " |"
            )
            counter += 1
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a traceable evidence matrix.")
    parser.add_argument("--scope", choices=["selected", "all"], default="selected")
    parser.add_argument("--local", action="store_true", help="Generate a simple matrix without API.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    args = parser.parse_args()

    ensure_dirs()
    matrix_path = EVIDENCE_DIR / "evidence_matrix.md"
    csv_path = EVIDENCE_DIR / "evidence_matrix.csv"
    if matrix_path.exists() and not args.force:
        print(f"Skip existing evidence matrix: {matrix_path}")
        return

    if args.scope == "selected" and (SCREENING_DIR / "final_core_selection.json").exists():
        selection = read_json(SCREENING_DIR / "final_core_selection.json")
        selected = ids_from_selection(selection)
        all_cards = card_by_id(compact=True)
        cards = [all_cards[paper_id] for paper_id in selected if paper_id in all_cards]
    else:
        cards = load_cards(compact=True)

    if not cards:
        print("No literature cards found. Run scripts/02_extract_cards.py first.")
        return

    if args.local:
        markdown = local_matrix(cards)
        write_text(matrix_path, markdown)
        markdown_table_to_csv(markdown, csv_path)
        print(f"Wrote local evidence matrix: {matrix_path}")
        return

    synthesis_paths = sorted(SYNTHESIS_DIR.glob("*_synthesis.md"))
    if not synthesis_paths:
        print("No synthesis files found. Run scripts/05_synthesize_dimensions.py first.")
        return

    review_brief = load_review_brief()
    template = load_prompt("05_evidence_matrix.md")
    synthesis_markdown = read_all_markdown(synthesis_paths)
    prompt = render_template(
        template,
        {
            "REVIEW_BRIEF": review_brief,
            "REVIEW_DIMENSIONS": review_dimensions_text(),
            "LITERATURE_CARDS_JSON": json_dumps(cards),
            "SYNTHESIS_MARKDOWN": synthesis_markdown,
        },
    )
    prompt_path = EVIDENCE_DIR / "evidence_matrix.prompt.md"
    raw_path = EVIDENCE_DIR / "evidence_matrix.raw_response.md"
    write_text(prompt_path, prompt)
    print("Generating evidence matrix")
    content, meta = chat_completion(
        prompt,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    write_text(raw_path, content)
    write_text(matrix_path, content)
    markdown_table_to_csv(content, csv_path)
    log_event(
        "evidence_matrix",
        {"status": "ok", "elapsed_seconds": meta.get("_elapsed_seconds"), "output": str(matrix_path)},
    )
    print(f"Wrote {matrix_path}")
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
