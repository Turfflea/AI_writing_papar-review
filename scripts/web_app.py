#!/usr/bin/env python3
from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from pipeline_utils import (
    CARDS_DIR,
    CONFIG_DIR,
    DRAFTS_DIR,
    EVIDENCE_DIR,
    HUMAN_OVERRIDES_PATH,
    OUTPUTS_DIR,
    PAPERS_DIR,
    PROMPTS_DIR,
    ROOT,
    SCREENING_DIR,
    SECTIONS_DIR,
    SYNTHESIS_DIR,
    ensure_dirs,
    list_paper_files,
    load_dotenv,
    read_json,
    read_text,
    write_text,
)


WEB_DIR = ROOT / "web"
ENV_PATH = ROOT / ".env"

STEP_DEFS = [
    {
        "id": "inventory",
        "title": "1. 文献清单",
        "script": "01_inventory.py",
        "description": "扫描 Markdown 文献，生成元数据、年份、DOI、OCR 风险和待检查清单。",
        "outputs": ["outputs/paper_inventory.csv", "outputs/metadata_needs_review.csv"],
    },
    {
        "id": "cards",
        "title": "2. 单篇文献卡片",
        "script": "02_extract_cards.py",
        "description": "每篇文献调用一次模型，提取方法、发现、理论、证据和相关度。",
        "outputs": ["outputs/literature_cards"],
    },
    {
        "id": "quality",
        "title": "3. 质量检查",
        "script": "03_quality_check.py",
        "description": "检查卡片缺字段、缺证据、分数异常和过短问题。",
        "outputs": ["outputs/quality_report.json", "outputs/quality_issues.md"],
    },
    {
        "id": "screening",
        "title": "4. 核心文献筛选",
        "script": "04_select_core_papers.py",
        "description": "分批筛选核心/辅助/边缘文献，并应用人工提升或降级规则。",
        "outputs": ["outputs/screening/final_core_selection.json", "outputs/screening/final_core_selection.md"],
    },
    {
        "id": "synthesis",
        "title": "5. 跨文献综合",
        "script": "05_synthesize_dimensions.py",
        "description": "按研究方法、研究发现、理论视角、研究情境和研究缺口生成综合概要。",
        "outputs": ["outputs/synthesis"],
    },
    {
        "id": "evidence",
        "title": "6. 证据矩阵",
        "script": "05_evidence_matrix.py",
        "description": "把文献卡片和综合结果整理为可追溯证据矩阵。",
        "outputs": ["outputs/evidence_index/evidence_matrix.md", "outputs/evidence_index/evidence_matrix.csv"],
    },
    {
        "id": "outline",
        "title": "7. 综述大纲",
        "script": "06_generate_outline.py",
        "description": "基于筛选、综合和证据矩阵生成问题化综述大纲。",
        "outputs": ["outputs/drafts/review_outline.md"],
    },
    {
        "id": "draft",
        "title": "8. 逐章写作",
        "script": "07_write_review.py",
        "description": "按大纲逐章生成正文，并合并为最终草稿。",
        "outputs": ["outputs/drafts/sections", "outputs/drafts/final_review.md"],
    },
]

RUNNABLE_STEPS = {step["id"]: step for step in STEP_DEFS}

EDITABLE_ROOTS = [
    PAPERS_DIR,
    CONFIG_DIR,
    OUTPUTS_DIR,
]
EDITABLE_FILES = {
    ROOT / ".env",
    ROOT / ".env.example",
    ROOT / "README.md",
}

