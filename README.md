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

## Features

- **Self-healing extraction** with LLM or offline heuristic selector generation.
- **Alerting** on changes via webhook, Slack, and email, with threshold rules (e.g. only price drops above N%).
- **Validation & confidence scoring** per run, surfaced in the CLI and dashboard.
- **LLM cost guardrails:** per-run call budget, content-hash cache to avoid re-billing identical pages, and spend accounting.
- **Anti-bot resilience:** proxy rotation, robots.txt compliance, randomized delay jitter, and optional User-Agent rotation.
- **Concurrent monitoring** of many sites via a bounded async runner.
- **Built-in scheduler daemon** (`crawlr monitor --daemon`) — no external cron required.
- **User-defined schemas** in YAML/JSON — add new verticals (jobs, real estate, leads) without code.
- **Dashboard** with add-site form, run-now buttons, health indicators, and price-history sparklines.
- **Pluggable storage:** SQLite by default, Postgres via `CRAWLR_DATABASE_URL`; Docker + docker-compose included.

## Watchlist — the easy way

Track a competitor's price and stock in one command:

```bash
crawlr watch "https://store.com/product/123"                 # track price + stock
crawlr watch "https://store.com/product/123" --target 25     # alert at/below $25
crawlr watch "https://store.com/product/123" --restock       # alert when back in stock
crawlr watchlist                                             # see current price, movement, stock
crawlr monitor --daemon                                      # keep checking in the background
```

Or use the **dashboard** (`crawlr serve`) — a black‑and‑white, iOS‑styled watchlist: paste a
product URL, pick a **trigger** from the dropdown (the filter for when you want to be alerted),
optionally set a target price, and click **Watch**.

### Trigger filter

Choose per watch (CLI `--trigger` or the dashboard dropdown):

| Trigger | Alerts when |
|---------|-------------|
| `any_change` | any watched field changes |
| `price_drop` | the price goes down |
| `price_below` | price is at/below your target |
| `price_above` | price is at/above your target |
| `back_in_stock` | the item becomes available |
| `out_of_stock` | the item sells out |

### Rules template — "what happens in different circumstances"

For richer logic across many situations, create an editable rules file:

```bash
crawlr init          # writes crawlr.rules.yaml
```

```yaml
default_action: ignore
rules:
  - when: price_drops_below
    amount: 25
    action: alert
  - when: back_in_stock
    action: alert
  - when: price_increases
    action: ignore
```

When `crawlr.rules.yaml` exists it takes precedence over per‑watch triggers, giving you a single
place to describe exactly what should happen in each circumstance.

## Architecture

```
fetch (static -> auto JS, proxies, robots, jitter) -> simplify DOM -> selector cache?
   |-- hit  -> deterministic extract --(broken?)--> self-heal
   |-- miss -> LLM/heuristic generate selectors -> cache -> extract
                              |
              validate + confidence score -> store run (SQLite/Postgres)
                              |
                     diff vs previous -> log changes -> alert sinks
```

Modules:

| Module | Responsibility |
|--------|----------------|
| `fetcher.py` | Static HTTP + retries, proxy rotation, robots.txt, jitter, auto-escalation to Playwright |
| `simplifier.py` | Reduce HTML to a compact outline for the LLM (80–95% fewer tokens) |
| `llm.py` | Pluggable OpenAI/Anthropic selector generation + offline heuristic fallback |
| `usage.py` | LLM call budget + token/spend accounting |
| `extractor.py` | Self-healing deterministic extraction core |
| `validate.py` | Schema validation + confidence scoring |
| `selector_cache.py` | Selector cache keyed by host+schema and by page-content hash |
| `db.py` | SQLite/Postgres connection + dialect abstraction |
| `storage.py` | Sites, runs, records (time series), change log |
| `monitor.py` | Change detection + sync/async runners |
| `scheduler.py` | Polling daemon that runs due sites |
| `alerts.py` | Webhook / Slack / email sinks + threshold rules |
| `schemas.py` | Unified registry: built-in verticals + user YAML/JSON schemas |
| `verticals/ecommerce.py` | Ready-made `product` and `product_list` schemas |
| `cli.py` / `api.py` | Typer CLI + FastAPI dashboard |

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
# optional extras
pip install -e '.[js]' && playwright install chromium   # JS rendering
pip install -e '.[postgres]'                              # Postgres backend
```

## Usage

```bash
# One-off scrape (prints confidence + validity + LLM spend)
crawlr scrape https://example-store.com/search?q=laptop --schema product_list

