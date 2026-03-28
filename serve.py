#!/usr/bin/env python3
"""
Serve the `project/` folder so dashboard.html and results.json resolve.

Run from the repo root (tinyfish-hack), not from inside project/:
  python serve.py

Then open http://localhost:8080/dashboard.html

POST /ingest  — feed TinyFish JSON directly into the pipeline.
  Accepts: {"listings": [...]} or a plain JSON array.
  Writes raw_results.json and results.json so the dashboard updates immediately.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import threading
import time
from pathlib import Path
from typing import Any

PORT = 8080
ROOT = Path(__file__).resolve().parent / "project"
RAW_PATH = ROOT / "raw_results.json"
RESULTS_PATH = ROOT / "results.json"


def _normalize_json(payload: Any) -> list[dict]:
    """Unwrap {"listings": [...]} or similar shapes into a plain list."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("listings", "posts", "results", "result", "data", "items", "output"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def _write_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _sync_raw_to_results() -> None:
    """Read raw_results.json, normalize, write to results.json."""
    try:
        with open(RAW_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        rows = _normalize_json(raw)
        if rows:
            _write_json(RESULTS_PATH, rows)
            print(f"[watcher] Synced {len(rows)} row(s) from raw_results.json → results.json")
    except Exception as exc:  # noqa: BLE001
        print(f"[watcher] Sync error: {exc!r}")


def _watch_raw_results() -> None:
    """Background thread: re-sync results.json whenever raw_results.json changes."""
    last_mtime = 0.0
    while True:
        try:
            mtime = os.path.getmtime(RAW_PATH) if RAW_PATH.exists() else 0.0
            if mtime != last_mtime and mtime != 0.0:
                last_mtime = mtime
                _sync_raw_to_results()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") == "/ingest":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                payload = json.loads(body)
                rows = _normalize_json(payload)
                if not rows:
                    self._respond(400, {"ok": False, "error": "No rows found in payload"})
                    return
                _write_json(RAW_PATH, rows)
                _write_json(RESULTS_PATH, rows)
                print(f"[ingest] Wrote {len(rows)} row(s) to raw_results.json and results.json")
                self._respond(200, {"ok": True, "rows": len(rows)})
            except Exception as exc:  # noqa: BLE001
                self._respond(500, {"ok": False, "error": str(exc)})
        else:
            self.send_error(404, "Not found")

    def _respond(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # suppress per-request noise for GET
        if args and str(args[0]).startswith("POST"):
            super().log_message(fmt, *args)


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f"Expected folder missing: {ROOT}")

    watcher = threading.Thread(target=_watch_raw_results, daemon=True)
    watcher.start()

    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving {ROOT}")
        print(f"  http://localhost:{PORT}/dashboard.html")
        print(f"  POST http://localhost:{PORT}/ingest  ← pipe TinyFish JSON here")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
