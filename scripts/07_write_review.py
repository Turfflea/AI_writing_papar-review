#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from pipeline_utils import (
    DRAFTS_DIR,
    EVIDENCE_DIR,
    OUTLINE_DIR,
    SCREENING_DIR,
    SECTIONS_DIR,
    SYNTHESIS_DIR,
    agent_readme,
    card_by_id,
    copy_files,
    ensure_dirs,
    extract_outline_sections,
    json_dumps,
    human_note_for_section,
    load_cards,
    load_prompt,
    load_review_brief,
    open_terminal_at,
    read_all_markdown,
    read_json,
    read_text,
    render_template,
    reset_dir,
    review_dimensions_text,
    write_text,
)


def load_core_cards(compact: bool = True) -> list[dict]:
    cards_by_id = card_by_id(compact=compact)
    selection_path = SCREENING_DIR / "final_core_selection.json"
    if not selection_path.exists():
        return load_cards(compact=compact)
    selection = read_json(selection_path)
    ids = [str(item.get("paper_id", "")) for item in selection.get("final_core_papers", [])]
    return [cards_by_id[paper_id] for paper_id in ids if paper_id in cards_by_id]


def choose_sections(outline_text: str, section_title: str, section_brief: str, limit: int) -> list[dict[str, str]]:
    sections = extract_outline_sections(outline_text) if outline_text else []
    if section_title:
        for section in sections:
            if section_title == section["title"] or section_title in section["title"] or section["title"] in section_title:
                return [section]
        return [{"title": section_title, "brief": section_brief or section_title}]
    if not sections and outline_text:
        sections = [{"title": "文献综述正文", "brief": outline_text}]
    if limit > 0:
        sections = sections[:limit]
    return sections


def outline_path() -> tuple[Path, str]:
    preferred = OUTLINE_DIR / "review_outline.md"
    legacy = DRAFTS_DIR / "review_outline.md"
    if preferred.exists():
        return preferred, read_text(preferred)
    if legacy.exists():
        return legacy, read_text(legacy)
    return preferred, ""


def prepare_agent_workspace(
    section_title: str,
    section_brief: str,
    limit: int,
    compact_cards: bool,
    agent: str,
    force: bool,
    open_terminal: bool,
) -> None:
    outline_file, outline_text = outline_path()
    matrix_path = EVIDENCE_DIR / "evidence_matrix.md"
    synthesis_paths = sorted(SYNTHESIS_DIR.glob("*_synthesis.md"))

    if not outline_text and not (section_title and section_brief):
        print("Missing review outline. Run scripts/06_generate_outline.py first, or pass --section-title and --section-brief.")
        return
    if not matrix_path.exists():
        print("Missing evidence matrix. Run scripts/05_evidence_matrix.py first.")
        return
    if not synthesis_paths:
        print("Missing synthesis files. Run scripts/05_synthesize_dimensions.py first.")
        return

    core_cards = load_core_cards(compact=compact_cards)
    if not core_cards:
        print("No core cards found. Run scripts/04_select_core_papers.py first.")
        return

    sections = choose_sections(outline_text, section_title, section_brief, limit)
    if not sections:
        sections = [{"title": "文献综述草稿", "brief": outline_text or section_brief}]

    input_dir = DRAFTS_DIR / "input"
    reset_dir(input_dir)
    SECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    write_text(input_dir / "review_brief.md", load_review_brief())
    write_text(input_dir / "review_dimensions.md", review_dimensions_text() + "\n")
    write_text(input_dir / "review_outline.md", outline_text)
    write_text(input_dir / "outline_source.txt", str(outline_file) + "\n")
    write_text(input_dir / "evidence_matrix.md", read_text(matrix_path))
    write_text(input_dir / "all_synthesis.md", read_all_markdown(synthesis_paths) + "\n")
    write_text(input_dir / "core_cards.json", json_dumps(core_cards) + "\n")
    write_text(input_dir / "section_tasks.json", json_dumps(sections) + "\n")
    if (SCREENING_DIR / "final_core_selection.json").exists():
        write_text(input_dir / "final_core_selection.json", json_dumps(read_json(SCREENING_DIR / "final_core_selection.json")) + "\n")
    copy_files(synthesis_paths, input_dir / "synthesis")

    section_prompt_title = section_title or "文献综述草稿"
    if section_title:
        prompt_section_brief = sections[0]["brief"] if sections else section_brief
        section_notes = human_note_for_section(section_prompt_title) or "无"
    else:
        prompt_section_brief = (
            "请根据 input/review_outline.md 中的大纲逐章写作。"
            "每个章节可以先保存到 sections/ 文件夹，最后合并为 final_review.md。"
            "章节任务清单也已保存到 input/section_tasks.json。\n\n"
            + (outline_text or section_brief)
        )
        section_notes = "无"

    template = load_prompt("07_section_writing.md")
    prompt = render_template(
        template,
        {
            "REVIEW_BRIEF": load_review_brief(),
            "REVIEW_DIMENSIONS": review_dimensions_text(),
            "SECTION_BRIEF": prompt_section_brief,
            "RELEVANT_SYNTHESIS_MARKDOWN": read_all_markdown(synthesis_paths),
            "RELEVANT_EVIDENCE_MATRIX": read_text(matrix_path),
            "RELEVANT_CORE_CARDS_JSON": json_dumps(core_cards),
            "SECTION_NOTES": section_notes,
            "SECTION_TITLE": section_prompt_title,
        },
    )
    prompt_path = DRAFTS_DIR / "prompt.md"
    if prompt_path.exists() and not force:
        write_text(DRAFTS_DIR / "prompt.latest.md", prompt)
        print(f"Kept existing prompt: {prompt_path}")
        print(f"Wrote refreshed prompt draft: {DRAFTS_DIR / 'prompt.latest.md'}")
    else:
        write_text(prompt_path, prompt)
        print(f"Wrote prompt: {prompt_path}")

    write_text(
        DRAFTS_DIR / "README.md",
        agent_readme("第 8 步：逐章写作", agent, ["sections/*.md", "final_review.md"]),
    )
    print(f"Prepared Agent workspace: {DRAFTS_DIR}")
    print("Terminal will open at this folder. If you have no extra instruction, tell the Agent: 按照项目中的.md 输出内容")
    if open_terminal:
        if open_terminal_at(DRAFTS_DIR):
            print("Opened terminal for Agent work.")
        else:
            print(f"Could not open a terminal automatically. Open one manually at: {DRAFTS_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the review-drafting Agent workspace.")
    parser.add_argument("--section-title", default="", help="Write only one section.")
    parser.add_argument("--section-brief", default="", help="Brief for --section-title if it is not in the outline.")
    parser.add_argument("--limit", type=int, default=0, help="Only write the first N parsed sections.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--compact-cards", action="store_true", help="Use compact core cards to reduce context.")
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument("--no-open-terminal", action="store_true")
    args = parser.parse_args()

    ensure_dirs()
    prepare_agent_workspace(
        args.section_title,
        args.section_brief,
        args.limit,
        args.compact_cards,
        args.agent,
        args.force,
        not args.no_open_terminal,
    )


if __name__ == "__main__":
    main()
