# Crawlr

**Crawlr** is an AI-powered, **self-healing** web scraper with an e-commerce / price-intelligence vertical.

## Why Crawlr is different

Most "AI scrapers" pipe every page through an LLM — slow, expensive, and
non-deterministic. Crawlr uses the LLM (or an offline heuristic) **only to
generate and repair CSS selectors**, then extracts pages deterministically with
those cached selectors. When a site changes its markup and the selectors break,
Crawlr detects it and **regenerates the selectors automatically** (self-healing).

- **Cheap & fast:** deterministic extraction on every run; the model runs once per site/schema and only again on breakage.
- **Resilient:** self-healing survives layout changes that break traditional scrapers.
- **General-purpose core, vertical products:** the same engine powers any schema; e-commerce ships out of the box.
- **Runs offline:** works with zero API keys via a heuristic selector generator; add an OpenAI/Anthropic key for higher accuracy.
- **Continuous monitoring:** schedule scrapes, store time-series snapshots, and detect price/stock changes.

## Architecture

```
fetch (static -> auto JS) -> simplify DOM -> selector cache?
   |-- hit  -> deterministic extract --(broken?)--> self-heal
   |-- miss -> LLM/heuristic generate selectors -> cache -> extract
                              |
                        store run (SQLite) -> diff vs previous -> log changes
```

Modules:

| Module | Responsibility |
|--------|----------------|
| `fetcher.py` | Static HTTP with retries + auto-escalation to Playwright for JS sites |
| `simplifier.py` | Reduce HTML to a compact outline for the LLM (80–95% fewer tokens) |
| `llm.py` | Pluggable OpenAI/Anthropic selector generation + offline heuristic fallback |
| `extractor.py` | Self-healing deterministic extraction core |
| `selector_cache.py` | Persistent selector cache keyed by host + schema |
| `storage.py` | SQLite: sites, runs, records (time series), change log |
| `monitor.py` | Scheduling + change detection (price drops, stock, new/removed items) |
| `verticals/ecommerce.py` | Ready-made `product` and `product_list` schemas |
| `cli.py` / `api.py` | Typer CLI + FastAPI dashboard |

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
# optional: JS rendering for client-rendered sites
pip install -e '.[js]' && playwright install chromium
```

## Usage

```bash
# One-off scrape of a product page
crawlr scrape https://example-store.com/product/123 --schema product

# Scrape a category/search page (list of products)
crawlr scrape https://example-store.com/search?q=laptop --schema product_list

# Register a site for continuous monitoring (every 30 min)
crawlr add https://example-store.com/product/123 --schema product --interval 30

# Run all due sites (drive this from cron) and detect changes
crawlr monitor

# Inspect state
crawlr sites
crawlr changes

# Launch the dashboard
crawlr serve   # http://127.0.0.1:8000
```

## LLM configuration (optional)

Set environment variables (or a `.env` file) to enable an LLM provider:

```bash
CRAWLR_LLM_PROVIDER=openai        # or anthropic, or none (default)
CRAWLR_LLM_API_KEY=sk-...
CRAWLR_LLM_MODEL=gpt-4o-mini      # optional override
```

Without a key, the heuristic selector generator is used automatically.

## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `CRAWLR_DATA_DIR` | `./.crawlr` | Where the SQLite DB and selector cache are stored |
| `CRAWLR_LLM_PROVIDER` | `none` | `openai`, `anthropic`, or `none` (heuristic) |
| `CRAWLR_LLM_API_KEY` | — | API key for the chosen provider |
| `CRAWLR_LLM_MODEL` | provider default | Model override |
| `CRAWLR_USER_AGENT` | `Crawlr/0.1` UA | User-Agent sent with requests |
| `CRAWLR_FETCH_TIMEOUT` | `30` | Per-request timeout (seconds) |
| `CRAWLR_FETCH_RETRIES` | `3` | Retry attempts with exponential backoff |
| `CRAWLR_MIN_DELAY` | `1.0` | Minimum delay between requests to the same host |

## Development

```bash
pip install -e '.[dev]'
pytest        # run the offline test suite
ruff check .  # lint
```

The test suite runs fully offline: `fetch` is monkeypatched with local HTML
fixtures, and selector generation uses the heuristic path. It covers extraction,
**self-healing after a simulated site redesign**, and price-change detection.

## Roadmap

- Proxy rotation + stealth for anti-bot resilience
- Pydantic-schema-driven custom verticals (jobs, real estate, leads)
- Alerting (email / webhook / Slack) on change events
- Postgres storage backend for scale
