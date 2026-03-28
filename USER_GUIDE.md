# HBBScout — User Guide

This guide explains how to use **HBBScout** end to end: from the landing page search through TinyFish scraping to the enriched results dashboard.

---

## 1. Before you start

### Software

- **Python 3.10+** installed  
- Dependencies: `pip install -r project/requirements.txt` (run from the repo root)

### Secrets (`project/.env`)

Create `project/.env` (you can copy from `project/.env.example`):

| Variable | Used for |
|----------|----------|
| `TINYFISH_API_KEY` | Browser automation / scraping on Lemon8 |
| `OPENAI_API_KEY` | Turning raw posts into structured leads (business name, contacts, menu hints, etc.) |

Keep this file private; do not commit it to git.

---

## 2. Starting the web app the right way

### Use `serve.py` (recommended)

From the **repository root** (`tinyfish-hack/`, where `serve.py` lives):

```bash
python serve.py
```

Then visit:

- **http://localhost:8080/** — landing page (search + “Find Businesses”)  
- **http://localhost:8080/dashboard.html** — results dashboard  

**Why not `python -m http.server`?**  
That only serves files. It does **not** provide the **scout API** (`/api/scout`, `/api/scout/status`), so the landing page cannot start a scrape. Always use **`python serve.py`** for the full workflow.

---

## 3. Landing page — scout a topic

1. Open **http://localhost:8080/**  
2. Type what you want (e.g. *matcha*, *bento cakes*, *nail salon*) or click a **Popular category** chip to fill the search box.  
3. Click **Find Businesses →**.

### What happens next

1. A **loading screen** appears: *“Hold on! We are searching through the web for your request”* while the pipeline runs.  
2. The server writes your keywords to **`project/scout_intent.json`** and runs **`project/run.py`** in the background (TinyFish scrape + OpenAI enrichment).  
3. When the run finishes, the browser sends you to the **dashboard** with your query saved so the list is easy to filter.

### If you see "We couldn't start the search"

- Confirm **`python serve.py`** is running from the **repo root**, not only `http.server`.  
- You can still click **Go to dashboard** to view old results, or run the pipeline manually (next section).

### Only one scout at a time

If another scout is already running, wait until it finishes or use the messages on screen. The API returns **409** when a run is already in progress.

---

## 4. Running the pipeline without the browser

Useful for debugging or if you prefer the terminal:

```bash
cd project
python run.py
```

This runs:

1. **Scraper** (`scraper.py`) — one TinyFish session (Lemon8 + optional **scout focus** from `scout_intent.json` or `SCOUT_QUERY`).  
2. **Enricher** (`enricher.py`) — reads `raw_results.json`, writes enriched **`results.json`**.

Optional environment variable:

```bash
export SCOUT_QUERY="matcha"
cd project && python run.py
```

`SCOUT_QUERY` overrides the file-based intent for that run.

---

## 5. Dashboard — working with results

Open **http://localhost:8080/dashboard.html** (or use **Have results? View dashboard →** on the landing page).

### After a scout

- A banner may show **Filtered for your scout** with your keywords.  
- The **search** box can be pre-filled; you can change it anytime.  

### Features

- **Stats** — totals, WhatsApp / Instagram counts, platform mix.  
- **Auto-refresh** — polls `results.json` / `raw_results.json` every few seconds (toggle off if you want).  
- **Filters** — category, location, platform, price band, contact chips (e.g. Has Instagram).  
- **Cards** — click a card (outside links) to expand **menu / food highlights** when available.  
- **Export CSV** — downloads the visible (filtered) rows.  
- **Scout home** — link back to the landing page.  

### Data sources

- Prefer **`results.json`** when it has rows (enriched).  
- Otherwise the UI may show **`raw_results.json`** (scrape-only shape).

---

## 6. Files you might touch or inspect

| File | Role |
|------|------|
| `project/raw_results.json` | Output of TinyFish scrape (normalized rows) |
| `project/results.json` | Enriched leads for the dashboard |
| `project/pipeline_status.json` | Rough phase hint for the UI banner |
| `project/scout_intent.json` | Written by the UI before a scout run (gitignored) |

---

## 7. Other HTTP endpoints (developers)

When using **`serve.py`**:

| Method | Path | Purpose |
|--------|------|--------|
| `POST` | `/api/scout` | Body: `{"query":"your keywords"}`. Starts `run.py` in the background. |
| `GET` | `/api/scout/status` | `{"running": true|false}` |
| `POST` | `/ingest` | Push pre-built JSON listings into `raw_results.json` / `results.json` |

---

## 8. Troubleshooting

| Problem | Things to check |
|--------|------------------|
| Landing error modal | Use `python serve.py` from repo root; keys in `project/.env` |
| 0 listings after scrape | TinyFish run in their dashboard; `TINYFISH_API_KEY`; Lemon8 access |
| Enrichment missing / errors | `OPENAI_API_KEY`, quota, network |
| Dashboard empty | Run `python project/run.py` or wait for scout to finish; reload |
| Stale data | Click **Reload data**; ensure auto-refresh is on during a run |

---

## 9. Tips for demos

1. Set `.env` and run **`python serve.py`**.  
2. Open the **landing** URL, enter a crisp keyword, click **Find Businesses**.  
3. While the loader is up, mention TinyFish + Lemon8 + enrichment.  
4. When redirected, show **filters**, **contact buttons**, and **CSV export**.  

For a quicker loop without waiting on TinyFish, use **`POST /ingest`** with sample JSON (see `serve.py` docstring) or keep a populated `results.json` in `project/`.

---

*If you extend the scraper goals or hashtags, update this guide so teammates stay aligned.*
