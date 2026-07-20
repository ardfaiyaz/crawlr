<p align="center">
  <img src="https://raw.githubusercontent.com/ardfaiyaz/crawlr/main/crawlr-icon-logo.png" alt="crawlr" width="120" />
</p>

<h1 align="center">crawlr</h1>

<p align="center">
  An AI-powered, <strong>self-healing</strong> web scraper for e-commerce price &amp; stock monitoring.
</p>

<p align="center">
  <a href="https://pypi.org/project/crawlr/"><img src="https://img.shields.io/pypi/v/crawlr?color=2a6833" alt="PyPI version" /></a>
  <a href="https://pypi.org/project/crawlr/"><img src="https://img.shields.io/pypi/pyversions/crawlr?color=2a6833" alt="Python versions" /></a>
  <a href="https://github.com/ardfaiyaz/crawlr/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-2a6833" alt="License: MIT" /></a>
  <a href="https://01crawlr.vercel.app/"><img src="https://img.shields.io/badge/website-live-2a6833" alt="Website" /></a>
</p>

<p align="center">
  <a href="https://01crawlr.vercel.app/"><strong>Website</strong></a> &middot;
  <a href="https://pypi.org/project/crawlr/"><strong>PyPI</strong></a> &middot;
  <code>pip install crawlr</code>
</p>

---

Crawlr uses an LLM (or a free offline heuristic) **only to generate and repair CSS selectors**,
then extracts pages deterministically with those cached selectors. When a site changes its layout
and the selectors break, Crawlr detects it and **regenerates them automatically** — so your
monitoring never silently dies.

- **Runs free & offline** — no API key required; add an OpenAI/Anthropic key for higher accuracy.
- **Self-healing** — survives redesigns that break traditional scrapers.
- **Zero-config** — `crawlr watch <url>` auto-detects the right schema (product, jobs, real estate, news).
- **Price & stock alerts** — webhook (signed), Slack, Discord, Teams, Telegram, ntfy, or email, with throttling.
- **General-purpose** — e-commerce ships in; add new verticals as simple YAML.

## Install

```bash
pipx install crawlr        # or: pip install crawlr
```

## Quickstart

```bash
crawlr watch "https://store.com/product/123" --target 25   # schema auto-detected
crawlr watchlist                                           # current price, movement, stock
crawlr monitor --daemon                                    # keep checking in the background
crawlr serve                                               # optional local dashboard
```

Omit `--schema` and Crawlr detects the page type for you (product, product list, jobs,
real estate, news). Pass `--schema <name>` to override.

## Deploy with Docker

```bash
docker run -p 8000:8000 -v crawlr-data:/data ghcr.io/ardfaiyaz/crawlr   # dashboard on :8000
```

Or run the dashboard **and** a background monitor together:

```bash
docker compose up -d      # then open http://localhost:8000
```

Build locally with `docker build -t crawlr .`. Data (SQLite DB, selector cache,
snapshots) persists in the `/data` volume.

## Alert triggers

Pick one per watch with `--trigger` (or in the dashboard):

| Trigger | Alerts when |
|---------|-------------|
| `any_change` | any watched field changes |
| `price_drop` | the price goes down |
| `price_below` | price is at/below your target |
| `price_above` | price is at/above your target |
| `back_in_stock` | the item becomes available |
| `out_of_stock` | the item sells out |

For richer logic, run `crawlr init` to create an editable `crawlr.rules.yaml` that maps
circumstances to actions (and overrides per-watch triggers):

```yaml
default_action: ignore
rules:
  - when: price_drops_below
    amount: 25
    action: alert
  - when: back_in_stock
    action: alert
```

## Every option, explained

**`crawlr watch <url> [options]`** — start tracking a product page or a store's product list.

| Option | What it does |
|--------|--------------|
| `--target 500` | Ping me when the price drops to **500 or below** (also sets the trigger to `price_below`) |
| `--restock` | Ping me when the item goes from **out of stock → in stock** |
| `--trigger <name>` | Choose exactly *when* to be alerted (see the table below) |
| `--interval 60` | Check this page **every 60 minutes** (default: 60) |
| `--schema <name>` | Force the page type instead of auto-detecting: `product`, `product_list`, `jobs`, `real_estate`, `news` |

