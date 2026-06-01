#!/usr/bin/env python3
from __future__ import annotations

import argparse

from pipeline_utils import (
    EVIDENCE_DIR,
    SCREENING_DIR,
    SYNTHESIS_DIR,
    agent_readme,
    as_list,
    author_year,
    card_by_id,
    copy_files,
    ensure_dirs,
    get_in,
    json_dumps,
    load_cards,
    load_prompt,
    load_review_brief,
    markdown_table_to_csv,
    md_escape,
    open_terminal_at,
    read_all_markdown,
    read_json,
    render_template,
    reset_dir,
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


def selected_cards(scope: str) -> list[dict]:
    if scope == "selected" and (SCREENING_DIR / "final_core_selection.json").exists():
        selection = read_json(SCREENING_DIR / "final_core_selection.json")
        selected = ids_from_selection(selection)
        all_cards = card_by_id(compact=True)
        return [all_cards[paper_id] for paper_id in selected if paper_id in all_cards]
    return load_cards(compact=True)


def prepare_agent_workspace(scope: str, agent: str, force: bool, open_terminal: bool) -> None:
    cards = selected_cards(scope)
    if not cards:
        print("No literature cards found. Run scripts/02_extract_cards.py first.")
        return

    synthesis_paths = sorted(SYNTHESIS_DIR.glob("*_synthesis.md"))
    if not synthesis_paths:
        print("No synthesis files found. Run scripts/05_synthesize_dimensions.py first.")
        return

    input_dir = EVIDENCE_DIR / "input"
    reset_dir(input_dir)
    write_text(input_dir / "review_brief.md", load_review_brief())
    write_text(input_dir / "review_dimensions.md", review_dimensions_text() + "\n")
    write_text(input_dir / "literature_cards.json", json_dumps(cards) + "\n")
    write_text(input_dir / "all_synthesis.md", read_all_markdown(synthesis_paths) + "\n")
    copy_files(synthesis_paths, input_dir / "synthesis")
    if (SCREENING_DIR / "final_core_selection.json").exists():
        write_text(input_dir / "final_core_selection.json", json_dumps(read_json(SCREENING_DIR / "final_core_selection.json")) + "\n")

    template = load_prompt("05_evidence_matrix.md")
    prompt = render_template(
        template,
        {
            "REVIEW_BRIEF": load_review_brief(),
            "REVIEW_DIMENSIONS": review_dimensions_text(),
            "LITERATURE_CARDS_JSON": json_dumps(cards),
            "SYNTHESIS_MARKDOWN": read_all_markdown(synthesis_paths),
        },
    )
    prompt_path = EVIDENCE_DIR / "prompt.md"
    if prompt_path.exists() and not force:
        write_text(EVIDENCE_DIR / "prompt.latest.md", prompt)
        print(f"Kept existing prompt: {prompt_path}")
        print(f"Wrote refreshed prompt draft: {EVIDENCE_DIR / 'prompt.latest.md'}")
    else:
        write_text(prompt_path, prompt)
        print(f"Wrote prompt: {prompt_path}")

    write_text(
        EVIDENCE_DIR / "README.md",
        agent_readme(
            "第 6 步：证据矩阵",
            agent,
            ["evidence_matrix.md", "evidence_matrix.csv（可选）"],
        ),
    )
    print(f"Prepared Agent workspace: {EVIDENCE_DIR}")
    print("Terminal will open at this folder. If you have no extra instruction, tell the Agent: 按照项目中的.md 输出内容")
    if open_terminal:
        if open_terminal_at(EVIDENCE_DIR):
            print("Opened terminal for Agent work.")
        else:
            print(f"Could not open a terminal automatically. Open one manually at: {EVIDENCE_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the evidence-matrix Agent workspace.")
    parser.add_argument("--scope", choices=["selected", "all"], default="selected")
    parser.add_argument("--local", action="store_true", help="Generate a simple matrix without API.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument("--no-open-terminal", action="store_true")
    args = parser.parse_args()

    ensure_dirs()
    matrix_path = EVIDENCE_DIR / "evidence_matrix.md"
    csv_path = EVIDENCE_DIR / "evidence_matrix.csv"
    if args.local and matrix_path.exists() and not args.force:
        print(f"Skip existing evidence matrix: {matrix_path}")
        return

    cards = selected_cards(args.scope)

    if not cards:
        print("No literature cards found. Run scripts/02_extract_cards.py first.")
        return

    if args.local:
        markdown = local_matrix(cards)
        write_text(matrix_path, markdown)
        markdown_table_to_csv(markdown, csv_path)
        print(f"Wrote local evidence matrix: {matrix_path}")
        return

    prepare_agent_workspace(args.scope, args.agent, args.force, not args.no_open_terminal)


if __name__ == "__main__":
    main()
