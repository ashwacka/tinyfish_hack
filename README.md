# HBBScout (TinyFish Hack)

**HBBScout** helps you discover **Singapore home-based businesses** from **Lemon8** using [TinyFish](https://tinyfish.ai) browser automation, then structures leads with OpenAI and shows them in a web dashboard.

## What’s in the repo

| Path | Purpose |
|------|--------|
| `project/index.html` | Landing page — search keywords, start a scout run |
| `project/dashboard.html` | Results grid — contacts, filters, CSV export |
| `project/scraper.py` | TinyFish scrape → `raw_results.json` |
| `project/enricher.py` | OpenAI enrichment → `results.json` |
| `project/run.py` | Runs scraper then enricher (full pipeline) |
| `serve.py` | **Recommended** local server: static files + scout API |

## Quick start

### 1. Python and dependencies

```bash
cd tinyfish-hack
pip install -r project/requirements.txt
```

### 2. API keys

```bash
cp project/.env.example project/.env
```

Edit `project/.env`:

- `TINYFISH_API_KEY` — from your TinyFish account  
- `OPENAI_API_KEY` — for GPT enrichment of listings  

Never commit real keys. `project/.env` is gitignored.

### 3. Run the app (full experience)

From the **repository root** (not inside `project/`):

```bash
python serve.py
```

Then open:

- **Landing / scout:** [http://localhost:8080/](http://localhost:8080/)  
- **Dashboard:** [http://localhost:8080/dashboard.html](http://localhost:8080/dashboard.html)  

`serve.py` is required for **“Find Businesses”** on the landing page (it exposes `/api/scout`). A plain `python -m http.server` **cannot** start scrapes from the UI.

### 4. Run the pipeline from the terminal only

```bash
cd project
python run.py
```

Uses `scout_intent.json` if present (written by the landing flow) or optional `SCOUT_QUERY` env var; see the user guide.

## Documentation

- **[USER_GUIDE.md](USER_GUIDE.md)** — step-by-step for scouts, dashboard, troubleshooting, and demos.

## Requirements

- Python 3.10+ recommended  
- Network access for TinyFish and OpenAI  
- First TinyFish run can take several minutes  

## License / hackathon

Built for a TinyFish-focused hack; adjust license and branding as needed for your team.
