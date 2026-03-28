#!/usr/bin/env python3
"""
Serve the `project/` folder so index.html, dashboard.html, and JSON resolve.

Run from the repo root (tinyfish-hack), not from inside project/:
  python serve.py

Then open http://localhost:8080/  (HBBScout landing)
     or http://localhost:8080/dashboard.html

POST /ingest  — feed TinyFish JSON directly into the pipeline.
  Accepts: {"listings": [...]} or a plain JSON array.
  Writes raw_results.json and results.json.

POST /api/scout  — start TinyFish + enrichment for a user query (from landing page).
  Body: {"query": "matcha"}
  Writes project/scout_intent.json and runs `python project/run.py` in a background thread.
  Returns 202 immediately; 409 if a run is already in progress.

GET /api/scout/status  — {"running": true|false}
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

PORT = 8080
ROOT = Path(__file__).resolve().parent / "project"
RAW_PATH = ROOT / "raw_results.json"
RESULTS_PATH = ROOT / "results.json"
SCOUT_INTENT_PATH = ROOT / "scout_intent.json"

_scout_lock = threading.Lock()
_scout_running = False


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


def _run_pipeline_job(query: str) -> None:
    global _scout_running
    try:
        with open(SCOUT_INTENT_PATH, "w", encoding="utf-8") as f:
            json.dump({"query": query.strip()[:200]}, f, ensure_ascii=False)
        print(f"[api/scout] Starting pipeline for query={query!r} …", flush=True)
        subprocess.run(
            [sys.executable, str(ROOT / "run.py")],
            cwd=str(ROOT),
            env=os.environ.copy(),
        )
        print("[api/scout] Pipeline finished.", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[api/scout] pipeline error: {exc!r}", flush=True)
    finally:
        with _scout_lock:
            _scout_running = False


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _path_base(self) -> str:
        return self.path.split("?", 1)[0].rstrip("/")

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        base = self._path_base()
        if base in ("/api/scout", "/api/scout/status", "/ingest"):
            self.send_response(204)
            self._cors()
            self.end_headers()
        else:
            self.send_error(404, "Not found")

    def do_GET(self) -> None:  # noqa: N802
        base = self._path_base()
        if base == "/api/scout/status":
            with _scout_lock:
                running = _scout_running
            self._send_json(200, {"running": running})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        global _scout_running
        base = self._path_base()
        if base == "/ingest":
            self._handle_ingest()
            return
        if base == "/api/scout":
            self._handle_scout()
            return
        self.send_error(404, "Not found")

    def _handle_ingest(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            payload = json.loads(body)
            rows = _normalize_json(payload)
            if not rows:
                self._send_json(400, {"ok": False, "error": "No rows found in payload"})
                return
            _write_json(RAW_PATH, rows)
            _write_json(RESULTS_PATH, rows)
            print(f"[ingest] Wrote {len(rows)} row(s) to raw_results.json and results.json")
            self._send_json(200, {"ok": True, "rows": len(rows)})
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": str(exc)})

    def _handle_scout(self) -> None:
        global _scout_running
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            payload = json.loads(body) if body else {}
            q = str(payload.get("query") or "").strip()
            if not q or len(q) > 120:
                self._send_json(
                    400,
                    {"ok": False, "error": "query is required (1–120 characters)"},
                )
                return
            with _scout_lock:
                if _scout_running:
                    self._send_json(
                        409,
                        {"ok": False, "error": "A scout run is already in progress."},
                    )
                    return
                _scout_running = True
            t = threading.Thread(target=_run_pipeline_job, args=(q,), daemon=True)
            t.start()
            self._send_json(
                202,
                {"ok": True, "message": "Pipeline started", "query": q},
            )
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid JSON"})
        except Exception as exc:  # noqa: BLE001
            with _scout_lock:
                _scout_running = False
            self._send_json(500, {"ok": False, "error": str(exc)})

    def log_message(self, fmt, *args):
        if args and str(args[0]).startswith("POST"):
            super().log_message(fmt, *args)


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f"Expected folder missing: {ROOT}")

    watcher = threading.Thread(target=_watch_raw_results, daemon=True)
    watcher.start()

    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving {ROOT}")
        print(f"  Landing:   http://localhost:{PORT}/")
        print(f"  Dashboard: http://localhost:{PORT}/dashboard.html")
        print(f"  POST http://localhost:{PORT}/api/scout  ← start scrape from UI")
        print(f"  POST http://localhost:{PORT}/ingest")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
