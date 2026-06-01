#!/usr/bin/env python3
from __future__ import annotations

import argparse

from pipeline_utils import (
    DRAFTS_DIR,
    EVIDENCE_DIR,
    SCREENING_DIR,
    SYNTHESIS_DIR,
    chat_completion,
    ensure_dirs,
    json_dumps,
    load_prompt,
    load_review_brief,
    log_event,
    read_all_markdown,
    read_json,
    read_text,
    render_template,
    write_text,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a review outline from synthesis and evidence.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    args = parser.parse_args()

    ensure_dirs()
    outline_path = DRAFTS_DIR / "review_outline.md"
    if outline_path.exists() and not args.force:
        print(f"Skip existing outline: {outline_path}")
        return

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

    review_brief = load_review_brief()
    template = load_prompt("06_outline_generation.md")
    prompt = render_template(
        template,
        {
            "REVIEW_BRIEF": review_brief,
            "FINAL_CORE_SELECTION_JSON": json_dumps(read_json(selection_path)),
            "ALL_SYNTHESIS_MARKDOWN": read_all_markdown(synthesis_paths),
            "EVIDENCE_MATRIX_MARKDOWN": read_text(matrix_path),
        },
    )
    prompt_path = DRAFTS_DIR / "review_outline.prompt.md"
    raw_path = DRAFTS_DIR / "review_outline.raw_response.md"
    write_text(prompt_path, prompt)
    print("Generating review outline")
    content, meta = chat_completion(
        prompt,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    write_text(raw_path, content)
    write_text(outline_path, content)
    log_event(
        "generate_outline",
        {"status": "ok", "elapsed_seconds": meta.get("_elapsed_seconds"), "output": str(outline_path)},
    )
    print(f"Wrote {outline_path}")


if __name__ == "__main__":
    main()

