#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from pipeline_utils import (
    CARDS_DIR,
    card_to_markdown,
    chat_completion,
    ensure_dirs,
    extract_json_object,
    load_prompt,
    load_review_brief,
    log_event,
    paper_id_from_path,
    read_text,
    render_template,
    write_json,
    write_text,
)


def maybe_truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return (
        head
        + "\n\n[TRUNCATED_FOR_CONTEXT: middle part omitted by script setting]\n\n"
        + tail
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract one structured literature card per paper.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N papers.")
    parser.add_argument("--paper-id", default="", help="Only process one paper_id.")
    parser.add_argument("--force", action="store_true", help="Regenerate existing cards.")
    parser.add_argument("--dry-run", action="store_true", help="Render prompts without calling the API.")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop at the first failed paper.")
    parser.add_argument("--model", default=None, help="Override DEEPSEEK_MODEL.")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument(
        "--max-chars",
        type=int,
        default=int(os.getenv("PAPER_MAX_CHARS", "0")),
        help="Optionally truncate very long papers. Default 0 means no truncation.",
    )
    args = parser.parse_args()

    ensure_dirs()
    review_brief = load_review_brief()
    template = load_prompt("01_extract_literature_card.md")

    from pipeline_utils import list_paper_files

    papers = list_paper_files()
    if args.paper_id:
        papers = [path for path in papers if paper_id_from_path(path) == args.paper_id]
    if args.limit > 0:
        papers = papers[: args.limit]

    if not papers:
        print("No Markdown papers found in papers_md/.")
        return

    for index, path in enumerate(papers, start=1):
        paper_id = paper_id_from_path(path)
        json_path = CARDS_DIR / f"{paper_id}.card.json"
        md_path = CARDS_DIR / f"{paper_id}.card.md"
        raw_path = CARDS_DIR / f"{paper_id}.raw_response.txt"
        prompt_path = CARDS_DIR / f"{paper_id}.prompt.md"

        if json_path.exists() and not args.force and not args.dry_run:
            print(f"[{index}/{len(papers)}] Skip existing card: {paper_id}")
            continue

        paper_markdown = maybe_truncate(read_text(path), args.max_chars)
        prompt = render_template(
            template,
            {
                "REVIEW_BRIEF": review_brief,
                "PAPER_MARKDOWN": paper_markdown,
                "PAPER_ID": paper_id,
            },
        )

        if args.dry_run:
            write_text(prompt_path, prompt)
            print(f"[{index}/{len(papers)}] Wrote dry-run prompt: {prompt_path}")
            continue

        print(f"[{index}/{len(papers)}] Extracting card: {paper_id}")
        try:
            content, meta = chat_completion(
                prompt,
                model=args.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
            write_text(raw_path, content)
            card = extract_json_object(content)
            if isinstance(card, dict):
                card["paper_id"] = paper_id
            else:
                raise ValueError("Model response JSON is not an object.")
            write_json(json_path, card)
            write_text(md_path, card_to_markdown(card))
            log_event(
                "extract_cards",
                {
                    "paper_id": paper_id,
                    "status": "ok",
                    "elapsed_seconds": meta.get("_elapsed_seconds"),
                    "output": str(json_path),
                },
            )
        except Exception as exc:
            log_event("extract_cards", {"paper_id": paper_id, "status": "error", "error": str(exc)})
            print(f"ERROR extracting {paper_id}: {exc}")
            if args.stop_on_error:
                raise


if __name__ == "__main__":
    main()

