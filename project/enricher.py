"""
Read raw_results.json, enrich each listing with GPT-4o, write results.json.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from openai import OpenAI  # noqa: E402

RAW_NAME = "raw_results.json"
OUT_NAME = "results.json"

BASE_DIR = os.path.dirname(__file__)
RAW_PATH = os.path.join(BASE_DIR, RAW_NAME)
OUT_PATH = os.path.join(BASE_DIR, OUT_NAME)
STATUS_PATH = os.path.join(BASE_DIR, "pipeline_status.json")


def _write_pipeline_status(payload: dict[str, Any]) -> None:
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

FOOD_CATEGORIES = [
    "Cakes",
    "Kueh",
    "Malay Food",
    "Healthy",
    "Desserts",
    "Other",
]

PRICE_RANGES = [
    "Under $20",
    "$20-$50",
    "$50-$100",
    "Above $100",
]

SYSTEM_PROMPT = """You extract structured business lead data from scraped social and marketplace posts.
Rules:
- Output a single JSON object only (no markdown fences).
- business_name: Prefer the vendor / shop named in the contact field (e.g. text after a leading slash like /Moni Coffee, or the name inside parentheses like "… (The Long Weekend Pizza)"). Do NOT use the poster's username when it is only the reviewer (often emoji or a personal handle) and contact names a different business.
- Use Singapore context (areas like Tampines, Bedok, Jurong, etc.).
- food_category must be exactly one of: Cakes, Kueh, Malay Food, Healthy, Desserts, Other.
- price_range must be exactly one of: Under $20, $20-$50, $50-$100, Above $100. Infer from any prices mentioned; if unclear use best guess or "Under $20".
- active: true if the post or listing seems recent or still relevant; false if clearly outdated or you have no signal (default false).
- whatsapp: digits only with country code if possible, e.g. 6591234567, or empty string.
- instagram: handle without @, or empty string. Put the handle in `instagram`, not inside `business_name` (do not use \"(@handle on instagram)\" in the business name).
- telegram: username without @, or empty string.
- email: lowercase or empty string.
- platform must be exactly \"Lemon8\" or \"Shopee\" matching the input.
- original_url must copy the input post_url if present.
"""


def _build_user_payload(row: dict[str, Any]) -> str:
    return json.dumps(
        {
            "username": row.get("username", ""),
            "caption": row.get("caption", ""),
            "title": row.get("title", ""),
            "price": row.get("price", ""),
            "location": row.get("location", ""),
            "contact": row.get("contact", ""),
            "post_url": row.get("post_url", ""),
            "platform": row.get("platform", ""),
        },
        ensure_ascii=False,
    )


_META_PAREN_SUFFIX = [
    r"\s*\(\s*check\s*ig\s*\)\s*$",
    r"\s*\(\s*see\s*ig\s*\)\s*$",
    r"\s*\(\s*check\s*instagram\s*\)\s*$",
    r"\s*\(\s*see\s*instagram\s*\)\s*$",
    r"\s*\(\s*ig\s*\)\s*$",
    r"\s*\(\s*link\s+in\s+bio\s*\)\s*$",
    r"\s*\(\s*link\s+on\s+bio\s*\)\s*$",
    r"\s*\(\s*bio\s*\)\s*$",
    r"\s*\(\s*dm\s*(me)?\s*\)\s*$",
    r"\s*\(\s*pm\s*(me)?\s*\)\s*$",
    r"\s*\(\s*whatsapp\s*\)\s*$",
    r"\s*\(\s*wa\s*\)\s*$",
    r"\s*\(\s*telegram\s*\)\s*$",
    r"\s*\(\s*details\s+in\s+bio\s*\)\s*$",
    r"\s*\(\s*more\s+info\s+in\s+bio\s*\)\s*$",
    r"\s*\(\s*tap\s+link\s*\)\s*$",
    r"\s*\(\s*swipe\s+up\s*\)\s*$",
]


def _strip_trailing_meta_parens(s: str) -> str:
    t = s.strip()
    patterns = [re.compile(p, re.I) for p in _META_PAREN_SUFFIX]
    changed = True
    while changed:
        changed = False
        for pat in patterns:
            n = pat.sub("", t).strip()
            if n != t:
                t = n
                changed = True
                break
    return t


# "Brand (@handle on instagram)" or trailing "handle on instagram"
_IG_IN_PARENS = re.compile(
    r"^\s*(.+?)\s*\(\s*@?([A-Za-z0-9._]+)\s+on\s+instagram\s*\)\s*$",
    re.I,
)
_IG_SUFFIX = re.compile(r"^(.+?)\s+on\s+instagram\s*$", re.I)
_HANDLE_LIKE = re.compile(r"^[A-Za-z0-9._]+$")


def _split_business_name_instagram(business_name: str) -> tuple[str, str]:
    s = business_name.strip()
    if not s:
        return "", ""
    m = _IG_IN_PARENS.match(s)
    if m:
        name, handle = m.group(1).strip(), m.group(2).strip()
        name = _strip_trailing_meta_parens(name)
        return name, handle
    m = _IG_SUFFIX.match(s)
    if m:
        before = m.group(1).strip()
        if _HANDLE_LIKE.fullmatch(before):
            return before, before
        return before, ""
    return s, ""


def postprocess_business_name_instagram(out: dict[str, Any]) -> None:
    """Strip '( @handle on instagram)' / ' on instagram' from business_name; fill instagram if empty."""
    bn = str(out.get("business_name") or "").strip()
    if not bn:
        return
    clean, ig = _split_business_name_instagram(bn)
    if clean:
        out["business_name"] = clean[:200]
    if ig and not str(out.get("instagram") or "").strip():
        out["instagram"] = ig[:120]


_LABEL_BEFORE_BUSINESS = re.compile(
    r"whatsapp|preorder|pre-order|order via|for preorders|contact\s|reach\s|"
    r"\bdm\b|message\s|call\s|text\s|tap\s|link\s|visit\s|check\s+out",
    re.I,
)


def _contact_fallback_business_name(contact: str) -> str:
    c = contact.strip()
    if not c:
        return ""
    if c.startswith("/"):
        c = c.lstrip("/").strip()
    elif c.startswith("@"):
        c = c[1:].strip()

    c = _strip_trailing_meta_parens(c)
    if not c:
        return ""

    m = re.match(r"^(.+)\(([^)]+)\)\s*$", c)
    if m:
        prefix, inner = m.group(1).strip(), m.group(2).strip()
        if (
            _LABEL_BEFORE_BUSINESS.search(prefix)
            and 2 <= len(inner) < 120
            and not inner.lower().startswith("http")
        ):
            return inner

    return c


def _default_record(row: dict[str, Any]) -> dict[str, Any]:
    contact = str(row.get("contact") or "").strip()
    fallback_name = _contact_fallback_business_name(contact)
    name = fallback_name or (row.get("username") or "Unknown")
    return {
        "business_name": name[:120],
        "what_they_sell": (row.get("caption") or row.get("title") or "Unknown")[:500],
        "food_category": "Other",
        "location": row.get("location") or "Unknown",
        "price_range": "Under $20",
        "whatsapp": "",
        "instagram": "",
        "telegram": "",
        "email": "",
        "active": False,
        "platform": row.get("platform") or "Other",
        "original_url": row.get("post_url") or "",
    }


def _coerce_record(data: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    out = _default_record(row)
    out["business_name"] = str(data.get("business_name") or out["business_name"])[:200]
    out["what_they_sell"] = str(data.get("what_they_sell") or out["what_they_sell"])[:500]
    cat = str(data.get("food_category") or "Other")
    out["food_category"] = cat if cat in FOOD_CATEGORIES else "Other"
    loc = str(data.get("location") or out["location"])
    out["location"] = loc[:120]
    pr = str(data.get("price_range") or out["price_range"])
    out["price_range"] = pr if pr in PRICE_RANGES else "Under $20"
    out["whatsapp"] = str(data.get("whatsapp") or "").replace(" ", "")[:32]
    out["instagram"] = str(data.get("instagram") or "").lstrip("@")[:120]
    out["telegram"] = str(data.get("telegram") or "").lstrip("@")[:120]
    out["email"] = str(data.get("email") or "").strip()[:200]
    if isinstance(data.get("active"), bool):
        out["active"] = data["active"]
    plat = str(data.get("platform") or row.get("platform") or "")
    out["platform"] = plat if plat in ("Lemon8", "Shopee") else (row.get("platform") or "Other")
    out["original_url"] = str(data.get("original_url") or row.get("post_url") or "")[:2000]
    return out


def enrich_one(client: OpenAI, row: dict[str, Any]) -> dict[str, Any]:
    user_content = (
        "Normalize this listing into the schema. Input JSON:\n"
        + _build_user_payload(row)
        + "\n\nFor business_name, derive the seller/business from `contact` (slash handles, "
        "parentheses, etc.), not from `username` when username is just the reviewer.\n"
        "Respond with JSON keys: "
        "business_name, what_they_sell, food_category, location, price_range, "
        "whatsapp, instagram, telegram, email, active, platform, original_url."
    )
    resp = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        out = _default_record(row)
    else:
        out = _coerce_record(data, row)
    postprocess_business_name_instagram(out)
    return out


def main() -> None:
    if not os.path.isfile(RAW_PATH):
        print(f"No {RAW_NAME} found at {RAW_PATH}. Run scraper.py first.", file=sys.stderr)
        sys.exit(1)

    with open(RAW_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    # Normalize: TinyFish may return {"listings": [...]} instead of a plain array.
    if isinstance(raw, dict):
        for key in ("listings", "posts", "results", "result", "data", "items", "output"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            raw = []

    if not isinstance(raw, list):
        print(f"{RAW_NAME} must contain a JSON array.", file=sys.stderr)
        sys.exit(1)

    if not raw:
        print("No raw listings to enrich. Writing empty results.json.")
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        _write_pipeline_status(
            {
                "phase": "complete",
                "enriched": 0,
                "total": 0,
                "hint": "No listings scraped — check TinyFish runs in their dashboard.",
            }
        )
        return

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("Missing OPENAI_API_KEY in environment (.env).", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=key)
    enriched: list[dict[str, Any]] = []
    to_process = [r for r in raw if isinstance(r, dict) and not r.get("error")]
    total = len(to_process)

    if total == 0:
        print("No valid raw rows to enrich (empty or only error entries).")
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        _write_pipeline_status(
            {
                "phase": "complete",
                "enriched": 0,
                "total": 0,
                "hint": "Nothing to enrich — check raw_results.json.",
            }
        )
        return

    _write_pipeline_status(
        {
            "phase": "enriching",
            "enriched": 0,
            "total": total,
            "hint": "OpenAI enrichment — results.json updates after each row.",
        }
    )

    for i, row in enumerate(to_process, start=1):
        print(f"Enriching {i}/{total} …")
        try:
            enriched.append(enrich_one(client, row))
        except Exception as exc:  # noqa: BLE001
            print(f"  OpenAI error, using defaults: {exc!r}")
            fallback = _default_record(row)
            postprocess_business_name_instagram(fallback)
            enriched.append(fallback)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(enriched, f, ensure_ascii=False, indent=2)
        _write_pipeline_status(
            {
                "phase": "enriching",
                "enriched": len(enriched),
                "total": total,
                "hint": "Refresh or leave auto-poll on — cards appear as rows complete.",
            }
        )
        time.sleep(0.35)

    _write_pipeline_status(
        {
            "phase": "complete",
            "enriched": len(enriched),
            "total": total,
            "hint": "Pipeline finished.",
        }
    )

    print(f"Wrote {len(enriched)} enriched record(s) to {OUT_PATH}")


if __name__ == "__main__":
    main()
