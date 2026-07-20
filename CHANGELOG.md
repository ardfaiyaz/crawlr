# Changelog

All notable changes to Crawlr are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
