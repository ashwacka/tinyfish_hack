"""
Run scraper then enricher and print a short summary.
"""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(__file__)
RESULTS_PATH = os.path.join(BASE_DIR, "results.json")


def _summary() -> tuple[int, int, int]:
    if not os.path.isfile(RESULTS_PATH):
        return 0, 0, 0
    with open(RESULTS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return 0, 0, 0
    n = len(data)
    wa = sum(1 for r in data if isinstance(r, dict) and (r.get("whatsapp") or "").strip())
    ig = sum(1 for r in data if isinstance(r, dict) and (r.get("instagram") or "").strip())
    return n, wa, ig


def main() -> None:
    print("=== Lead pipeline ===\n", flush=True)

    print("[1/2] Running scraper (TinyFish) …", flush=True)
    try:
        import scraper

        scraper.main()
    except SystemExit as e:
        if e.code not in (0, None):
            print("Scraper exited with an error.", file=sys.stderr)
            raise
    except Exception as exc:  # noqa: BLE001
        print(f"Scraper failed: {exc!r}", file=sys.stderr)
        sys.exit(1)

    print("\n[2/2] Running enricher (OpenAI) …", flush=True)
    try:
        import enricher

        enricher.main()
    except SystemExit as e:
        if e.code not in (0, None):
            print("Enricher exited with an error.", file=sys.stderr)
            raise
    except Exception as exc:  # noqa: BLE001
        print(f"Enricher failed: {exc!r}", file=sys.stderr)
        sys.exit(1)

    total, with_wa, with_ig = _summary()
    print("\n=== Done ===", flush=True)
    print(f"Businesses in results.json: {total}", flush=True)
    print(f"With WhatsApp: {with_wa}", flush=True)
    print(f"With Instagram: {with_ig}", flush=True)
    repo_root = os.path.dirname(BASE_DIR)
    serve_py = os.path.join(repo_root, "serve.py")
    print("\nView dashboard:", flush=True)
    if os.path.isfile(serve_py):
        print(f"  From repo root:  python serve.py", flush=True)
        print("  Then: http://localhost:8080/dashboard.html", flush=True)
    print(
        f"  Or:  cd {BASE_DIR} && python -m http.server 8080",
        flush=True,
    )


if __name__ == "__main__":
    main()
