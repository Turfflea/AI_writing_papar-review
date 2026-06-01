#!/usr/bin/env python3
from __future__ import annotations

import argparse

from pipeline_utils import (
    SCREENING_DIR,
    author_year,
    brief_table,
    card_by_id,
    chat_completion,
    chunked,
    ensure_dirs,
    extract_json_object,
    json_dumps,
    load_cards,
    load_human_overrides,
    load_prompt,
    load_review_brief,
    log_event,
    md_escape,
    read_json,
    render_template,
    write_json,
    write_text,
)


def override_items(section: dict, key: str) -> list[dict]:
    items = section.get(key, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and str(item.get("paper_id", "")).strip()]


def remove_paper(selection: dict, paper_id: str) -> None:
    for key in ["final_core_papers", "supporting_papers", "peripheral_papers"]:
        rows = selection.get(key, [])
        if isinstance(rows, list):
            selection[key] = [row for row in rows if str(row.get("paper_id", "")) != paper_id]


def apply_core_overrides(selection: dict, all_cards: dict[str, dict]) -> dict:
    overrides = load_human_overrides().get("core_selection", {})
    if not isinstance(overrides, dict):
        return selection

    applied: list[dict] = []
    selection.setdefault("final_core_papers", [])
    selection.setdefault("supporting_papers", [])
    selection.setdefault("peripheral_papers", [])

    for item in override_items(overrides, "promote_to_core"):
        paper_id = str(item["paper_id"]).strip()
        remove_paper(selection, paper_id)
        card = all_cards.get(paper_id, {"paper_id": paper_id})
        selection["final_core_papers"].append(
            {
                "paper_id": paper_id,
                "author_year": author_year(card),
                "core_reason": item.get("reason") or "User manually promoted this paper to core.",
                "primary_roles": item.get("primary_roles") or ["findings"],
                "covered_review_questions": item.get("covered_review_questions", []),
                "priority": item.get("priority") or "high",
            }
        )
        applied.append({"action": "promote_to_core", "paper_id": paper_id})

    for item in override_items(overrides, "move_to_supporting"):
        paper_id = str(item["paper_id"]).strip()
        remove_paper(selection, paper_id)
        card = all_cards.get(paper_id, {"paper_id": paper_id})
        selection["supporting_papers"].append(
            {
                "paper_id": paper_id,
                "author_year": author_year(card),
                "supporting_reason": item.get("reason") or "User manually moved this paper to supporting.",
                "possible_use": item.get("possible_use") or ["background"],
            }
        )
        applied.append({"action": "move_to_supporting", "paper_id": paper_id})

    for item in override_items(overrides, "move_to_peripheral"):
        paper_id = str(item["paper_id"]).strip()
        remove_paper(selection, paper_id)
        card = all_cards.get(paper_id, {"paper_id": paper_id})
        selection["peripheral_papers"].append(
            {
                "paper_id": paper_id,
                "author_year": author_year(card),
                "reason": item.get("reason") or "User manually moved this paper to peripheral.",
            }
        )
        applied.append({"action": "move_to_peripheral", "paper_id": paper_id})

    if applied:
        selection["human_overrides_applied"] = applied
    return selection


