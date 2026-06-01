#!/usr/bin/env python3
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from pipeline_utils import ROOT, read_json, read_text, slugify, write_text


WEB_DIR = ROOT / "web"
PROJECTS_DIR = ROOT / "projects"
ACTIVE_PROJECT_PATH = PROJECTS_DIR / ".active_project"
TEMPLATE_CONFIG_DIR = ROOT / "project_config"

STEP_DEFS = [
    {
        "id": "inventory",
        "title": "1. 文献清单",
        "script": "01_inventory.py",
        "description": "扫描项目中的 Markdown 文献，生成文献清单、元数据猜测和待人工检查项。",
        "outputs": ["outputs/paper_inventory.csv", "outputs/metadata_needs_review.csv"],
        "prompt_files": [],
    },
    {
        "id": "cards",
        "title": "2. 单篇文献卡片",
        "script": "02_extract_cards.py",
        "description": "逐篇调用 AI，将每篇文献压缩成结构化卡片。这一步通常最慢，适合用“查看进度”跟踪。",
        "outputs": ["outputs/literature_cards"],
        "prompt_files": ["project_config/prompts/01_extract_literature_card.md"],
    },
    {
        "id": "quality",
        "title": "3. 质量检查",
        "script": "03_quality_check.py",
        "description": "检查卡片是否缺字段、缺证据、分数异常或过短，帮助你决定是否重跑或人工修卡片。",
        "outputs": ["outputs/quality_report.json", "outputs/quality_issues.md"],
        "prompt_files": [],
    },
    {
        "id": "screening",
        "title": "4. 核心文献筛选",
        "script": "04_select_core_papers.py",
        "description": "先把文献卡片分批交给 AI 初筛，再做全局复筛。你可以设定每批多少篇，并人工改核心/辅助/边缘分类。",
        "outputs": ["outputs/screening/final_core_selection.json", "outputs/screening/final_core_selection.md"],
        "prompt_files": [
            "project_config/prompts/02_batch_core_screening.md",
            "project_config/prompts/03_global_core_selection.md",
        ],
    },
    {
        "id": "synthesis",
        "title": "5. 跨文献综合",
        "script": "05_synthesize_dimensions.py",
        "description": "围绕研究方法、研究发现、理论视角、研究情境和研究缺口做跨文献综合。",
        "outputs": ["outputs/synthesis"],
        "prompt_files": ["project_config/prompts/04_dimension_synthesis.md"],
    },
    {
        "id": "evidence",
        "title": "6. 证据矩阵",
        "script": "05_evidence_matrix.py",
        "description": "准备证据矩阵 Agent 工作区，写入真实输入材料和 prompt.md，并打开终端让你选择 Claude Code 或 Codex 完成输出。",
        "outputs": ["outputs/evidence_index"],
        "required_outputs": ["outputs/evidence_index/evidence_matrix.md"],
        "prompt_files": ["project_config/prompts/05_evidence_matrix.md"],
        "agent_step": True,
    },
    {
        "id": "outline",
        "title": "7. 综述大纲",
        "script": "06_generate_outline.py",
        "description": "准备综述大纲 Agent 工作区，使用筛选结果、综合文件和证据矩阵生成 prompt.md，并打开终端继续写作。",
        "outputs": ["outputs/outline"],
        "required_outputs": ["outputs/outline/review_outline.md"],
        "prompt_files": ["project_config/prompts/06_outline_generation.md"],
        "agent_step": True,
    },
    {
        "id": "draft",
        "title": "8. 逐章写作",
        "script": "07_write_review.py",
        "description": "准备逐章写作 Agent 工作区，放入大纲、证据矩阵、核心卡片和 prompt.md，并打开终端让 Agent 写出正文草稿。",
        "outputs": ["outputs/drafts"],
        "required_outputs": ["outputs/drafts/final_review.md"],
        "prompt_files": ["project_config/prompts/07_section_writing.md"],
        "agent_step": True,
    },
]

