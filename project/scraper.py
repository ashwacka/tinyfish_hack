"""
Scrape Lemon8 hashtags in ONE TinyFish browser session.
Writes deduped rows to raw_results.json and mirrors the same array to results.json
so the dashboard sees data immediately. Running enricher later overwrites
results.json with OpenAI-enriched rows.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from tinyfish import (  # noqa: E402
    BrowserProfile,
    EventType,
    ProxyConfig,
    RunStatus,
    TinyFish,
)

PROXY_OFF = ProxyConfig(enabled=False)

_RAW_DIR = os.path.dirname(__file__)
RAW_PATH = os.path.join(_RAW_DIR, "raw_results.json")
RESULTS_PATH = os.path.join(_RAW_DIR, "results.json")
STATUS_PATH = os.path.join(_RAW_DIR, "pipeline_status.json")

LEMON8_HOME = "https://www.lemon8-app.com/"

LEMON8_HASHTAG_URLS = [
    "https://www.lemon8-app.com/search/hashtag/sghomefood",
    "https://www.lemon8-app.com/search/hashtag/sghomebaker",
    "https://www.lemon8-app.com/search/hashtag/sghomebased",
]

SCOUT_INTENT_PATH = os.path.join(_RAW_DIR, "scout_intent.json")


def _load_scout_focus() -> str:
    """Optional user theme from landing page (scout_intent.json or SCOUT_QUERY env)."""
    env_q = (os.environ.get("SCOUT_QUERY") or "").strip()
    if env_q:
        return env_q[:200]
    if os.path.isfile(SCOUT_INTENT_PATH):
        try:
            with open(SCOUT_INTENT_PATH, encoding="utf-8") as f:
                data = json.load(f)
            q = str(data.get("query") or "").strip()
            return q[:200] if q else ""
        except (json.JSONDecodeError, OSError):
            return ""
    return ""


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (row.get("post_url") or "").strip()
        if not key:
            key = f"{row.get('username', '')}|{(row.get('caption') or row.get('title') or '')[:80]}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _write_pipeline_status(payload: dict[str, Any]) -> None:
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _infer_platform_from_url(post_url: str) -> str:
    u = post_url.lower()
    if "shopee" in u:
        return "Shopee"
    return "Lemon8"


def _normalize_platform(name: Any) -> str:
    s = str(name or "").strip().lower()
    if s == "shopee":
        return "Shopee"
    return "Lemon8"


def _normalize_listing(item: dict[str, Any], platform: str) -> dict[str, Any]:
    contact = item.get("contact")
    if isinstance(contact, dict):
        contact_str = json.dumps(contact)
    elif contact is None:
        contact_str = ""
    else:
        contact_str = str(contact)

    post_url = (
        item.get("post_url") or item.get("listing_url") or item.get("url") or ""
    )
    plat = _normalize_platform(item.get("platform") or platform)
    if not item.get("platform") and post_url:
        plat = _infer_platform_from_url(post_url)

    return {
        "username": item.get("username") or item.get("seller_name") or "",
        "caption": item.get("caption") or item.get("description") or "",
        "title": item.get("title") or item.get("product_name") or "",
        "price": item.get("price") or "",
        "location": item.get("location") or "",
        "contact": contact_str,
        "post_url": post_url,
        "platform": plat,
    }


def _parse_json_blob(raw: str) -> Any | None:
    """Parse agent output that may include markdown fences or extra prose."""
    s = raw.strip()
    if not s:
        return None
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```\s*$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _coerce_result_to_object(result_json: Any) -> Any:
    if result_json is None:
        return None
    if isinstance(result_json, str):
        return _parse_json_blob(result_json)
    return result_json


def _looks_like_post_row(d: dict[str, Any]) -> bool:
    return bool(
        d.get("post_url")
        or d.get("url")
        or d.get("listing_url")
        or d.get("link")
        or d.get("href")
        or d.get("username")
        or d.get("author")
        or d.get("handle")
        or d.get("caption")
        or d.get("title")
    )


def _find_list_of_posts(obj: Any, depth: int = 0) -> list[dict[str, Any]]:
    """Find the first list of dicts that look like Lemon8 post rows (nested anywhere)."""
    if depth > 10 or obj is None:
        return []
    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict) and not x.get("error")]
        if len(dicts) >= 1 and any(_looks_like_post_row(x) for x in dicts):
            return dicts
        for x in obj:
            sub = _find_list_of_posts(x, depth + 1)
            if sub:
                return sub
        return []
    if isinstance(obj, dict):
        for v in obj.values():
            sub = _find_list_of_posts(v, depth + 1)
            if sub:
                return sub
    return []


def _extract_array_from_result(result_json: Any) -> list[dict[str, Any]]:
    if result_json is None:
        return []

    coerced = _coerce_result_to_object(result_json)
    if coerced is None and isinstance(result_json, str):
        return []

    data = coerced if coerced is not None else result_json

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict) and not x.get("error")]

    if isinstance(data, dict):
        if data.get("error"):
            return []
        for key in (
            "result",
            "listings",
            "posts",
            "results",
            "data",
            "items",
            "output",
            "extracted",
            "leads",
            "businesses",
            "records",
        ):
            val = data.get(key)
            if isinstance(val, list):
                rows = [x for x in val if isinstance(x, dict) and not x.get("error")]
                if rows:
                    return rows
            if isinstance(val, dict):
                nested = _extract_array_from_result(val)
                if nested:
                    return nested

        found = _find_list_of_posts(data)
        if found:
            return found

        if _looks_like_post_row(data):
            return [data]

    return []


def _debug_unparsed_result(payload: Any) -> None:
    preview = repr(payload)
    if len(preview) > 2000:
        preview = preview[:2000] + "…"
    print(f"    Debug: `result` payload Python type = {type(payload).__name__}", file=sys.stderr)
    print(f"    Debug: value preview (see why parsing got 0 rows):\n{preview}", file=sys.stderr)


def build_combined_scrape_goal(scout_focus: str = "") -> str:
    lemon8_bullets = "\n".join(f"     • {u}" for u in LEMON8_HASHTAG_URLS)
    focus_block = ""
    if scout_focus:
        esc = scout_focus.replace('"', "'")[:200]
        focus_block = f"""
