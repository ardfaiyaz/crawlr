# Changelog

All notable changes to Crawlr are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.0]

### Added
- **Cross-store price history + deal-over-time (the data moat).** Canvas now
  persists every result to a `canvas_prices` table keyed by product identity, and
  scores each listing against that product's own history across stores — flagging
  "N% below its usual price" or "all-time low". History accrues the more you use
  it. Configurable via `CRAWLR_CANVAS_HISTORY` (default on) and
  `CRAWLR_CANVAS_HISTORY_DAYS` (default 90). Best-effort: storage errors never
  fail a search.

## [0.8.0]

### Added
- **Multi-strategy extraction engine** (`crawlr/strategies.py`) — every store is
  parsed with a waterfall that runs automatically and merges results, so canvas
  never depends on one technique: store JSON APIs, **embedded JSON-LD**,
  **framework hydration state** (`__NEXT_DATA__`, `__NUXT__`, `__APOLLO_STATE__`,
  `__INITIAL_STATE__`/`__PRELOADED_STATE__`), a generic **inline-JSON scan**, and
  the self-healing selector extractor — all on a single fetch. The report exposes
  `strategies_used`.
- **Product-identity resolver** (`crawlr/identity.py`) — matches listings by
  GTIN/barcode → SKU + brand → brand + model code (e.g. `g502`, `60he`). Canvas
  grouping now uses it, so `--group` compares the same product across shops
  without merging different models.
- **Close the loop: `crawlr canvas --watch [--target N] [--trigger …]`** — turns a
  canvas search into tracked watches across every store it found, reusing the
  existing monitor + alert stack (Discord/Telegram/etc.).
- **Deal scoring** — every listing is scored against the cross-store median, and
  the best buy is flagged ("X% below median — good time to buy").
- **Mobile user-agent acquisition fallback** — on a block, Crawlr retries with a
  mobile UA (lighter, less protected) before escalating to a headless browser.

## [0.7.1]

### Changed
- `crawlr canvas --group` now renders a proper **table** (grouped with section
  dividers) instead of a plain list.
- **Deduplicate by canonical URL** — the same product reached via different
  tracking params (`?_psq=…`, `?_pos=…`) collapses to one listing.
- **Drop non-positive prices** — placeholder `0` prices (e.g. a Shopify
  `"0.00"`) are ignored instead of shown as `PHP 0`.
- **More accurate matching** — expanded query variants are scored against the
  *original* query (so dropping "superlight" no longer surfaces unrelated
  Logitech items), 1-character tokens are ignored, and the match threshold was
  raised. Product grouping is tighter so different models aren't merged.
- Reject "page not found" / "404" / "doesn't exist" titles as junk.

## [0.7.0]

### Added
- **Embedded JSON-LD product extraction** — canvas now reads schema.org
  `Product`/`ItemList` data from a search page's HTML (one fetch runs both
  JSON-LD and the selector extractor, merged), so stores that expose structured
  data yield real products even when CSS selectors find nothing.
- **More stores** — added Watsons and SM Store (platform auto-detected) plus
  Temu and Banggood to the Philippine set (and Temu/Banggood globally).
- **Brand-store search** — when a query names a brand, canvas also searches that
  brand's official store (Razer, Logitech, SteelSeries, ASUS, Nike, Adidas,
  Apple, Samsung, Sony, Lenovo, Acer, Canon).
- **Cross-marketplace grouping** — `crawlr canvas --group` clusters the same
  product across shops (fuzzy title match) and shows a cheapest-first price
  comparison per product, like PCPartPicker.

## [0.6.0]

### Added
- **Canvas is now a shopping aggregator.** Each store is searched with multiple
  strategies (structured JSON API first, then HTML + auto JS rendering):
  - Generic **Shopify** (`/search/suggest.json`) and **WooCommerce**
    (`/wp-json/wc/store/products`) adapters, plus a multi-strategy auto-adapter,
    unlocking many smaller PH shops (DataBlitz, DynaQuest, EasyPC, PC Express,
    GameXtreme, Villman, …).
  - Enriched Lazada/Shopee adapters return **rich product details**: original
    price, discount %, rating, reviews, units sold, official-store badge, image,
    stock.
- **Query expansion + auto-retry** — when results are below
  `CRAWLR_CANVAS_MIN_RESULTS` (default 20), canvas retries with expanded queries
  (plural/singular, drop brand/model, no-space forms) and merges/dedupes results.
- **Price intelligence** — report and CLI now show lowest/highest/average/median
  price and max savings across shops.
