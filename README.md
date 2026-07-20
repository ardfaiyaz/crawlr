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
| `crawlr --version` | Print the installed Crawlr version (also `-V`) |

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
| `CRAWLR_AUTO_JS` | `true` | Auto-render blocked / JS-only pages with the built-in headless browser |
| `CRAWLR_AUTO_PLAYWRIGHT_INSTALL` | `true` | Auto-download the Chromium browser binary on first JS render |
| `CRAWLR_FX_BASE` | `USD` | Currency that `compare` converts prices into |
| `CRAWLR_FX_LIVE` | `false` | Fetch live FX rates (cached) instead of the pinned table |
| `CRAWLR_FX_API_URL` | `open.er-api.com` | Live FX endpoint (`{"rates": {CODE: perUSD}}`) |
| `CRAWLR_FX_RATES` | — | Pinned rate overrides, e.g. `EUR=0.92,GBP=0.79` |
| `CRAWLR_FETCH_PROVIDER` | `direct` | Unblocking/render backend: `scraperapi`, `scrapingbee`, `zyte`, `custom`, or `direct` |
| `CRAWLR_FETCH_PROVIDER_KEY` | — | API key for the chosen provider |
| `CRAWLR_FETCH_PROVIDER_RENDER` | `true` | Ask the provider to render JavaScript (costs more credits) |
| `CRAWLR_CANVAS_RETAILERS` | — | Path to a YAML file adding your own stores to `crawlr canvas` |
| `CRAWLR_COUNTRY` | — | Default country for `crawlr canvas` local stores (ISO code, e.g. `ph`, `us`) |
| `CRAWLR_GEO` | `true` | Auto-detect the canvas country from your IP when no country/currency is given |
| `CRAWLR_GEO_TIMEOUT` | `3.0` | Seconds to wait for the IP-geolocation lookup before falling back |
| `CRAWLR_CANVAS_PER_STORE` | `3` | How many matching listings `crawlr canvas` keeps per store |
| `CRAWLR_CANVAS_WORKERS` | `6` | Retailers searched concurrently by `crawlr canvas` (1 = serial) |

## Step-by-step setup guides

Every integration below follows the same pattern: **get the URL/key from the service, set the
variable, then run `crawlr test-alert` (for alerts) or `crawlr doctor` (for everything else) to
confirm it works.** Set variables with `export VAR=value` (macOS/Linux), `$env:VAR="value"`
(Windows PowerShell), or a `.env` file.

### Discord alerts

1. Open Discord and go to the **server** you manage where you want alerts.
2. Click the server name → **Server Settings**.
3. Go to **Integrations** → **Webhooks** → **New Webhook**.
4. Pick the channel it should post in, optionally rename it, then click **Copy Webhook URL**.
5. Set it and test:

```bash
export CRAWLR_ALERT_DISCORD="https://discord.com/api/webhooks/…"
crawlr test-alert
```

### Slack alerts

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**; pick your workspace.
2. Open **Incoming Webhooks** and turn it **On**.
3. Click **Add New Webhook to Workspace**, choose a channel, and **Allow**.
4. Copy the webhook URL, then set it:

```bash
export CRAWLR_ALERT_SLACK="https://hooks.slack.com/services/…"
```

### Telegram alerts