# Monitor sites
crawlr add https://example-store.com/product/123 --schema product --interval 30
crawlr monitor                       # run all due sites once (concurrently)
crawlr monitor --daemon --poll 60    # run continuously (built-in scheduler)

# Schemas
crawlr schemas                       # list built-in + user schemas
crawlr validate-schema ./my-schema.yaml

# Inspect + dashboard
crawlr sites
crawlr changes
crawlr serve                         # http://127.0.0.1:8000
```

### Defining a custom schema (no code)

Drop a YAML file into `CRAWLR_SCHEMA_DIR` (default `<data dir>/schemas`):

```yaml
name: jobs
item_selector: ".job-card"
fields:
  - name: title
    description: the job title
    type: text
    required: true
  - name: salary
    description: annual salary
    type: number
```

Then `crawlr scrape <url> --schema jobs`.

## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `CRAWLR_DATA_DIR` | `./.crawlr` | SQLite DB, selector cache, schemas |
| `CRAWLR_DATABASE_URL` | — | `postgresql://...` to use Postgres instead of SQLite |
| `CRAWLR_SCHEMA_DIR` | `<data>/schemas` | Directory scanned for user YAML/JSON schemas |
| `CRAWLR_LLM_PROVIDER` | `none` | `openai`, `anthropic`, or `none` (heuristic) |
| `CRAWLR_LLM_API_KEY` | — | API key for the chosen provider |
| `CRAWLR_LLM_MODEL` | provider default | Model override |
| `CRAWLR_LLM_MAX_CALLS` | `2` | Max LLM calls per scrape (cost guardrail) |
| `CRAWLR_PROXIES` | — | Comma-separated proxy URLs to rotate through |
| `CRAWLR_RESPECT_ROBOTS` | `true` | Honor robots.txt |
| `CRAWLR_JITTER` | `0.75` | Max random extra delay (s) per request |
| `CRAWLR_ROTATE_UA` | `false` | Rotate realistic User-Agent strings |
| `CRAWLR_ALERT_WEBHOOK` | — | Generic webhook URL for change alerts |
| `CRAWLR_ALERT_SLACK` | — | Slack incoming-webhook URL |
| `CRAWLR_ALERT_EMAIL_TO` | — | Comma-separated recipient emails |
| `CRAWLR_SMTP_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_FROM` | — | SMTP settings for email alerts |
| `CRAWLR_ALERT_MIN_DROP` | `0.0` | Only alert on price drops ≥ this fraction (0.1 = 10%) |

## Docker

```bash
# Dashboard + Postgres + background scheduler
docker compose up --build
# Dashboard at http://localhost:8000
```

## Development

```bash
pip install -e '.[dev]'
pytest        # offline test suite (extraction, self-heal, validation, alerts, schemas, async, dashboard)
ruff check .  # lint
```

The test suite runs fully offline (no network, no LLM key): `fetch` is
monkeypatched with local fixtures and selector generation uses the heuristic
path. The same portable SQL is exercised on SQLite in CI and on Postgres in
production.

## Website &amp; docs

Crawlr is a **command-line product**. The `web/` directory is a static showcase + docs
site (what Crawlr does, how to use it, and reference documentation) — it deploys free on
Vercel:

1. Import the repo at [vercel.com/new](https://vercel.com/new).
2. Set **Root Directory** to `web`.
3. Framework preset: **Other** (no build step — it's static HTML/CSS).
4. Deploy. You get a public URL like `https://crawlr.vercel.app`.

Locally you can preview it with any static server, e.g. `python -m http.server -d web 3000`.

## Roadmap

- Additional verticals shipped as YAML presets
- Richer dashboard charts and filtering
- Distributed workers / task queue for very large fleets