- **Sorting** — `--sort price|price_high|rating|reviews|popular|discount|match`.
- More results by default: `CRAWLR_CANVAS_PER_STORE` 3 → 6, `CRAWLR_CANVAS_WORKERS`
  6 → 10; new `CRAWLR_CANVAS_API_TIMEOUT` for fast structured-API probes.

### Changed
- A canvas result must link to a **distinct product page**, which robustly rejects
  search-page headings / query echoes even across expanded queries.

## [0.5.1]

### Added
- **Structured-API canvas search** — for big marketplaces, canvas now queries the
  store's own JSON search endpoint first (Lazada's `?ajax=true`, Shopee's
  `/api/v4/search/search_items`), returning real products + prices *for free*
  without a fetch provider. Falls back to HTML (auto JS-rendered) if the API is
  unavailable, so results are strictly better than before.

### Changed
- **Stricter junk filtering** — search-page headings like "View all … ads",
  "… ads in <store>", "browse …" are now rejected, so bogus rows (e.g. a fake
  "60" price scraped from a heading) no longer appear.

## [0.5.0]

### Changed
- **JavaScript rendering is now built in and automatic.** Playwright ships as a
  core dependency, so `pip install crawlr` includes the headless browser engine —
  no `crawlr[js]` extra needed. Any page that's bot-blocked or looks like a
  JS-only shell is transparently re-rendered with a real browser (no `--js` flag).
  Toggle with `CRAWLR_AUTO_JS` (default on).
- The Chromium browser binary is **auto-downloaded on first use** (removing the
  manual `playwright install chromium` step); disable with
  `CRAWLR_AUTO_PLAYWRIGHT_INSTALL=false`. The old `crawlr[js]` extra is kept as a
  no-op alias for backwards compatibility.

## [0.4.2]

### Added
- **Canvas shows many listings, ranked** — up to N matches per store (default 3;
  `--per-store`/`CRAWLR_CANVAS_PER_STORE`), with retailers searched concurrently
  (`CRAWLR_CANVAS_WORKERS`). Output shows a listing/shop count.
- **Region-aware pricing** — when a country is detected, canvas converts every
  listing into that country's own currency automatically (e.g. PH → PHP), no
  `--to` needed. Added MYR/IDR/THB/VND/TWD/AED to the pinned FX table.
- **More retailers** — PH now includes Galleon, Carousell, Amazon &amp; eBay
  (alongside Lazada/Shopee/Zalora); US adds Target.