0. USER SCOUT REQUEST (prioritize this theme)
   The user asked for Singapore HOME-BASED sellers related to: "{esc}".
   Use Lemon8 search (search bar / suggestions) with queries like "{esc}", "sg {esc}", "home based {esc}", "sg home {esc}" as needed.
   Collect posts that match this theme (food, beauty, crafts, services — home-based / HBB / small seller).
   Merge these leads with hashtag results below; de-duplicate by post URL.
"""
    return f"""
You are collecting Singapore home-based business leads on Lemon8 in a SINGLE continuous session.
Do everything below before returning JSON. Re-use the same browser tab/window; navigate with the address bar or in-page links.
{focus_block}
1. Open {LEMON8_HOME}, wait until loaded, dismiss cookie banners or popups.
2. Visit EACH hashtag URL below IN ORDER. On each page, scroll until roughly 10–15 posts that look like home food / home bakers / home-based sellers are visible. Extract data from each relevant post.
{lemon8_bullets}
   Each record must include: username, caption (or post title), price (if any), location, contact (handles, phone, WhatsApp text—one string), post_url (full permalink), and "platform": "Lemon8".

FINAL OUTPUT (mandatory)
Your last step must output machine-parseable JSON only (no markdown, no ``` fences, no commentary).
Exactly one JSON object with this shape (listings must be a non-empty array if you collected any posts):
{{ "listings": [ {{ "username": "...", "caption": "...", "title": "", "price": "", "location": "", "contact": "", "post_url": "...", "platform": "Lemon8" }} ] }}

Use empty strings for unknown fields. Include EVERY post you extracted across all hashtags in the single "listings" array.
If you truly found zero posts, return {{ "listings": [] }}.

If login is required, return partial data in "listings" and optional "note": "partial_due_to_login".
"""


def _run_single_tinyfish_session(client: TinyFish, scout_focus: str = "") -> list[dict[str, Any]]:
    goal = build_combined_scrape_goal(scout_focus)
    print("\n=== One TinyFish scrape session (Lemon8 hashtags only) ===")
    print(f"    Start URL: {LEMON8_HOME}")
    if scout_focus:
        print(f"    Scout focus: {scout_focus!r}")
    print("    This is a single dashboard run — it may take several minutes.\n")

    rows: list[dict[str, Any]] = []
    run_id: str | None = None
    try:
        with client.agent.stream(
            url=LEMON8_HOME,
            goal=goal,
            browser_profile=BrowserProfile.STEALTH,
            proxy_config=PROXY_OFF,
            on_progress=lambda e: print(f"    > {e.purpose}"),
        ) as stream:
            for event in stream:
                rid = getattr(event, "run_id", None)
                if rid:
                    run_id = rid
                if event.type != EventType.COMPLETE:
                    continue
                if event.status != RunStatus.COMPLETED or event.error:
                    err = event.error.message if event.error else "unknown error"
                    print(f"    Run failed: {err}")
                    return rows

                # TinyFish stores structured output on the run as `result` (REST). The SSE
                # COMPLETE event does not reliably expose that field in this SDK (it maps
                # `resultJson` only), so we always load the final payload via runs.get().
                rest_payload: Any | None = None
                if not run_id:
                    print("    Debug: COMPLETE event had no run_id; cannot fetch `result`.", file=sys.stderr)
                else:
                    try:
                        run = client.runs.get(run_id)
                        rest_payload = run.result
                        for raw in _extract_array_from_result(rest_payload):
                            rows.append(_normalize_listing(raw, ""))
                    except Exception as exc:  # noqa: BLE001
                        print(f"    runs.get({run_id!r}) failed: {exc!r}", file=sys.stderr)

                print(f"    Parsed {len(rows)} listing(s) from TinyFish result.")
                if not rows:
                    if rest_payload is not None:
                        _debug_unparsed_result(rest_payload)
                    else:
                        print(
                            "    Debug: runs.get returned no `result` payload to parse.",
                            file=sys.stderr,
                        )
                return rows
    except Exception as exc:  # noqa: BLE001
        print(f"    Error: {exc!r}")
        return rows
    return rows


def main() -> None:
    if not os.environ.get("TINYFISH_API_KEY"):
        print("Missing TINYFISH_API_KEY in environment (.env).", file=sys.stderr)
        sys.exit(1)

    client = TinyFish()

    _write_pipeline_status(
        {
            "phase": "scraping",
            "jobs_done": 0,
            "jobs_total": 1,
            "raw_listings": 0,
            "last_job": "single session (Lemon8 only)",
            "hint": "One TinyFish run covers all targets; raw_results.json updates when it finishes.",
        }
    )

    scout_focus = _load_scout_focus()
    part = _run_single_tinyfish_session(client, scout_focus)
    deduped = _dedupe_rows(part)

    if not deduped:
        print(
            "\n  (0 rows — TinyFish may have failed, returned non-JSON, or used a shape we "
            "did not parse. Check the run in the TinyFish dashboard and the terminal error above.)",
            file=sys.stderr,
        )
        # Load existing raw data so we don't overwrite good data with empty results.
        existing: list[Any] = []
        if os.path.isfile(RAW_PATH):
            try:
                with open(RAW_PATH, encoding="utf-8") as f:
                    loaded = json.load(f)
                # Unwrap {"listings": [...]} if needed.
                if isinstance(loaded, dict):
                    for key in ("listings", "posts", "results", "result", "data", "items", "output"):
                        if isinstance(loaded.get(key), list):
                            loaded = loaded[key]
                            break
                if isinstance(loaded, list):
                    existing = loaded
            except Exception:  # noqa: BLE001
                pass
        if existing:
            print(f"  Keeping {len(existing)} existing listing(s) from {RAW_PATH}.", file=sys.stderr)
            deduped = existing

    with open(RAW_PATH, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    # Same data in results.json so dashboard / git see scrape output without enricher.
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    _write_pipeline_status(
        {
            "phase": "scraping_complete",
            "jobs_done": 1,
            "jobs_total": 1,
            "raw_listings": len(deduped),
            "last_job": None,
            "hint": "results.json = raw scrape; run enricher to replace with OpenAI-cleaned rows.",
        }
    )

    print(f"\nSaved {len(deduped)} listing(s) to {RAW_PATH} and {RESULTS_PATH}")


if __name__ == "__main__":
    main()