**Triggers** (`--trigger ...`), in plain English:

| Trigger | Alerts you when… |
|---------|------------------|
| `any_change` | **anything** you watch changes (price, stock, title…) |
| `price_drop` | the price goes **down** by any amount |
| `price_below` | the price is **at or below** your `--target` |
| `price_above` | the price is **at or above** your `--target` |
| `back_in_stock` | the item becomes **available** again |
| `out_of_stock` | the item **sells out** |

**The commands you'll actually use:**

| Command | What it does |
|---------|--------------|
| `crawlr watch <url>` | Start tracking a product or store page |
| `crawlr watchlist` | Show everything you track: price, change, stock, status |
| `crawlr monitor` | Check all due pages **once**, right now |
| `crawlr monitor --daemon` | Keep checking forever in the background |
| `crawlr compare <url> <url> …` | One-off price comparison across several links |
| `crawlr canvas "<product>"` | Search many stores by product name and compare prices |
| `crawlr insights <id>` | Price analytics: all-time low/high, average, "deal score" |
| `crawlr pause <id>` / `resume <id>` | Temporarily stop / restart tracking one item |
| `crawlr unwatch <id>` | Stop tracking an item and delete its history |
| `crawlr serve` | Open the web dashboard at `http://localhost:8000` |
| `crawlr doctor` | Check that your setup works |
| `crawlr test-alert` | Send a test notification so you know alerts reach you |

> The `<id>` numbers come from `crawlr watchlist` or `crawlr sites`.

## Recipes

```bash
# Track a competitor's price, alert on a 10%+ drop, check hourly
crawlr watch "https://store.com/p/123" --trigger price_drop --interval 60

# Get pinged when something is back in stock
crawlr watch "https://store.com/p/123" --restock

# Compare the same product across three shops
crawlr compare "https://a.com/p" "https://b.com/p" "https://c.com/p"

# Monitor a job board (schema auto-detected)
crawlr watch "https://boards.example/jobs" --interval 720

# Free phone alerts via ntfy.sh
export CRAWLR_ALERT_NTFY="https://ntfy.sh/my-crawlr-alerts"
crawlr monitor --daemon

# Pause / resume / remove a watch
crawlr pause 3 && crawlr resume 3 && crawlr unwatch 3

# Pipe machine-readable output into other tools
crawlr watchlist --json | jq '.[] | {title, price}'
```

## Custom schemas (no code)

Add new verticals by dropping a YAML file into your schema directory:

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

Then `crawlr scrape <url> --schema jobs`. List schemas with `crawlr schemas`.

## Configuration

Crawlr is configured with **environment variables**. Set them whichever way suits you:

| Where | How |
|-------|-----|
| macOS / Linux | `export CRAWLR_LLM_PROVIDER=openai` |
| Windows PowerShell | `$env:CRAWLR_LLM_PROVIDER="openai"` |
| A `.env` file | add `CRAWLR_LLM_PROVIDER=openai` in your project folder (loaded automatically) |

A couple of quick examples:

```bash
# Turn on AI mode for higher accuracy (optional — free heuristic is the default)
export CRAWLR_LLM_PROVIDER="openai"
export CRAWLR_LLM_API_KEY="sk-..."

# Get Discord alerts, then verify they arrive
export CRAWLR_ALERT_DISCORD="https://discord.com/api/webhooks/..."
crawlr test-alert
```

