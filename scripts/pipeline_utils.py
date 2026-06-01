from __future__ import annotations

import csv
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(os.getenv("LIT_REVIEW_PROJECT_DIR", str(ROOT))).expanduser().resolve()
PAPERS_DIR = PROJECT_ROOT / "papers_md"
CONFIG_DIR = PROJECT_ROOT / "project_config"
PROMPTS_DIR = CONFIG_DIR / "prompts"
HUMAN_OVERRIDES_PATH = CONFIG_DIR / "human_overrides.json"
REVIEW_DIMENSIONS_PATH = CONFIG_DIR / "review_dimensions.json"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
CARDS_DIR = OUTPUTS_DIR / "literature_cards"
SCREENING_DIR = OUTPUTS_DIR / "screening"
SYNTHESIS_DIR = OUTPUTS_DIR / "synthesis"
EVIDENCE_DIR = OUTPUTS_DIR / "evidence_index"
DRAFTS_DIR = OUTPUTS_DIR / "drafts"
SECTIONS_DIR = DRAFTS_DIR / "sections"
LOGS_DIR = OUTPUTS_DIR / "logs"


def ensure_dirs() -> None:
    for path in [
        PAPERS_DIR,
        PROMPTS_DIR,
        CARDS_DIR,
        SCREENING_DIR,
        SYNTHESIS_DIR,
        EVIDENCE_DIR,
        DRAFTS_DIR,
        SECTIONS_DIR,
        LOGS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def slugify(value: str, fallback: str = "item") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or fallback


def paper_id_from_path(path: Path) -> str:
    return slugify(path.stem, fallback="paper")


def list_paper_files() -> list[Path]:
    return sorted(path for path in PAPERS_DIR.rglob("*.md") if path.is_file())


def load_review_brief() -> str:
    path = CONFIG_DIR / "review_brief.md"
    if not path.exists():
        raise FileNotFoundError(f"Missing review brief: {path}")
    review_brief = read_text(path)
    dimensions_path = CONFIG_DIR / "review_dimensions.json"
    if dimensions_path.exists():
        try:
            data = read_json(dimensions_path)
            selected = data.get("selected_dimensions", []) if isinstance(data, dict) else []
            dimensions = [str(item).strip() for item in selected if str(item).strip()]
            if dimensions:
                review_brief += "\n\n# 本项目启用的综述维度\n\n" + "、".join(dimensions) + "\n"
        except Exception:
            pass
    return review_brief


DEFAULT_REVIEW_DIMENSIONS = ["研究方法", "研究发现", "理论视角", "研究情境", "研究缺口"]


def load_review_dimensions() -> list[str]:
    if not REVIEW_DIMENSIONS_PATH.exists():
        return DEFAULT_REVIEW_DIMENSIONS
    try:
        data = read_json(REVIEW_DIMENSIONS_PATH)
    except Exception:
        return DEFAULT_REVIEW_DIMENSIONS
    selected = data.get("selected_dimensions") if isinstance(data, dict) else None
    if not isinstance(selected, list):
        return DEFAULT_REVIEW_DIMENSIONS
    dimensions = [str(item).strip() for item in selected if str(item).strip()]
    return dimensions or DEFAULT_REVIEW_DIMENSIONS


def review_dimensions_text() -> str:
    return "、".join(load_review_dimensions())


def default_human_overrides() -> dict[str, Any]:
    return {
        "card_review_notes": {},
        "core_selection": {
            "promote_to_core": [],
            "move_to_supporting": [],
            "move_to_peripheral": [],
        },
        "synthesis_notes": {},
        "outline_notes": "",
        "section_notes": {},
    }


def load_human_overrides() -> dict[str, Any]:
    if not HUMAN_OVERRIDES_PATH.exists():
        return default_human_overrides()
    try:
        data = read_json(HUMAN_OVERRIDES_PATH)
    except Exception:
        return default_human_overrides()
    if not isinstance(data, dict):
        return default_human_overrides()
    defaults = default_human_overrides()
    for key, value in defaults.items():
        data.setdefault(key, value)
    return data


def human_note_for_dimension(dimension: str) -> str:
    notes = load_human_overrides().get("synthesis_notes", {})
    if isinstance(notes, dict):
        return str(notes.get(dimension, "")).strip()
    return ""


def human_note_for_section(section_title: str) -> str:
    notes = load_human_overrides().get("section_notes", {})
    if not isinstance(notes, dict):
        return ""
    exact = str(notes.get(section_title, "")).strip()
    if exact:
        return exact
    for key, value in notes.items():
        if key.startswith("_"):
            continue
        if key and (key in section_title or section_title in key):
            return str(value).strip()
    return ""


def outline_human_notes() -> str:
    return str(load_human_overrides().get("outline_notes", "")).strip()


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing prompt template: {path}")
    return read_text(path)


def render_template(template: str, values: dict[str, Any]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def load_dotenv(path: Path | None = None) -> None:
    env_paths = [path] if path else [PROJECT_ROOT / ".env", ROOT / ".env"]
    for env_path in env_paths:
        if not env_path or not env_path.exists():
            continue
        for raw_line in read_text(env_path).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def completion_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def chat_completion(
    prompt: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[str, dict[str, Any]]:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LIT_REVIEW_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY. Copy .env.example to .env and fill it in.")

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    selected_model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    selected_temperature = (
        temperature
        if temperature is not None
        else float(os.getenv("DEEPSEEK_TEMPERATURE", "0.2"))
    )
    timeout = int(os.getenv("DEEPSEEK_TIMEOUT", "180"))

    payload: dict[str, Any] = {
        "model": selected_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": selected_temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        completion_url(base_url),
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    started = time.time()
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"API request failed: {exc}") from exc

    elapsed = time.time() - started
    response_data["_elapsed_seconds"] = elapsed
    content = response_data["choices"][0]["message"]["content"]
    return content, response_data


def extract_json_object(text: str) -> Any:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
    if fence:
        stripped = fence.group(1).strip()
    if not stripped.startswith("{"):
        first = stripped.find("{")
        last = stripped.rfind("}")
        if first != -1 and last != -1 and last > first:
            stripped = stripped[first : last + 1]
    return json.loads(stripped)


def log_event(log_name: str, event: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    event = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), **event}
    with (LOGS_DIR / f"{log_name}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def get_in(data: dict[str, Any], path: str, default: Any = "") -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def author_year(card: dict[str, Any]) -> str:
    bib = card.get("bibliographic_info", {})
    authors = as_list(bib.get("authors"))
    first_author = str(authors[0]) if authors else "Unknown"
    year = bib.get("year") or "n.d."
    return f"{first_author} ({year})"


def compact_card(card: dict[str, Any]) -> dict[str, Any]:
    findings = as_list(card.get("main_findings"))[:8]
    compact = {
        "paper_id": card.get("paper_id", ""),
        "author_year": author_year(card),
        "bibliographic_info": card.get("bibliographic_info", {}),
        "research_problem": card.get("research_problem", {}),
        "theoretical_perspective": card.get("theoretical_perspective", {}),
        "methodology": card.get("methodology", {}),
        "main_findings": findings,
        "key_concepts": as_list(card.get("key_concepts"))[:8],
        "contribution_to_review": card.get("contribution_to_review", {}),
        "limitations_and_future_research": card.get("limitations_and_future_research", {}),
        "screening_scores": card.get("screening_scores", {}),
        "uncertainties": card.get("uncertainties", []),
        "one_sentence_summary": card.get("one_sentence_summary", ""),
    }
    review_notes = load_human_overrides().get("card_review_notes", {})
    paper_id = str(card.get("paper_id", ""))
    if isinstance(review_notes, dict) and paper_id in review_notes:
        compact["human_review_note"] = review_notes[paper_id]
    return compact


def load_cards(compact: bool = False) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for path in sorted(CARDS_DIR.glob("*.card.json")):
        card = read_json(path)
        cards.append(compact_card(card) if compact else card)
    return cards


def card_by_id(compact: bool = False) -> dict[str, dict[str, Any]]:
    return {str(card.get("paper_id")): card for card in load_cards(compact=compact)}


def md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("|", "\\|")
    return re.sub(r"\s+", " ", text).strip()


def brief_table(cards: list[dict[str, Any]]) -> str:
    rows = [
        "| paper_id | author_year | title | method | fit | overall_score | one_sentence_summary |",
        "|---|---|---|---|---|---|---|",
    ]
    for card in cards:
        scores = card.get("screening_scores", {})
        rows.append(
            "| "
            + " | ".join(
                [
                    md_escape(card.get("paper_id", "")),
                    md_escape(card.get("author_year") or author_year(card)),
                    md_escape(get_in(card, "bibliographic_info.title")),
                    md_escape(get_in(card, "methodology.method_type")),
                    md_escape(get_in(card, "research_problem.fit_to_review_topic")),
                    md_escape(scores.get("overall_core_candidate_1_to_5", "")),
                    md_escape(card.get("one_sentence_summary", "")),
                ]
            )
            + " |"
        )
    return "\n".join(rows)


def card_to_markdown(card: dict[str, Any]) -> str:
    lines = [
        f"# {card.get('paper_id', 'unknown')}",
        "",
        f"- Author/year: {author_year(card)}",
        f"- Title: {get_in(card, 'bibliographic_info.title')}",
        f"- Source: {get_in(card, 'bibliographic_info.journal_or_source')}",
        f"- DOI/URL: {get_in(card, 'bibliographic_info.doi_or_url')}",
        f"- Fit: {get_in(card, 'research_problem.fit_to_review_topic')}",
        "",
        "## One-Sentence Summary",
        "",
        str(card.get("one_sentence_summary", "")),
        "",
        "## Research Problem",
        "",
        str(get_in(card, "research_problem.summary")),
        "",
        "## Theoretical Perspective",
        "",
        str(get_in(card, "theoretical_perspective.summary")),
        "",
        "## Methodology",
        "",
        f"- Type: {get_in(card, 'methodology.method_type')}",
        f"- Specific methods: {', '.join(map(str, as_list(get_in(card, 'methodology.specific_methods', []))))}",
        f"- Data sources: {', '.join(map(str, as_list(get_in(card, 'methodology.data_sources', []))))}",
        f"- Sample/cases: {get_in(card, 'methodology.sample_or_cases')}",
        f"- Context: {get_in(card, 'methodology.research_context')}",
        "",
        "## Main Findings",
        "",
    ]
    for idx, item in enumerate(as_list(card.get("main_findings")), start=1):
        if isinstance(item, dict):
            lines.append(f"{idx}. {item.get('finding', '')}")
            if item.get("mechanism_or_explanation"):
                lines.append(f"   - Mechanism: {item.get('mechanism_or_explanation')}")
            if item.get("boundary_conditions"):
                lines.append(f"   - Boundary conditions: {item.get('boundary_conditions')}")
            if item.get("evidence_quote"):
                lines.append(f"   - Evidence: {item.get('evidence_quote')}")
        else:
            lines.append(f"{idx}. {item}")
    lines.extend(["", "## Contribution To Review", ""])
    contribution = card.get("contribution_to_review", {})
    if isinstance(contribution, dict):
        lines.append(f"- Sections: {', '.join(map(str, as_list(contribution.get('can_support_sections'))))}")
        lines.append(f"- Unique value: {contribution.get('unique_value', '')}")
        lines.append(f"- Possible use: {contribution.get('possible_use_in_review', '')}")
    lines.extend(["", "## Uncertainties", ""])
    for item in as_list(card.get("uncertainties")):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def markdown_table_to_csv(markdown: str, csv_path: Path) -> bool:
    table_lines = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return False

    rows: list[list[str]] = []
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        rows.append(cells)

    if not rows:
        return False

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerows(rows)
    return True


def extract_outline_sections(outline_markdown: str) -> list[dict[str, str]]:
    lines = outline_markdown.splitlines()
    sections: list[dict[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if current_title:
            sections.append(
                {
                    "title": current_title.strip(),
                    "brief": "\n".join(current_lines).strip() or current_title.strip(),
                }
            )
        current_title = None
        current_lines = []

    for line in lines:
        if line.startswith("### "):
            flush()
            current_title = line[4:].strip()
            current_lines = [line]
        elif current_title:
            if line.startswith("## ") and not line.startswith("### "):
                flush()
            else:
                current_lines.append(line)
    flush()
    return sections


def read_all_markdown(paths: list[Path]) -> str:
    parts = []
    for path in paths:
        parts.append(f"\n\n<!-- {path.name} -->\n\n{read_text(path)}")
    return "\n".join(parts).strip()
