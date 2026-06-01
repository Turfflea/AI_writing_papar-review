#!/usr/bin/env python3
from __future__ import annotations

import argparse

from pipeline_utils import (
    SCREENING_DIR,
    SYNTHESIS_DIR,
    card_by_id,
    chat_completion,
    ensure_dirs,
    json_dumps,
    load_cards,
    load_prompt,
    load_review_brief,
    log_event,
    read_json,
    render_template,
    write_text,
)


DIMENSION_INSTRUCTIONS = {
    "研究方法": """请重点综合：

1. 文献使用了哪些研究方法。
2. 定性、定量、混合、理论、综述类研究如何分布。
3. 不同方法适合回答什么问题。
4. 不同方法产生了什么类型的发现。
5. 方法是否随时间发生变化。
6. 哪些方法证据强，哪些方法存在局限。
7. 未来研究在方法上还有哪些改进空间。""",
    "研究发现": """请重点综合：

1. 文献关于员工算法管理的主要发现。
2. 哪些发现形成共识。
3. 哪些发现存在冲突或边界条件。
4. 不同组织情境、职业群体、平台类型下发现是否不同。
5. 研究发现背后的机制解释是什么。
6. 哪些发现受到研究方法限制。
7. 哪些发现可以构成综述正文的核心论点。""",
    "理论视角": """请重点综合：

1. 文献使用了哪些理论视角和核心概念。
2. 不同理论如何解释员工算法管理。
3. 理论之间是互补、竞争还是各自解释不同层面。
4. 哪些理论被反复使用，哪些理论较新或较少使用。
5. 理论视角如何影响研究问题、方法和发现。
6. 现有理论解释还有哪些不足。""",
    "研究情境": """请重点综合：

1. 文献覆盖了哪些组织情境、职业群体、国家地区、行业和平台类型。
2. 不同情境下员工算法管理的表现是否不同。
3. 哪些情境被反复研究，哪些情境明显不足。
4. 情境差异如何影响研究方法、研究发现和理论解释。
5. 哪些情境可以构成未来研究的重要方向。""",
    "研究缺口": """请重点综合：

1. 文献作者自己提出的局限和未来研究方向。
2. 跨文献比较后暴露出的研究空白。
3. 哪些对象、情境、国家、职业、平台或组织类型研究不足。
4. 哪些方法或数据来源不足。
5. 哪些理论解释不足。
6. 哪些重要问题存在证据冲突或证据薄弱。
7. 可以如何转化为综述最后的未来研究议程。""",
}

DIMENSION_SLUGS = {
    "研究方法": "methods",
    "研究发现": "findings",
    "理论视角": "theory",
    "研究情境": "contexts",
    "研究缺口": "research_gaps",
}


def selected_ids(selection: dict, key: str) -> list[str]:
    return [str(item.get("paper_id", "")) for item in selection.get(key, []) if item.get("paper_id")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize literature cards across dimensions.")
    parser.add_argument("--dimension", action="append", help="Run one or more dimensions. Default runs all.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--compact", action="store_true", help="Use compact cards to reduce context size.")
    parser.add_argument(
        "--use-all-if-no-selection",
        action="store_true",
        help="Use all cards as core cards if final_core_selection.json is missing.",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    args = parser.parse_args()

    ensure_dirs()
    review_brief = load_review_brief()
    template = load_prompt("04_dimension_synthesis.md")
    dimensions = args.dimension or list(DIMENSION_INSTRUCTIONS.keys())
    cards_by_id = card_by_id(compact=args.compact)

    if not cards_by_id:
        print("No literature cards found. Run scripts/02_extract_cards.py first.")
        return

    selection_path = SCREENING_DIR / "final_core_selection.json"
    if selection_path.exists():
        selection = read_json(selection_path)
        core_ids = selected_ids(selection, "final_core_papers")
        supporting_ids = selected_ids(selection, "supporting_papers")
    elif args.use_all_if_no_selection:
        print("No final selection found. Using all cards as core cards.")
        core_ids = list(cards_by_id.keys())
        supporting_ids = []
    else:
        print("Missing outputs/screening/final_core_selection.json. Run scripts/04_select_core_papers.py first.")
        return

    core_cards = [cards_by_id[paper_id] for paper_id in core_ids if paper_id in cards_by_id]
    supporting_cards = [cards_by_id[paper_id] for paper_id in supporting_ids if paper_id in cards_by_id]
    if not core_cards:
        print("No core cards matched the final selection.")
        return

    for dimension in dimensions:
        slug = DIMENSION_SLUGS.get(dimension, dimension)
        out_path = SYNTHESIS_DIR / f"{slug}_synthesis.md"
        prompt_path = SYNTHESIS_DIR / f"{slug}_synthesis.prompt.md"
        raw_path = SYNTHESIS_DIR / f"{slug}_synthesis.raw_response.md"
        if out_path.exists() and not args.force:
            print(f"Skip existing synthesis: {out_path}")
            continue

        instruction = DIMENSION_INSTRUCTIONS.get(
            dimension,
            "请围绕该维度进行跨文献主题化综合，保留支持文献 paper_id 和证据不足提示。",
        )
        prompt = render_template(
            template,
            {
                "REVIEW_BRIEF": review_brief,
                "DIMENSION": dimension,
                "DIMENSION_INSTRUCTION": instruction,
                "CORE_LITERATURE_CARDS_JSON": json_dumps(core_cards),
                "SUPPORTING_LITERATURE_CARDS_JSON": json_dumps(supporting_cards),
            },
        )
        write_text(prompt_path, prompt)
        print(f"Synthesizing dimension: {dimension}")
        content, meta = chat_completion(
            prompt,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        write_text(raw_path, content)
        write_text(out_path, content)
        log_event(
            "synthesize_dimensions",
            {
                "dimension": dimension,
                "status": "ok",
                "elapsed_seconds": meta.get("_elapsed_seconds"),
                "output": str(out_path),
            },
        )
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