PROMPT_DESCRIPTIONS = {
    "project_config/prompts/01_extract_literature_card.md": {
        "title": "单篇文献卡片提取模板",
        "description": "控制 AI 如何阅读一篇 Markdown 文献，并输出研究方法、研究发现、理论、证据和相关度等结构化字段。",
    },
    "project_config/prompts/02_batch_core_screening.md": {
        "title": "分批核心文献初筛模板",
        "description": "控制 AI 如何从一批文献卡片中初步区分核心、辅助和边缘文献。",
    },
    "project_config/prompts/03_global_core_selection.md": {
        "title": "全局核心文献复筛模板",
        "description": "控制 AI 如何合并各批初筛结果，生成最终核心文献、辅助文献和边缘文献名单。",
    },
    "project_config/prompts/04_dimension_synthesis.md": {
        "title": "跨文献综合模板",
        "description": "控制 AI 如何围绕研究方法、研究发现、理论视角、研究情境或研究缺口做跨文献归纳。",
    },
    "project_config/prompts/05_evidence_matrix.md": {
        "title": "证据矩阵模板",
        "description": "控制第 6 步生成的 Agent prompt.md 如何把文献卡片和综合结论整理为可追溯证据表。",
    },
    "project_config/prompts/06_outline_generation.md": {
        "title": "综述大纲模板",
        "description": "控制第 7 步生成的 Agent prompt.md 如何把筛选、综合和证据矩阵转化为正式综述大纲。",
    },
    "project_config/prompts/07_section_writing.md": {
        "title": "逐章正文写作模板",
        "description": "控制第 8 步生成的 Agent prompt.md 如何根据章节任务、证据矩阵和核心文献卡片写出正式中文综述正文。",
    },
}

RUNNABLE_STEPS = {step["id"]: step for step in STEP_DEFS}

job_lock = threading.Lock()
current_job: dict[str, Any] = {
    "running": False,
    "step_id": "",
    "project_id": "",
    "command": [],
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "log": "",
}


