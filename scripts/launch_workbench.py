#!/usr/bin/env python3
from __future__ import annotations

import os
import socket
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline_utils import ensure_dirs  # noqa: E402
from web_app import Handler  # noqa: E402


def find_port(start: int = 8765, attempts: int = 25) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free local port found from {start} to {start + attempts - 1}.")


def main() -> None:
    os.chdir(ROOT)
    ensure_dirs()
    requested_port = int(os.getenv("LIT_REVIEW_PORT", "8765"))
    port = find_port(requested_port)
    url = f"http://127.0.0.1:{port}"
    print(f"AI literature review workbench is starting at {url}")
    print("Keep this window open while using the app. Press Ctrl+C to stop.")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