def selection_to_markdown(selection: dict) -> str:
    lines = ["# Final Core Paper Selection", ""]

    def add_table(title: str, rows: list[dict], reason_key: str) -> None:
        lines.extend([f"## {title}", ""])
        lines.append("| paper_id | author_year | reason | roles/use | priority/confidence |")
        lines.append("|---|---|---|---|---|")
        for row in rows:
            roles = row.get("primary_roles") or row.get("possible_use") or row.get("main_use") or []
            priority = row.get("priority") or row.get("confidence") or ""
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_escape(row.get("paper_id", "")),
                        md_escape(row.get("author_year", "")),
                        md_escape(row.get(reason_key, "")),
                        md_escape(", ".join(map(str, roles))),
                        md_escape(priority),
                    ]
                )
                + " |"
            )
        lines.append("")

    add_table("Core Papers", selection.get("final_core_papers", []), "core_reason")
    add_table("Supporting Papers", selection.get("supporting_papers", []), "supporting_reason")
    add_table("Peripheral Papers", selection.get("peripheral_papers", []), "reason")

    lines.extend(["## Coverage Check", ""])
    coverage = selection.get("coverage_check", {})
    if isinstance(coverage, dict):
        for key, value in coverage.items():
            lines.append(f"- {key}: {value}")
    lines.extend(["", "## Recommended Review Structure", ""])
    for item in selection.get("recommended_review_structure", []):
        lines.append(f"### {item.get('section_title', '')}")
        lines.append("")
        lines.append(f"- Why needed: {item.get('why_this_section_is_needed', '')}")
        lines.append(f"- Main papers: {', '.join(map(str, item.get('main_papers_to_use', [])))}")
        lines.append("")
    lines.extend(["## Warnings", ""])
    for warning in selection.get("warnings", []):
        lines.append(f"- {warning}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Select core, supporting, and peripheral papers.")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Write prompts without calling the API.")
    parser.add_argument("--only-global", action="store_true", help="Use existing batch results and only run global selection.")
    parser.add_argument("--apply-overrides-only", action="store_true", help="Apply project_config/human_overrides.json to the existing final selection.")
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    args = parser.parse_args()

    ensure_dirs()
    review_brief = load_review_brief()
    batch_template = load_prompt("02_batch_core_screening.md")
    global_template = load_prompt("03_global_core_selection.md")
    cards = load_cards(compact=True)
    all_cards_by_id = card_by_id(compact=True)

    if not cards:
        print("No literature cards found. Run scripts/02_extract_cards.py first.")
        return

    final_path = SCREENING_DIR / "final_core_selection.json"
    if args.apply_overrides_only:
        if not final_path.exists():
            print(f"Missing {final_path}. Run normal screening first.")
            return
        selection = apply_core_overrides(read_json(final_path), all_cards_by_id)
        write_json(final_path, selection)
        write_text(SCREENING_DIR / "final_core_selection.md", selection_to_markdown(selection))
        core_ids = [str(item.get("paper_id", "")) for item in selection.get("final_core_papers", [])]
        write_text(SCREENING_DIR / "core_paper_ids.txt", "\n".join(core_ids) + ("\n" if core_ids else ""))
        print(f"Applied human overrides to {final_path}")
        return

    batch_results = []
    batches = chunked(cards, args.batch_size)
    if not args.only_global:
        for index, batch in enumerate(batches, start=1):
            batch_id = f"batch_{index:02d}"
            out_path = SCREENING_DIR / f"{batch_id}_screening.json"
            raw_path = SCREENING_DIR / f"{batch_id}_screening.raw_response.txt"
            prompt_path = SCREENING_DIR / f"{batch_id}_screening.prompt.md"
            if out_path.exists() and not args.force and not args.dry_run:
                print(f"[{index}/{len(batches)}] Skip existing batch: {batch_id}")
                batch_results.append(read_json(out_path))
                continue

            prompt = render_template(
                batch_template,
                {
                    "REVIEW_BRIEF": review_brief,
                    "BATCH_LITERATURE_CARDS_JSON": json_dumps(batch),
                    "BATCH_ID": batch_id,
                },
            )
            if args.dry_run:
                write_text(prompt_path, prompt)
                print(f"[{index}/{len(batches)}] Wrote dry-run prompt: {prompt_path}")
                continue

            print(f"[{index}/{len(batches)}] Screening {batch_id}")
            content, meta = chat_completion(
                prompt,
                model=args.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
            write_text(raw_path, content)
            result = extract_json_object(content)
            write_json(out_path, result)
            batch_results.append(result)
            log_event(
                "select_core_papers",
                {
                    "batch_id": batch_id,
                    "status": "ok",
                    "elapsed_seconds": meta.get("_elapsed_seconds"),
                },
            )

    if args.only_global:
        batch_results = [read_json(path) for path in sorted(SCREENING_DIR.glob("batch_*_screening.json"))]

    if args.dry_run:
        print("Dry run complete. Global prompt requires actual or existing batch results.")
        return

    if not batch_results:
        print("No batch screening results available.")
        return

    if final_path.exists() and not args.force:
        print(f"Skip existing global selection: {final_path}")
        return

    prompt = render_template(
        global_template,
        {
            "REVIEW_BRIEF": review_brief,
            "BATCH_SCREENING_RESULTS_JSON": json_dumps(batch_results),
            "ALL_PAPER_BRIEF_TABLE": brief_table(cards),
            "HUMAN_NOTES": json_dumps(load_human_overrides().get("core_selection", {})),
        },
    )
    prompt_path = SCREENING_DIR / "global_core_selection.prompt.md"
    raw_path = SCREENING_DIR / "global_core_selection.raw_response.txt"
    write_text(prompt_path, prompt)
    print("Running global core paper selection")
    content, meta = chat_completion(
        prompt,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    write_text(raw_path, content)
    selection = apply_core_overrides(extract_json_object(content), all_cards_by_id)
    write_json(final_path, selection)
    write_text(SCREENING_DIR / "final_core_selection.md", selection_to_markdown(selection))
    core_ids = [str(item.get("paper_id", "")) for item in selection.get("final_core_papers", [])]
    write_text(SCREENING_DIR / "core_paper_ids.txt", "\n".join(core_ids) + ("\n" if core_ids else ""))
    log_event(
        "select_core_papers",
        {
            "batch_id": "global",
            "status": "ok",
            "elapsed_seconds": meta.get("_elapsed_seconds"),
            "core_count": len(core_ids),
        },
    )
    print(f"Wrote {final_path}")


if __name__ == "__main__":
    main()
