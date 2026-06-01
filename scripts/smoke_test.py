#!/usr/bin/env python3
from __future__ import annotations

import compileall
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parents[1]


def find_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(url: str) -> dict:
    with request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, data: dict) -> dict:
    payload = json.dumps(data).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_server(url: str, timeout: float = 5.0) -> None:
    started = time.time()
    while time.time() - started < timeout:
        try:
            get_json(url + "/api/state")
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Server did not become ready.")


def wait_for_job(url: str, expected_step_id: str, timeout: float = 10.0) -> dict:
    started = time.time()
    last = {}
    while time.time() - started < timeout:
        last = get_json(url + "/api/job")
        if last.get("step_id") == expected_step_id and last.get("started_at") is not None and not last.get("running"):
            return last
        time.sleep(0.2)
    raise RuntimeError(f"Job did not finish. Last state: {last}")


def main() -> None:
    os.chdir(ROOT)
    print("Checking Python syntax...")
    if not compileall.compile_dir(ROOT / "scripts", quiet=1):
        raise SystemExit(1)

    node = shutil.which("node")
    if node:
        print("Checking frontend JavaScript syntax...")
        subprocess.run([node, "--check", str(ROOT / "web" / "app.js")], check=True)
    else:
        print("Node is not available; skipping JS syntax check.")

    port = find_port()
    env = {**os.environ, "LIT_REVIEW_PORT": str(port)}
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "web_app.py")],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for_server(url)
        state = get_json(url + "/api/state")
        assert "steps" in state and state["steps"], "state should contain workflow steps"
        files = get_json(url + "/api/list?kind=config")
        assert files["files"], "config file list should not be empty"
        review_brief = get_json(url + "/api/file?path=project_config/review_brief.md")
        assert "综述主题" in review_brief["content"], "review brief should be readable"

        post_json(url + "/api/run", {"step_id": "inventory", "args": ["--force"]})
        job = wait_for_job(url, "inventory")
        assert job.get("returncode") == 0, job.get("log", "")
        print("Smoke test passed.")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