job_lock = threading.Lock()
current_job: dict[str, Any] = {
    "running": False,
    "step_id": "",
    "command": [],
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "log": "",
}


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def json_response(handler: BaseHTTPRequestHandler, data: Any, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, text: str, status: int = 200, content_type: str = "text/plain") -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", f"{content_type}; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def safe_path(relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("Missing path.")
    candidate = (ROOT / unquote(relative_path)).resolve()
    if candidate in {path.resolve() for path in EDITABLE_FILES}:
        return candidate
    if any(candidate == root.resolve() or root.resolve() in candidate.parents for root in EDITABLE_ROOTS):
        return candidate
    raise ValueError("Path is outside editable project areas.")


def list_files(kind: str) -> list[dict[str, Any]]:
    roots = {
        "papers": [PAPERS_DIR],
        "cards": [CARDS_DIR],
        "prompts": [PROMPTS_DIR],
        "config": [CONFIG_DIR, ROOT],
        "outputs": [OUTPUTS_DIR],
    }.get(kind, [CONFIG_DIR, OUTPUTS_DIR, PAPERS_DIR])

    files: list[Path] = []
    for root in roots:
        if root == ROOT:
            files.extend(path for path in [ROOT / ".env", ROOT / ".env.example", ROOT / "README.md"] if path.exists())
            continue
        if root.exists():
            files.extend(path for path in root.rglob("*") if path.is_file() and path.name != ".gitkeep")

    unique = sorted({path.resolve() for path in files})
    return [
        {
            "path": rel(path),
            "name": path.name,
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
        }
        for path in unique
    ]


def path_done(path_text: str) -> bool:
    path = ROOT / path_text
    if path.is_dir():
        return any(child.is_file() and child.name != ".gitkeep" for child in path.rglob("*"))
    return path.exists() and path.stat().st_size > 0


def step_status(step: dict[str, Any]) -> str:
    outputs = step["outputs"]
    if all(path_done(path) for path in outputs):
        return "done"
    if any(path_done(path) for path in outputs):
        return "partial"
    return "pending"


def count_cards() -> int:
    return len(list(CARDS_DIR.glob("*.card.json")))


def selection_counts() -> dict[str, int]:
    path = SCREENING_DIR / "final_core_selection.json"
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


def env_settings() -> dict[str, Any]:
    load_dotenv()
    key = os.getenv("DEEPSEEK_API_KEY", "")
    return {
        "has_api_key": bool(key),
        "api_key_preview": ("*" * max(0, len(key) - 4) + key[-4:]) if key else "",
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "temperature": os.getenv("DEEPSEEK_TEMPERATURE", "0.2"),
        "timeout": os.getenv("DEEPSEEK_TIMEOUT", "180"),
    }


def write_env(settings: dict[str, Any]) -> None:
    existing: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in read_text(ENV_PATH).splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                existing[key.strip()] = value.strip()

    mapping = {
        "api_key": "DEEPSEEK_API_KEY",
        "base_url": "DEEPSEEK_BASE_URL",
        "model": "DEEPSEEK_MODEL",
        "temperature": "DEEPSEEK_TEMPERATURE",
        "timeout": "DEEPSEEK_TIMEOUT",
    }
    for input_key, env_key in mapping.items():
        value = str(settings.get(input_key, "")).strip()
        if value or env_key != "DEEPSEEK_API_KEY":
            existing[env_key] = value
            os.environ[env_key] = value

    lines = [f"{key}={value}" for key, value in existing.items()]
    write_text(ENV_PATH, "\n".join(lines) + "\n")


def read_paper_ids() -> list[str]:
    ids: set[str] = set()
    for path in CARDS_DIR.glob("*.card.json"):
        ids.add(path.name.removesuffix(".card.json"))
    for path in list_paper_files():
        ids.add(path.stem)
    return sorted(ids)


def state() -> dict[str, Any]:
    steps = []
    for step in STEP_DEFS:
        outputs = [
            {
                "path": output,
                "exists": path_done(output),
            }
            for output in step["outputs"]
        ]
        steps.append({**step, "status": step_status(step), "outputs": outputs})
    return {
        "steps": steps,
        "counts": {
            "papers": len(list_paper_files()),
            "cards": count_cards(),
            "synthesis_files": len(list(SYNTHESIS_DIR.glob("*_synthesis.md"))),
            "section_drafts": len(list(SECTIONS_DIR.glob("*.md"))),
            **selection_counts(),
        },
        "settings": env_settings(),
        "paper_ids": read_paper_ids(),
        "job": current_job,
    }


def run_job(step_id: str, args: list[str]) -> None:
    global current_job
    step = RUNNABLE_STEPS[step_id]
    command = [sys.executable, str(ROOT / "scripts" / step["script"]), *args]
    with job_lock:
        current_job = {
            "running": True,
            "step_id": step_id,
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
            elif path == "/api/job":
                json_response(self, current_job)
            elif path == "/api/list":
                json_response(self, {"files": list_files(query.get("kind", ["all"])[0])})
            elif path == "/api/file":
                target = safe_path(query.get("path", [""])[0])
                if target.is_dir():
                    json_response(self, {"error": "Path is a directory."}, HTTPStatus.BAD_REQUEST)
                elif not target.exists():
                    json_response(self, {"error": "File does not exist."}, HTTPStatus.NOT_FOUND)
                else:
                    json_response(self, {"path": rel(target), "content": read_text(target)})
            elif path == "/api/settings":
                json_response(self, env_settings())
            else:
                json_response(self, {"error": "Not found."}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            data = read_body(self)
            if path == "/api/file":
                target = safe_path(str(data.get("path", "")))
                write_text(target, str(data.get("content", "")))
                json_response(self, {"ok": True, "path": rel(target)})
            elif path == "/api/upload":
                filename = Path(str(data.get("filename", "paper.md"))).name
                if not filename.endswith(".md"):
                    filename += ".md"
                target = PAPERS_DIR / filename
                write_text(target, str(data.get("content", "")))
                json_response(self, {"ok": True, "path": rel(target)})
            elif path == "/api/settings":
                write_env(data)
                json_response(self, {"ok": True, "settings": env_settings()})
            elif path == "/api/delete":
                target = safe_path(str(data.get("path", "")))
                if target.exists() and target.is_file():
                    target.unlink()
                json_response(self, {"ok": True})
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
                thread = threading.Thread(target=run_job, args=(step_id, [str(arg) for arg in args]), daemon=True)
                thread.start()
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


def main() -> None:
    ensure_dirs()
    port = int(os.getenv("LIT_REVIEW_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Literature review workbench: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
