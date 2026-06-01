#!/usr/bin/env python3
from __future__ import annotations

import argparse

from pipeline_utils import (
    DRAFTS_DIR,
    EVIDENCE_DIR,
    SCREENING_DIR,
    SECTIONS_DIR,
    SYNTHESIS_DIR,
    card_by_id,
    chat_completion,
    ensure_dirs,
    extract_outline_sections,
    json_dumps,
    load_cards,
    load_prompt,
    load_review_brief,
    log_event,
    read_all_markdown,
    read_json,
    read_text,
    render_template,
    slugify,
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


def merge_sections(sections: list[dict[str, str]]) -> str:
    parts = ["# 文献综述草稿", ""]
    for section in sections:
        path = SECTIONS_DIR / f"{slugify(section['title'], fallback='section')}.md"
        if path.exists():
            parts.append(read_text(path).strip())
            parts.append("")
    return "\n\n".join(part for part in parts if part.strip()) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Write review sections from the generated outline.")
    parser.add_argument("--section-title", default="", help="Write only one section.")
    parser.add_argument("--section-brief", default="", help="Brief for --section-title if it is not in the outline.")
    parser.add_argument("--limit", type=int, default=0, help="Only write the first N parsed sections.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--compact-cards", action="store_true", help="Use compact core cards to reduce context.")
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    args = parser.parse_args()

    ensure_dirs()
    outline_path = DRAFTS_DIR / "review_outline.md"
    matrix_path = EVIDENCE_DIR / "evidence_matrix.md"
    synthesis_paths = sorted(SYNTHESIS_DIR.glob("*_synthesis.md"))

    outline_text = read_text(outline_path) if outline_path.exists() else ""
    if not outline_text and not (args.section_title and args.section_brief):
        print("Missing review outline. Run scripts/06_generate_outline.py first, or pass --section-title and --section-brief.")
        return
    if not matrix_path.exists():
        print("Missing evidence matrix. Run scripts/05_evidence_matrix.py first.")
        return
    if not synthesis_paths:
        print("Missing synthesis files. Run scripts/05_synthesize_dimensions.py first.")
        return

    sections = choose_sections(outline_text, args.section_title, args.section_brief, args.limit)
    if not sections:
        print("No sections found in the outline.")
        return

    review_brief = load_review_brief()
    template = load_prompt("07_section_writing.md")
    synthesis_markdown = read_all_markdown(synthesis_paths)
    evidence_matrix = read_text(matrix_path)
    core_cards = load_core_cards(compact=args.compact_cards)
    if not core_cards:
        print("No core cards found. Run scripts/04_select_core_papers.py first.")
        return

    for index, section in enumerate(sections, start=1):
        title = section["title"]
        out_path = SECTIONS_DIR / f"{slugify(title, fallback='section')}.md"
        prompt_path = SECTIONS_DIR / f"{slugify(title, fallback='section')}.prompt.md"
        raw_path = SECTIONS_DIR / f"{slugify(title, fallback='section')}.raw_response.md"
        if out_path.exists() and not args.force:
            print(f"[{index}/{len(sections)}] Skip existing section: {out_path}")
            continue

        prompt = render_template(
            template,
            {
                "REVIEW_BRIEF": review_brief,
                "SECTION_BRIEF": section["brief"],
                "RELEVANT_SYNTHESIS_MARKDOWN": synthesis_markdown,
                "RELEVANT_EVIDENCE_MATRIX": evidence_matrix,
                "RELEVANT_CORE_CARDS_JSON": json_dumps(core_cards),
                "SECTION_TITLE": title,
            },
        )
        write_text(prompt_path, prompt)
        print(f"[{index}/{len(sections)}] Writing section: {title}")
        content, meta = chat_completion(
            prompt,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        write_text(raw_path, content)
        write_text(out_path, content)
        log_event(
            "write_review",
            {
                "section_title": title,
                "status": "ok",
                "elapsed_seconds": meta.get("_elapsed_seconds"),
                "output": str(out_path),
            },
        )
        print(f"Wrote {out_path}")

    final_path = DRAFTS_DIR / "final_review.md"
    write_text(final_path, merge_sections(sections))
    print(f"Wrote {final_path}")


if __name__ == "__main__":
    main()

