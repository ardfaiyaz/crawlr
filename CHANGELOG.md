# Changelog

All notable changes to Crawlr are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