1. In Telegram, message **@BotFather**, send `/newbot`, and follow the prompts. Copy the **bot token**.
2. Open a chat with your new bot and send it `/start` (a bot can't message you until you do).
3. Message **@userinfobot** — it replies with your numeric **chat id**.
4. Set both:

```bash
export CRAWLR_ALERT_TELEGRAM_TOKEN="123456:ABC-your-token"
export CRAWLR_ALERT_TELEGRAM_CHAT_ID="123456789"
```

### ntfy alerts (free phone push, no account)

1. Choose a hard-to-guess topic name, e.g. `my-crawlr-a7f3`. Your URL is `https://ntfy.sh/my-crawlr-a7f3`.
2. Install the **ntfy** app (iOS/Android) — or open the URL in a browser — and **subscribe** to that topic.
3. Set it:

```bash
export CRAWLR_ALERT_NTFY="https://ntfy.sh/my-crawlr-a7f3"
```

### Microsoft Teams alerts

1. In Teams, hover the channel → **⋯** → **Workflows** (older tenants: **Connectors → Incoming Webhook**).
2. Pick the "post to a channel when a webhook request is received" template and create it.
3. Copy the generated URL and set it:

```bash
export CRAWLR_ALERT_TEAMS="https://…webhook…url…"
```

### Email alerts (SMTP)

1. Get your provider's SMTP details. For Gmail: enable 2-step verification, then create an **App Password** (Google Account → Security → App passwords).
2. Set the recipient and server:

```bash
export CRAWLR_ALERT_EMAIL_TO="you@example.com"
export CRAWLR_SMTP_HOST="smtp.gmail.com"
export CRAWLR_SMTP_PORT="587"
export CRAWLR_SMTP_USER="you@gmail.com"
export CRAWLR_SMTP_PASSWORD="your-app-password"
```

### Any generic webhook

1. Use any endpoint that accepts an HTTP POST with JSON. To try it out, grab a free URL from [webhook.site](https://webhook.site).
2. Set it (optionally sign the payloads so your receiver can verify them):

```bash
export CRAWLR_ALERT_WEBHOOK="https://webhook.site/your-id"
export CRAWLR_WEBHOOK_SECRET="any-shared-secret"   # optional; adds X-Crawlr-Signature
```

> **Tip:** enable several channels at once, add `CRAWLR_ALERT_THROTTLE_MINUTES=60` to avoid repeat
> pings, and prefer a daily summary with `crawlr digest --send`.

### AI mode — OpenAI

Crawlr runs free and offline by default; a key only helps on unusual layouts (it runs once per site).

1. Go to [platform.openai.com](https://platform.openai.com) and sign in.
2. Account menu (top-right) → **API keys** → **Create new secret key** → copy it (shown once, starts with `sk-`).
3. Add a payment method under **Settings → Billing**.
4. Set it:

```bash
export CRAWLR_LLM_PROVIDER="openai"
export CRAWLR_LLM_API_KEY="sk-..."
```

### AI mode — Anthropic

1. Go to [console.anthropic.com](https://console.anthropic.com) and sign in.
2. Open **API keys** → **Create Key** → copy it (starts with `sk-ant-`).
3. Set it:

```bash
export CRAWLR_LLM_PROVIDER="anthropic"
export CRAWLR_LLM_API_KEY="sk-ant-..."
```

### Postgres storage (free hosted)

1. Create a free project at [neon.tech](https://neon.tech) (or supabase.com / railway.app).
2. Copy the **connection string** — `postgresql://user:pass@host:5432/dbname`.
3. Install the extra and set the URL:

```bash
pip install "crawlr[postgres]"
export CRAWLR_DATABASE_URL="postgresql://user:pass@host:5432/dbname"
crawlr doctor
```

### Fetch provider (for big marketplaces)

1. Sign up at [scraperapi.com](https://www.scraperapi.com) (or scrapingbee.com / zyte.com); free trial tiers exist.
2. Copy the **API key** from the dashboard.
3. Set the backend and key, then verify:

```bash
export CRAWLR_FETCH_PROVIDER="scraperapi"   # or scrapingbee | zyte | custom
export CRAWLR_FETCH_PROVIDER_KEY="your-key"
crawlr doctor
```

### Currency conversion

`crawlr compare` / `crawlr canvas` convert prices to one currency so you can compare fairly.

```bash
export CRAWLR_FX_BASE="PHP"                     # compare everything in pesos
export CRAWLR_FX_LIVE="true"                    # live rates (cached); else pinned table
export CRAWLR_FX_RATES="EUR=0.92,GBP=0.79"      # optional: pin specific rates (units per USD)
crawlr fx --amount 100 --from EUR --to USD      # quick one-off conversion
```

### Proxies

1. Get one or more proxy URLs from your proxy provider (format `http://user:pass@host:port`).
2. Comma-separate them; Crawlr rotates between them:

```bash
export CRAWLR_PROXIES="http://user:pass@host:port,http://host2:port"
```

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
   after the page runs its scripts. **Crawlr handles this automatically** — a headless browser
   ships with it, and Crawlr transparently re-renders any page that's blocked or looks like a
   JS-only shell (no `--js` flag, no separate install). The browser binary downloads itself the
   first time it's needed. To force rendering you can still pass `--js`; to turn the automatic
   behavior off, set `CRAWLR_AUTO_JS=false`.

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
| Lazada / Shopee / Amazon product pages | ⚠️ Auto JS rendering helps; a fetch provider + proxies is most reliable, but may still get blocked |
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
crawlr canvas "Wooting 60HE"                                        # global stores
crawlr canvas "MAD60 HE" --country ph                               # Philippine stores (Lazada, Shopee, Zalora)
crawlr canvas "Wooting 60HE" --to PHP                               # infers --country ph from the currency
crawlr canvas "Wooting 60HE" --retailers amazon,ebay,newegg --to USD
```

### Shop your local marketplaces

Canvas is **location-aware**. Pass `--country` (ISO code) — or set `CRAWLR_COUNTRY`, or just use a
local currency with `--to` — and Crawlr searches that country's stores instead of the global set:

| Country | `--country` | Local stores it searches |
|---------|-------------|--------------------------|
| Philippines | `ph` | Lazada PH, Shopee PH, Zalora PH, Galleon PH, Carousell PH, AliExpress, Amazon, eBay |
| Singapore | `sg` | Lazada SG, Shopee SG, Amazon SG, AliExpress |
| Malaysia | `my` | Lazada MY, Shopee MY, AliExpress |
| Indonesia | `id` | Lazada ID, Shopee ID, Tokopedia, AliExpress |
| Thailand | `th` | Lazada TH, Shopee TH, AliExpress |
| Vietnam | `vn` | Lazada VN, Shopee VN, Tiki, AliExpress |
| United States | `us` | Amazon, eBay, Walmart, Newegg, Best Buy, Target |
| United Kingdom | `gb` | Amazon UK, eBay UK, Currys, AliExpress |
| India | `in` | Amazon IN, Flipkart, AliExpress |
| Australia | `au` | Amazon AU, eBay AU, AliExpress |
| Japan | `jp` | Amazon JP, AliExpress |
| Canada | `ca` | Amazon CA, eBay CA, Newegg CA |

**Prices are shown in your region's own currency automatically.** When a country is
detected, canvas converts every listing into that country's currency (e.g. PH → ₱ PHP) with no
`--to` needed — so you compare like-for-like. Override any time with `--to USD`.

**Many listings, ranked, in parallel.** Canvas searches all the stores concurrently and keeps the
top matches from each (default 3 per store — change with `--per-store 5`). Results that are search-page
chrome rather than real products (e.g. "Results for …") are filtered out, so what you see is accurate.
Stores that block bots are listed explicitly with a hint to enable a fetch provider.

**How the country is chosen** (first match wins):

1. `--country ph` — the flag you pass
2. `CRAWLR_COUNTRY=ph` — your saved default
3. the explicit currency you asked for (`--to PHP` → Philippines)
4. **your IP address** — Crawlr auto-detects your location (result is cached; no key needed)
5. otherwise → global stores

So in most cases you don't have to pass anything — just run `crawlr canvas "mad60 he"` and, from
the Philippines, it automatically searches Lazada PH, Shopee PH, and Zalora PH. Turn the IP lookup
off with `CRAWLR_GEO=false` (fully offline). Add your own shops any time via a YAML file
(`CRAWLR_CANVAS_RETAILERS`).

**Smart multi-strategy search.** For big marketplaces, Crawlr queries the store's own
**structured JSON search API** first (the same endpoints their apps use) — so **Lazada and Shopee
return real products with prices for free**, no fetch provider needed. If an API is unavailable it
falls back to scraping the HTML search page, auto-rendering JavaScript when required.

> **Heads-up:** the toughest marketplaces (Amazon, or Shopee from a datacenter/VPN IP) may still
> block automated requests. When that happens Crawlr says so explicitly, and a
> [fetch provider](#use-a-fetch-provider-recommended-for-marketplaces)
> (`CRAWLR_FETCH_PROVIDER` + key) is the most reliable fallback.

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