### Changed
- **More accurate canvas matching** — search-page chrome ("Results for …", bare
  query echoes that don't link to a real product page) is filtered out, quoted
  title echoes are cleaned, and query matching normalizes forms like
  "60HE" == "60 he". Blocked/unreachable stores are reported explicitly with a
  hint to enable a fetch provider.

## [0.4.1]

### Added
- **Automatic location detection for canvas** — when you don't pass `--country`
  (and no `CRAWLR_COUNTRY`/explicit currency), Crawlr now auto-detects your
  country from your public IP and searches your local marketplaces (e.g. Lazada
  PH, Shopee PH, Zalora PH from the Philippines). The result is cached to disk;
  any lookup failure falls back gracefully to currency/global. Disable with
  `CRAWLR_GEO=false`; tune the timeout with `CRAWLR_GEO_TIMEOUT`.

## [0.4.0]

### Added
- **Multi-strategy extraction fallbacks** — product name, price, image, and other
  fields are now recovered through several strategies (structured data, cached
  selectors, and heuristic fallbacks) so more sites yield complete data.
- **Pluggable fetch-provider backend** — route fetches through an unblocking/render
  service for big marketplaces via `CRAWLR_FETCH_PROVIDER`
  (`scraperapi`/`scrapingbee`/`zyte`/`custom`) + `CRAWLR_FETCH_PROVIDER_KEY`.
- **Canvas** — `crawlr canvas "<product name>"` suggests which retailers likely
  carry a product so you can compare across stores, plus `CRAWLR_CANVAS_RETAILERS`
  to add your own stores.
- **Location-aware canvas** — `--country`/`--region` (or `CRAWLR_COUNTRY`, or
  inferred from the target currency) searches local marketplaces: Lazada/Shopee/
  Zalora for PH, and regional stores for SG/MY/ID/TH/VN/US/GB/IN/AU/JP/CA.
- **`crawlr --version`** (`-V`) prints the installed version.
- **Graceful network-error handling** — DNS/connection failures no longer crash a
  monitor run; the site is retried next cycle instead of recording bad data.
- **Step-by-step setup guides** — README and the website docs now walk through
  obtaining every credential (Discord/Slack/Telegram/ntfy/Teams/email webhooks,
  OpenAI/Anthropic keys, hosted Postgres, fetch-provider keys, proxies, FX).
- **Website icon refresh** — all UI icons migrated to the Font Awesome icon
  library with subtle, accessibility-aware animations (replacing broken CDN
  glyph images).

### Added (previously unreleased)
- **Zero-config schema detection** — `crawlr watch <url>` auto-detects product,
  product list, jobs, real estate, and news pages (JSON-LD, microdata,
  OpenGraph, and URL heuristics). `--schema` still overrides.
- **New alert channels** — Discord, Telegram, Microsoft Teams, and ntfy.sh.
- **Signed webhooks** — set `CRAWLR_WEBHOOK_SECRET` to attach an
  `X-Crawlr-Signature` HMAC header to generic-webhook payloads.
- **Alert throttling** — `CRAWLR_ALERT_THROTTLE_MINUTES` suppresses repeat
  alerts for the same item/field within a window.
- **Alert history** — dispatched alerts are recorded and shown on the dashboard
  and via `GET /api/alerts`.
- **Redesigned dashboard** — white & green iOS theme, stat cards, sparklines,
  per-item price-history charts, pause/resume/delete, background "Check now",
  a digest button, and auto-refresh.
- **Health probes** — `/healthz` and `/readyz`.
- **CLI** — `unwatch`, `pause`, `resume`, `compare`, `insights`, and `--json`
  output on `watchlist`, `sites`, `changes`, and `stats`.
- **Richer, more accurate data** — structured-data extraction now also pulls
  brand, SKU/GTIN/MPN, review count, list/original price (incl. AggregateOffer),
  currency, and more availability states; a computed discount %; per-field
  **provenance** (`structured`/`selector`/`both`) and a **data-quality** label
  (`verified`/`high`/`inferred`/`low`).
- **Price analytics** — all-time low/high, average, current-vs-average, a 0–100
  **deal score**, and **availability stats** (in-stock %, restocks) via
  `crawlr insights`, `GET /api/insights`, the dashboard detail page, and an
  all-time-low marker in the watchlist.
- **Anomaly guard** — price changes that are statistical outliers vs an item's
  own history (robust z-score/MAD) are quarantined so a glitch can't poison
  alerts or history (`CRAWLR_ANOMALY_ZSCORE`).
- **Rendering/fetch reliability** — blocked/anti-bot runs are no longer recorded
  (so a block can't create a false "price → null"/out-of-stock and the site is
  retried next cycle); **stale-page detection** flags identical content between
  checks; results now expose `blocked`, `rendered_with_js`, and `content_hash`.
- **Persisted data-quality** — each run's quality (`verified`/`inferred`/…) is
  stored and shown as a badge in the dashboard watchlist and `/api/watchlist`.
- **Multi-currency conversion** — `crawlr compare` now converts prices to a
  common currency (`--to`, or `CRAWLR_FX_BASE`) and picks the cheapest across
  currencies. A pinned offline rate table ships by default; set
  `CRAWLR_FX_LIVE=true` for live rates (cached to disk with a TTL, falling back
  to the pinned table). New `crawlr fx` command lists rates and converts values.
- **Persisted per-field provenance** — each run's per-field source map
  (`structured`/`selector`/`both`/`none`) is stored and exposed as
  `field_sources` in `/api/watchlist` and on the dashboard detail page (not just
  the record-level quality badge).
- **Per-site anomaly & retention overrides** — each watch can override the global
  anomaly z-score, minimum samples, and retention window (`crawlr watch
  --anomaly-zscore/--anomaly-min-samples/--retention-runs`, or the same fields on
  `POST /api/watch`); unset fields inherit the global config defaults.
- **Accuracy gate** — golden-fixture extraction accuracy is asserted in the test
  suite (CI), so it can't silently regress.
- **Docker** — `Dockerfile`, `docker-compose.yml`, and a GHCR publish workflow
  for `docker run ghcr.io/ardfaiyaz/crawlr`.

### Changed
- Package version is now sourced from installed metadata (no drift).
- Selector cache moved to the database; SQLite uses WAL; optional Postgres pool.

### Security
- Dashboard output is autoescaped (Jinja2), preventing HTML/JS injection from
  scraped content. API-key checks are constant-time.

## [0.1.1] - 2026-07-15
### Fixed
- Publish workflow derives the version from the git tag.

## [0.1.0] - 2026-07-15
### Added
- Initial release: self-healing extraction engine, monitoring, alerts,
  watchlist, verticals, CLI, dashboard, and hosted API.