> A step-by-step version of every setting — grouped by task, with examples — lives in the
> [website docs](https://01crawlr.vercel.app/docs.html#config).

Full reference:

| Variable | Default | Description |
|----------|---------|-------------|
| `CRAWLR_LLM_PROVIDER` | `none` | `openai`, `anthropic`, or `none` (offline heuristic) |
| `CRAWLR_LLM_API_KEY` | — | API key for the chosen provider |
| `CRAWLR_DATABASE_URL` | — | `postgresql://...` to use Postgres instead of SQLite |
| `CRAWLR_ALERT_WEBHOOK` | — | Webhook URL for change alerts |
| `CRAWLR_ALERT_SLACK` | — | Slack incoming-webhook URL |
| `CRAWLR_ALERT_DISCORD` | — | Discord incoming-webhook URL |
| `CRAWLR_ALERT_TEAMS` | — | Microsoft Teams incoming-webhook URL |
| `CRAWLR_ALERT_NTFY` | — | ntfy.sh (or self-hosted) topic URL |
| `CRAWLR_ALERT_TELEGRAM_TOKEN` | — | Telegram bot token (from @BotFather) |
| `CRAWLR_ALERT_TELEGRAM_CHAT_ID` | — | Telegram chat id to send alerts to |
| `CRAWLR_WEBHOOK_SECRET` | — | HMAC-signs generic webhook payloads |
| `CRAWLR_ALERT_THROTTLE_MINUTES` | `0` | Suppress repeat alerts within N minutes |
| `CRAWLR_PROXIES` | — | Comma-separated proxy URLs to rotate |
| `CRAWLR_RESPECT_ROBOTS` | `true` | Honor robots.txt |
| `CRAWLR_FX_BASE` | `USD` | Currency that `compare` converts prices into |
| `CRAWLR_FX_LIVE` | `false` | Fetch live FX rates (cached) instead of the pinned table |
| `CRAWLR_FX_API_URL` | `open.er-api.com` | Live FX endpoint (`{"rates": {CODE: perUSD}}`) |
| `CRAWLR_FX_RATES` | — | Pinned rate overrides, e.g. `EUR=0.92,GBP=0.79` |
| `CRAWLR_FETCH_PROVIDER` | `direct` | Unblocking/render backend: `scraperapi`, `scrapingbee`, `zyte`, `custom`, or `direct` |
| `CRAWLR_FETCH_PROVIDER_KEY` | — | API key for the chosen provider |
| `CRAWLR_FETCH_PROVIDER_RENDER` | `true` | Ask the provider to render JavaScript (costs more credits) |
| `CRAWLR_CANVAS_RETAILERS` | — | Path to a YAML file adding your own stores to `crawlr canvas` |

## Examples

Ready-to-run recipes live in [`examples/`](./examples) — watch competitors, use a
custom schema, and call the hosted API from Python.

## Development

```bash
pip install -e '.[dev]'
pytest          # offline test suite
ruff check .    # lint
crawlr eval     # extraction accuracy gate
```

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md). Great first
contributions: new vertical presets, golden eval cases for sites that extract
wrong, and docs/examples.

## Demo

