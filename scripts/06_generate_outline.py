#!/usr/bin/env python3
from __future__ import annotations

import argparse

from pipeline_utils import (
    EVIDENCE_DIR,
    OUTLINE_DIR,
    SCREENING_DIR,
    SYNTHESIS_DIR,
    agent_readme,
    copy_files,
    ensure_dirs,
    json_dumps,
    load_prompt,
    load_review_brief,
    outline_human_notes,
    open_terminal_at,
    read_all_markdown,
    read_json,
    read_text,
    render_template,
    reset_dir,
    review_dimensions_text,
    write_text,
)


def prepare_agent_workspace(agent: str, force: bool, open_terminal: bool) -> None:
    selection_path = SCREENING_DIR / "final_core_selection.json"
    matrix_path = EVIDENCE_DIR / "evidence_matrix.md"
    synthesis_paths = sorted(SYNTHESIS_DIR.glob("*_synthesis.md"))

    missing = []
    if not selection_path.exists():
        missing.append(str(selection_path))
    if not matrix_path.exists():
        missing.append(str(matrix_path))
    if not synthesis_paths:
        missing.append(str(SYNTHESIS_DIR / "*_synthesis.md"))
    if missing:
        print("Missing required inputs:")
        for item in missing:
            print(f"- {item}")
        return

    input_dir = OUTLINE_DIR / "input"
    reset_dir(input_dir)
    write_text(input_dir / "review_brief.md", load_review_brief())
    write_text(input_dir / "review_dimensions.md", review_dimensions_text() + "\n")
    write_text(input_dir / "final_core_selection.json", json_dumps(read_json(selection_path)) + "\n")
    write_text(input_dir / "all_synthesis.md", read_all_markdown(synthesis_paths) + "\n")
    write_text(input_dir / "evidence_matrix.md", read_text(matrix_path))
    write_text(input_dir / "outline_notes.md", (outline_human_notes() or "无") + "\n")
    copy_files(synthesis_paths, input_dir / "synthesis")

    template = load_prompt("06_outline_generation.md")
    prompt = render_template(
        template,
        {
            "REVIEW_BRIEF": load_review_brief(),
            "REVIEW_DIMENSIONS": review_dimensions_text(),
            "FINAL_CORE_SELECTION_JSON": json_dumps(read_json(selection_path)),
            "ALL_SYNTHESIS_MARKDOWN": read_all_markdown(synthesis_paths),
            "EVIDENCE_MATRIX_MARKDOWN": read_text(matrix_path),
            "OUTLINE_NOTES": outline_human_notes() or "无",
        },
    )
    prompt_path = OUTLINE_DIR / "prompt.md"
    if prompt_path.exists() and not force:
        write_text(OUTLINE_DIR / "prompt.latest.md", prompt)
        print(f"Kept existing prompt: {prompt_path}")
        print(f"Wrote refreshed prompt draft: {OUTLINE_DIR / 'prompt.latest.md'}")
    else:
        write_text(prompt_path, prompt)
        print(f"Wrote prompt: {prompt_path}")

    write_text(
        OUTLINE_DIR / "README.md",
        agent_readme("第 7 步：综述大纲", agent, ["review_outline.md"]),
    )
    print(f"Prepared Agent workspace: {OUTLINE_DIR}")
    print("Terminal will open at this folder. If you have no extra instruction, tell the Agent: 按照项目中的.md 输出内容")
    if open_terminal:
        if open_terminal_at(OUTLINE_DIR):
            print("Opened terminal for Agent work.")
        else:
            print(f"Could not open a terminal automatically. Open one manually at: {OUTLINE_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the review-outline Agent workspace.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument("--no-open-terminal", action="store_true")
    args = parser.parse_args()

    ensure_dirs()
    prepare_agent_workspace(args.agent, args.force, not args.no_open_terminal)


if __name__ == "__main__":
    main()