def json_response(handler: BaseHTTPRequestHandler, data: Any, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8")) if raw else {}


def rel_to_project(path: Path, project_dir: Path | None = None) -> str:
    base = project_dir or active_project_dir()
    return str(path.relative_to(base))


def project_id_from_name(name: str) -> str:
    return slugify(name.strip(), fallback="review_project")


def project_dir(project_id: str) -> Path:
    return (PROJECTS_DIR / project_id).resolve()


def project_meta_path(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def default_review_brief(name: str) -> str:
    return f"""# 综述主题

{name}

# 综述目标与详细介绍

请在这里写清楚本次综述要回答的问题、研究对象、希望重点比较的维度，以及不希望纳入的文献范围。

# 核心综述问题

1. 这个主题中的核心概念如何被定义和操作化？
2. 现有研究采用了哪些研究方法？
3. 主要研究发现是什么？
4. 不同研究方法与研究发现之间有什么关系？
5. 现有研究有哪些共识、分歧、边界条件和研究缺口？

# 重点提取维度

- 研究对象与组织情境
- 理论视角
- 研究方法
- 数据来源
- 样本与案例
- 关键概念和变量
- 主要研究发现
- 机制解释
- 局限与未来研究
- 与本综述主题的相关度
"""


def ensure_project(project_id: str, display_name: str | None = None) -> Path:
    base = project_dir(project_id)
    for path in [
        base / "papers_md",
        base / "project_config" / "prompts",
        base / "outputs" / "literature_cards",
        base / "outputs" / "screening",
        base / "outputs" / "synthesis",
        base / "outputs" / "evidence_index",
        base / "outputs" / "outline",
        base / "outputs" / "drafts" / "sections",
        base / "outputs" / "logs",
    ]:
        path.mkdir(parents=True, exist_ok=True)

    config_dir = base / "project_config"
    prompts_dir = config_dir / "prompts"
    if not (config_dir / "review_brief.md").exists():
        write_text(config_dir / "review_brief.md", default_review_brief(display_name or project_id))
    for name in ["extraction_schema.yaml", "human_overrides.json", "review_dimensions.json"]:
        src = TEMPLATE_CONFIG_DIR / name
        dst = config_dir / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
    for src in sorted((TEMPLATE_CONFIG_DIR / "prompts").glob("*.md")):
        dst = prompts_dir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
    if not (base / ".env").exists() and (ROOT / ".env.example").exists():
        shutil.copy2(ROOT / ".env.example", base / ".env")
    meta_path = project_meta_path(project_id)
    if not meta_path.exists():
        write_text(
            meta_path,
            json.dumps(
                {
                    "id": project_id,
                    "name": display_name or project_id,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return base


def list_projects() -> list[dict[str, Any]]:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects = []
    for path in sorted(PROJECTS_DIR.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        meta = {"id": path.name, "name": path.name}
        if (path / "project.json").exists():
            try:
                meta.update(read_json(path / "project.json"))
            except Exception:
                pass
        projects.append({**meta, "path": str(path)})
    return projects


def set_active_project(project_id: str) -> None:
    ensure_project(project_id)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    write_text(ACTIVE_PROJECT_PATH, project_id)


def active_project_id() -> str:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    if ACTIVE_PROJECT_PATH.exists():
        candidate = read_text(ACTIVE_PROJECT_PATH).strip()
        if candidate and project_dir(candidate).exists():
            return candidate
    projects = list_projects()
    if projects:
        set_active_project(projects[0]["id"])
        return projects[0]["id"]
    default_id = "default_project"
    ensure_project(default_id, "默认综述项目")
    set_active_project(default_id)
    return default_id


def active_project_dir() -> Path:
    return ensure_project(active_project_id())


def active_project_meta() -> dict[str, Any]:
    project_id = active_project_id()
    meta = {"id": project_id, "name": project_id}
    path = project_meta_path(project_id)
    if path.exists():
        try:
            meta.update(read_json(path))
        except Exception:
            pass
    meta["path"] = str(project_dir(project_id))
    return meta


def project_path(relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("Missing path.")
    base = active_project_dir()
    target = (base / unquote(relative_path)).resolve()
    if target == base or base in target.parents:
        return target
    raise ValueError("Path is outside the active project.")


def output_path_done(project_root: Path, relative_path: str) -> bool:
    path = project_root / relative_path
    if path.is_dir():
        return any(child.is_file() and child.name != ".gitkeep" for child in path.rglob("*"))
    return path.exists() and path.stat().st_size > 0


def step_status(step: dict[str, Any], project_root: Path) -> str:
    required_outputs = step.get("required_outputs") or step["outputs"]
    visible_outputs = list(dict.fromkeys([*step["outputs"], *required_outputs]))
    if all(output_path_done(project_root, path) for path in required_outputs):
        return "done"
    if any(output_path_done(project_root, path) for path in visible_outputs):
        return "partial"
    return "pending"


def project_papers(project_root: Path) -> list[Path]:
    papers_dir = project_root / "papers_md"
    return sorted(path for path in papers_dir.rglob("*.md") if path.is_file())


def card_progress(project_root: Path) -> dict[str, Any]:
    papers = project_papers(project_root)
    cards_dir = project_root / "outputs" / "literature_cards"
    inventory_done = output_path_done(project_root, "outputs/paper_inventory.csv")
    errors: dict[str, str] = {}
    log_path = project_root / "outputs" / "logs" / "extract_cards.jsonl"
    if log_path.exists():
        for line in read_text(log_path).splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            if item.get("status") == "error" and item.get("paper_id"):
                errors[str(item["paper_id"])] = str(item.get("error", ""))

    rows = []
    seen: set[str] = set()
    for paper in papers:
        paper_id = slugify(paper.stem, fallback="paper")
        seen.add(paper_id)
        json_path = cards_dir / f"{paper_id}.card.json"
        raw_path = cards_dir / f"{paper_id}.raw_response.txt"
        prompt_path = cards_dir / f"{paper_id}.prompt.md"
        if json_path.exists():
            status = "success"
        elif paper_id in errors or raw_path.exists():
            status = "failed"
        elif prompt_path.exists():
            status = "submitted"
        else:
            status = "pending"
        rows.append(
            {
                "paper_id": paper_id,
                "display_name": paper.stem,
                "paper_file": rel_to_project(paper, project_root),
                "status": status,
                "library_status": "inventoried" if inventory_done else "imported",
                "card_path": rel_to_project(json_path, project_root) if json_path.exists() else "",
                "raw_response_path": rel_to_project(raw_path, project_root) if raw_path.exists() else "",
                "error": errors.get(paper_id, ""),
            }
        )

    for json_path in sorted(cards_dir.glob("*.card.json")):
        paper_id = json_path.name.removesuffix(".card.json")
        if paper_id not in seen:
            rows.append(
                {
                    "paper_id": paper_id,
                    "display_name": paper_id,
                    "paper_file": "",
                    "status": "success",
                    "library_status": "card_only",
                    "card_path": rel_to_project(json_path, project_root),
                    "raw_response_path": "",
                    "error": "",
                }
            )
    counts = {
        "total": len(rows),
        "success": sum(1 for row in rows if row["status"] == "success"),
        "failed": sum(1 for row in rows if row["status"] == "failed"),
        "pending": sum(1 for row in rows if row["status"] == "pending"),
        "submitted": sum(1 for row in rows if row["status"] == "submitted"),
    }
    return {"counts": counts, "papers": rows}


def selection_counts(project_root: Path) -> dict[str, int]:
    path = project_root / "outputs" / "screening" / "final_core_selection.json"
    if not path.exists():
        return {"core": 0, "supporting": 0, "peripheral": 0}
    try:
        data = read_json(path)
    except Exception:
        return {"core": 0, "supporting": 0, "peripheral": 0}
    return {
        "core": len(data.get("final_core_papers", [])),
        "supporting": len(data.get("supporting_papers", [])),
        "peripheral": len(data.get("peripheral_papers", [])),
    }


def screening_results(project_root: Path) -> dict[str, list[dict[str, Any]]]:
    path = project_root / "outputs" / "screening" / "final_core_selection.json"
    if not path.exists():
        return {"core": [], "supporting": [], "peripheral": []}
    try:
        data = read_json(path)
    except Exception:
        return {"core": [], "supporting": [], "peripheral": []}
    return {
        "core": data.get("final_core_papers", []),
        "supporting": data.get("supporting_papers", []),
        "peripheral": data.get("peripheral_papers", []),
    }


def parse_env_file(path: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    if not path.exists():
        return settings
    for line in read_text(path).splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.strip()] = value.strip().strip('"').strip("'")
    return settings


def env_settings(project_root: Path) -> dict[str, Any]:
    settings = {
        **parse_env_file(ROOT / ".env"),
        **parse_env_file(project_root / ".env"),
    }
    key = settings.get("DEEPSEEK_API_KEY", "")
    return {
        "has_api_key": bool(key and key != "your_api_key_here"),
        "api_key_preview": ("*" * max(0, len(key) - 4) + key[-4:]) if key and key != "your_api_key_here" else "",
        "base_url": settings.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": settings.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "temperature": settings.get("DEEPSEEK_TEMPERATURE", "0.2"),
        "timeout": settings.get("DEEPSEEK_TIMEOUT", "180"),
    }


def write_env_settings(project_root: Path, data: dict[str, Any]) -> None:
    env_path = project_root / ".env"
    existing = parse_env_file(env_path)
    mapping = {
        "api_key": "DEEPSEEK_API_KEY",
        "base_url": "DEEPSEEK_BASE_URL",
        "model": "DEEPSEEK_MODEL",
        "temperature": "DEEPSEEK_TEMPERATURE",
        "timeout": "DEEPSEEK_TIMEOUT",
    }
    for input_key, env_key in mapping.items():
        value = str(data.get(input_key, "")).strip()
        if value or env_key != "DEEPSEEK_API_KEY":
            existing[env_key] = value
    write_text(env_path, "\n".join(f"{key}={value}" for key, value in existing.items()) + "\n")


def review_dimensions(project_root: Path) -> dict[str, Any]:
    path = project_root / "project_config" / "review_dimensions.json"
    default = {
        "available_dimensions": ["研究方法", "研究发现", "理论视角", "研究情境", "研究缺口"],
        "selected_dimensions": ["研究方法", "研究发现", "理论视角", "研究情境", "研究缺口"],
    }
    if not path.exists():
        write_text(path, json.dumps(default, ensure_ascii=False, indent=2))
        return default
    try:
        data = read_json(path)
    except Exception:
        return default
    if not isinstance(data, dict):
        return default
    data.setdefault("available_dimensions", default["available_dimensions"])
    data.setdefault("selected_dimensions", default["selected_dimensions"])
    return data


def write_review_dimensions(project_root: Path, selected: list[str]) -> dict[str, Any]:
    current = review_dimensions(project_root)
    available = [str(item) for item in current.get("available_dimensions", [])]
    cleaned = [item for item in selected if item in available]
    if not cleaned:
        cleaned = ["研究方法"]
    current["selected_dimensions"] = cleaned
    write_text(project_root / "project_config" / "review_dimensions.json", json.dumps(current, ensure_ascii=False, indent=2))
    return current


def list_outputs_for_step(project_root: Path, step_id: str) -> list[dict[str, Any]]:
    step = RUNNABLE_STEPS.get(step_id)
    if not step:
        return []
    files: list[Path] = []
    for output in step["outputs"]:
        path = project_root / output
        if path.is_dir():
            files.extend(child for child in path.rglob("*") if child.is_file())
        elif path.exists():
            files.append(path)
    return [
        {
            "path": rel_to_project(path, project_root),
            "name": path.name,
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
        }
        for path in sorted(files)
    ]


def prompt_info_for_step(step: dict[str, Any], project_root: Path) -> list[dict[str, str]]:
    result = []
    for prompt_file in step.get("prompt_files", []):
        path = project_root / prompt_file
        meta = PROMPT_DESCRIPTIONS.get(prompt_file, {"title": path.name, "description": ""})
        result.append(
            {
                "path": prompt_file,
                "filename": path.name,
                "title": meta["title"],
                "description": meta["description"],
                "content": read_text(path) if path.exists() else "",
            }
        )
    return result


def state() -> dict[str, Any]:
    project_root = active_project_dir()
    progress = card_progress(project_root)
    steps = []
    for step in STEP_DEFS:
        steps.append(
            {
                **step,
                "status": step_status(step, project_root),
                "outputs": [
                    {"path": path, "exists": output_path_done(project_root, path)}
                    for path in step.get("required_outputs", step["outputs"])
                ],
                "prompt_info": prompt_info_for_step(step, project_root),
                "output_files": list_outputs_for_step(project_root, step["id"]),
            }
        )
    return {
        "active_project": active_project_meta(),
        "projects": list_projects(),
        "steps": steps,
        "counts": {
            "papers": len(project_papers(project_root)),
            "cards": progress["counts"]["success"],
            "synthesis_files": len(list((project_root / "outputs" / "synthesis").glob("*_synthesis.md"))),
            "section_drafts": len(list((project_root / "outputs" / "drafts" / "sections").glob("*.md"))),
            **selection_counts(project_root),
        },
        "settings": env_settings(project_root),
        "dimensions": review_dimensions(project_root),
        "screening_results": screening_results(project_root),
        "card_progress": progress,
        "job": current_job,
    }


def safe_file(relative_path: str) -> Path:
    target = project_path(relative_path)
    allowed_roots = [
        active_project_dir() / "papers_md",
        active_project_dir() / "project_config",
        active_project_dir() / "outputs",
        active_project_dir() / ".env",
    ]
    if any(target == root or (root.is_dir() and root in target.parents) for root in allowed_roots):
        return target
    raise ValueError("This file is not editable from the workbench.")


def run_job(step_id: str, args: list[str], project_id: str) -> None:
    global current_job
    step = RUNNABLE_STEPS[step_id]
    project_root = ensure_project(project_id)
    command = [sys.executable, str(ROOT / "scripts" / step["script"]), *args]
    env = {**os.environ, "LIT_REVIEW_PROJECT_DIR": str(project_root)}
    env.update(parse_env_file(project_root / ".env"))
    with job_lock:
        current_job = {
            "running": True,
            "step_id": step_id,
            "project_id": project_id,
            "command": command,
            "started_at": time.time(),
            "finished_at": None,
            "returncode": None,
            "log": "",
        }

    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert process.stdout is not None
    for line in process.stdout:
        with job_lock:
            current_job["log"] += line
    returncode = process.wait()
    with job_lock:
        current_job["running"] = False
        current_job["finished_at"] = time.time()
        current_job["returncode"] = returncode


def rollback_step(step_id: str, project_root: Path) -> list[str]:
    step_ids = [step["id"] for step in STEP_DEFS]
    if step_id not in step_ids:
        raise ValueError("Unknown step.")
    start = step_ids.index(step_id)
    removed: list[str] = []
    for step in STEP_DEFS[start:]:
        for output in step["outputs"]:
            path = project_root / output
            if path.is_dir():
                shutil.rmtree(path)
                path.mkdir(parents=True, exist_ok=True)
                removed.append(output)
            elif path.exists():
                path.unlink()
                removed.append(output)
    return removed


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/":
                self.serve_static(WEB_DIR / "index.html")
            elif path.startswith("/web/"):
                self.serve_static(WEB_DIR / path.removeprefix("/web/"))
            elif path == "/api/state":
                json_response(self, state())
            elif path == "/api/projects":
                json_response(self, {"active_project": active_project_meta(), "projects": list_projects()})
            elif path == "/api/job":
                json_response(self, current_job)
            elif path == "/api/card-progress":
                json_response(self, card_progress(active_project_dir()))
            elif path == "/api/step":
                step_id = query.get("step_id", [""])[0]
                step = RUNNABLE_STEPS.get(step_id)
                if not step:
                    json_response(self, {"error": "Unknown step."}, HTTPStatus.BAD_REQUEST)
                    return
                json_response(
                    self,
                    {
                        "step": step,
                        "prompt_info": prompt_info_for_step(step, active_project_dir()),
                        "output_files": list_outputs_for_step(active_project_dir(), step_id),
                    },
                )
            elif path == "/api/file":
                target = safe_file(query.get("path", [""])[0])
                if not target.exists():
                    json_response(self, {"error": "File does not exist."}, HTTPStatus.NOT_FOUND)
                elif target.is_dir():
                    json_response(self, {"error": "Path is a directory."}, HTTPStatus.BAD_REQUEST)
                else:
                    json_response(self, {"path": rel_to_project(target), "content": read_text(target)})
            elif path == "/api/list":
                kind = query.get("kind", ["outputs"])[0]
                json_response(self, {"files": list_named_files(active_project_dir(), kind)})
            elif path == "/api/settings":
                json_response(self, env_settings(active_project_dir()))
            elif path == "/api/dimensions":
                json_response(self, review_dimensions(active_project_dir()))
            else:
                json_response(self, {"error": "Not found."}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            data = read_body(self)
            if path == "/api/projects":
                action = str(data.get("action", "select"))
                if action == "create":
                    name = str(data.get("name", "")).strip() or "新综述项目"
                    project_id = project_id_from_name(name)
                    ensure_project(project_id, name)
                    set_active_project(project_id)
                elif action == "select":
                    project_id = str(data.get("project_id", "")).strip()
                    if not project_id:
                        raise ValueError("Missing project_id.")
                    set_active_project(project_id)
                else:
                    raise ValueError("Unknown project action.")
                json_response(self, {"ok": True, "active_project": active_project_meta(), "projects": list_projects()})
            elif path == "/api/file":
                target = safe_file(str(data.get("path", "")))
                write_text(target, str(data.get("content", "")))
                json_response(self, {"ok": True, "path": rel_to_project(target)})
            elif path == "/api/upload":
                filename = Path(str(data.get("filename", "paper.md"))).name
                if not filename.endswith(".md"):
                    filename += ".md"
                target = active_project_dir() / "papers_md" / filename
                write_text(target, str(data.get("content", "")))
                json_response(self, {"ok": True, "path": rel_to_project(target)})
            elif path == "/api/settings":
                write_env_settings(active_project_dir(), data)
                json_response(self, {"ok": True, "settings": env_settings(active_project_dir())})
            elif path == "/api/dimensions":
                selected = data.get("selected_dimensions", [])
                if not isinstance(selected, list):
                    selected = []
                dimensions = write_review_dimensions(active_project_dir(), [str(item) for item in selected])
                json_response(self, {"ok": True, "dimensions": dimensions})
            elif path == "/api/run":
                step_id = str(data.get("step_id", ""))
                if step_id not in RUNNABLE_STEPS:
                    json_response(self, {"error": "Unknown step."}, HTTPStatus.BAD_REQUEST)
                    return
                with job_lock:
                    if current_job.get("running"):
                        json_response(self, {"error": "A job is already running."}, HTTPStatus.CONFLICT)
                        return
                args = data.get("args", [])
                if not isinstance(args, list):
                    args = []
                project_id = active_project_id()
                thread = threading.Thread(target=run_job, args=(step_id, [str(arg) for arg in args], project_id), daemon=True)
                thread.start()
                json_response(self, {"ok": True})
            elif path == "/api/rollback":
                step_id = str(data.get("step_id", ""))
                removed = rollback_step(step_id, active_project_dir())
                json_response(self, {"ok": True, "removed": removed})
            elif path == "/api/delete":
                target = safe_file(str(data.get("path", "")))
                if target.exists() and target.is_file():
                    target.unlink()
                json_response(self, {"ok": True})
            else:
                json_response(self, {"error": "Not found."}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def serve_static(self, path: Path) -> None:
        target = path.resolve()
        if not target.exists() or not target.is_file() or WEB_DIR.resolve() not in target.parents:
            json_response(self, {"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def list_named_files(project_root: Path, kind: str) -> list[dict[str, Any]]:
    roots = {
        "papers": [project_root / "papers_md"],
        "cards": [project_root / "outputs" / "literature_cards"],
        "outputs": [project_root / "outputs"],
        "prompts": [project_root / "project_config" / "prompts"],
        "config": [project_root / "project_config"],
    }.get(kind, [project_root / "outputs"])
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(path for path in root.rglob("*") if path.is_file() and path.name != ".gitkeep")
    return [
        {
            "path": rel_to_project(path, project_root),
            "name": path.name,
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
        }
        for path in sorted(files)
    ]


def main() -> None:
    ensure_project(active_project_id())
    port = int(os.getenv("LIT_REVIEW_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Literature review workbench: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