A short GIF is the best intro. Generate one with [VHS](https://github.com/charmbracelet/vhs):
`vhs docs/demo.tape` → `docs/demo.gif` (see [docs/DEMO.md](./docs/DEMO.md)).

## Does it work on big marketplaces (Lazada, Shopee, Amazon)?

**Short answer: it can, but they're the hardest sites to scrape — expect extra setup, and don't count on 100% reliability.**

Crawlr shines on sites with clean HTML or embedded product data (schema.org JSON-LD). Big
marketplaces are deliberately hostile to bots, in three ways — here's how to give Crawlr its
best shot:

1. **They render prices with JavaScript.** The price often isn't in the raw HTML; it loads
   after the page runs its scripts. Install the browser engine so Crawlr can render it:
   ```bash
   pip install "crawlr[js]"
   playwright install chromium
   ```
   Then pass `--js` (e.g. `crawlr watch "<url>" --js`) or let Crawlr auto-escalate when it
   detects a JS-only shell.

2. **They have anti-bot protection** (Cloudflare, CAPTCHAs, rate limits). Crawlr detects when
   it's blocked and **skips that run** instead of saving a bogus price. The most reliable way
   through is a **fetch provider** — a service that renders the page and clears anti-bot for
   you, returning clean HTML (see *Use a fetch provider* below). Rotating proxies also help:
   ```bash
   export CRAWLR_PROXIES="http://user:pass@host:port,http://host2:port"
   ```

3. **robots.txt** — many marketplaces disallow scraping these pages, and Crawlr honors
   `robots.txt` by default, so it may refuse to fetch. Only override this for sites you're
   permitted to scrape (see *Legal & responsible use* below):
   ```bash
   export CRAWLR_RESPECT_ROBOTS=false
   ```

**Rule of thumb:**

| Site type | How well it works |
|-----------|-------------------|
| Independent shops, Shopify / WooCommerce, anything with schema.org data | ✅ Works well out of the box |
| A marketplace's **official API** (if it offers one) | ✅ Most reliable — prefer this |
| Lazada / Shopee / Amazon product pages | ⚠️ Possible with `crawlr[js]` + proxies; may still get blocked |
| Pages behind a login, or a CAPTCHA on every request | ❌ Not a good fit |

**Tip:** prove the whole flow works on an easy site first, then point it at the hard one:

```bash
crawlr watch "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html" --target 60
crawlr watchlist
```

### Use a fetch provider (recommended for marketplaces)

Rather than fighting anti-bot yourself, route fetches through a rendering/unblocking service
(ScraperAPI, ScrapingBee, Zyte, or any similar "URL in → HTML out" API). Crawlr then extracts
as usual — no code changes needed:

```bash
export CRAWLR_FETCH_PROVIDER=scraperapi     # or scrapingbee | zyte | custom
export CRAWLR_FETCH_PROVIDER_KEY=your-key
crawlr doctor                               # confirms the provider is configured
```

Most providers have a free tier to start. For any service that isn't built in, use
`CRAWLR_FETCH_PROVIDER=custom` and point it at the endpoint yourself
(`CRAWLR_FETCH_PROVIDER_ENDPOINT`, `_URL_PARAM`, `_KEY_PARAM`/`_KEY_HEADER`, `_EXTRA`,
`_RESPONSE`/`_HTML_PATH`). Even more reliable and fully legal: a marketplace's **official API**.

## Canvas — shop a product across many stores

Don't have a link, just a product in mind (say a *Wooting 60HE*)? `crawlr canvas` searches
several retailers at once, grabs the best-matching result + price from each, converts everything
into one currency, and ranks them so you can comparison-shop ("canvas") in one command:

```bash
crawlr canvas "Wooting 60HE"                                        # all known retailers
crawlr canvas "Wooting 60HE" --retailers amazon,ebay,newegg --to USD
```

Built-in retailers include Amazon, eBay, Walmart, Newegg, Lazada, and AliExpress; add your own
via a YAML file (`CRAWLR_CANVAS_RETAILERS`). Marketplaces that block bots need a fetch provider
(above) to return results reliably.

## Legal & responsible use

Crawlr is a general-purpose scraping tool, and **you are responsible for how you use it.**
Before monitoring any site, make sure you comply with:

- the target site's **Terms of Service** and `robots.txt` — Crawlr honors `robots.txt`
  by default, so keep `CRAWLR_RESPECT_ROBOTS=true` unless you own the site;
- applicable laws such as the **CFAA** (US) and **GDPR/CCPA** whenever personal data is
  involved — prefer public, non-personal data and avoid collecting PII;
- reasonable **rate limits** — use sensible intervals and delays so you don't overload a site.

Crawlr is meant for legitimate uses such as tracking your own listings, price research,
and public-data monitoring. Please don't use it to bypass authentication, paywalls, or
anti-abuse protections. The maintainers provide the software "as is" and are not
responsible for how it is used (see [LICENSE](./LICENSE)).

## License

Crawlr is released under the **MIT License** — free to use, modify, and distribute,
including commercially. See [LICENSE](./LICENSE).

Building a commercial or hosted product on top of Crawlr? An **open-core** model works
well: keep the CLI and library MIT-licensed (this repo) and offer any hosted service,
team features, or premium connectors as a separate paid layer.
