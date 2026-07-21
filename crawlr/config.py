"""Runtime configuration loaded from environment variables / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Root directory where the tool stores its database, selector cache, snapshots.
DATA_DIR = Path(os.getenv("CRAWLR_DATA_DIR", "./.crawlr")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "crawlr.db"

# Optional database URL. When it starts with "postgres", the Postgres backend is
# used; otherwise Crawlr falls back to the local SQLite file above.
DATABASE_URL = os.getenv("CRAWLR_DATABASE_URL", "") or None

# Max size of the Postgres connection pool (only used when the optional
# `psycopg_pool` package is installed; otherwise a direct connection is opened).
PG_POOL_MAX = int(os.getenv("CRAWLR_PG_POOL_MAX", "10"))

# Data retention: keep at most this many most-recent runs per site (older runs
# and their records are pruned automatically after each scrape). 0 = keep all.
RETENTION_RUNS = int(os.getenv("CRAWLR_RETENTION_RUNS", "0"))

# Directory scanned for user-defined YAML/JSON schema files.
SCHEMA_DIR = Path(os.getenv("CRAWLR_SCHEMA_DIR", str(DATA_DIR / "schemas"))).resolve()

# User-editable rules template: "in circumstance X, do action Y" for alerts.
RULES_FILE = Path(os.getenv("CRAWLR_RULES_FILE", "crawlr.rules.yaml")).resolve()

# Plausibility guard: price changes beyond this factor (e.g. >20x or <1/20x) are
# treated as likely extraction errors and suppressed from alerts.
MAX_PRICE_CHANGE_FACTOR = float(os.getenv("CRAWLR_MAX_PRICE_FACTOR", "20"))

# Reliability: archive raw HTML snapshots for offline re-extraction & debugging.
ARCHIVE_ENABLED = os.getenv("CRAWLR_ARCHIVE", "true").lower() == "true"
SNAPSHOT_DIR = Path(os.getenv("CRAWLR_SNAPSHOT_DIR", str(DATA_DIR / "snapshots"))).resolve()

# Only alert on field changes whose extraction confidence is at least this
# (0.0 disables the gate). Uses per-field consensus confidence.
MIN_FIELD_CONFIDENCE = float(os.getenv("CRAWLR_MIN_FIELD_CONFIDENCE", "0.0"))

# Anomaly guard: quarantine a price change when it's a statistical outlier vs the
# item's own history (robust z-score via MAD). 0 disables. The guard only kicks
# in once there are at least ANOMALY_MIN_SAMPLES prior points, so thin history is
# never quarantined. These are the *global defaults*; each watch can override
# them (and RETENTION_RUNS) per-site — see the sites table / `crawlr watch`.
ANOMALY_ZSCORE = float(os.getenv("CRAWLR_ANOMALY_ZSCORE", "6.0"))
ANOMALY_MIN_SAMPLES = int(os.getenv("CRAWLR_ANOMALY_MIN_SAMPLES", "6"))

# ---------------------------------------------------------------------------
# Currency conversion (multi-currency comparison)
# ---------------------------------------------------------------------------

# Base/reporting currency that mixed-currency comparisons convert into.
FX_BASE = os.getenv("CRAWLR_FX_BASE", "USD").strip().upper() or "USD"

# When true, refresh FX rates from a public API (cached to disk with a TTL),
# falling back to the pinned offline table on any failure. Left false, Crawlr
# converts using the pinned rates only — fully offline and deterministic.
FX_LIVE = os.getenv("CRAWLR_FX_LIVE", "false").lower() == "true"

# Live FX endpoint. Must return JSON with a top-level {"rates": {CODE: rate}}
# object expressed as units-per-USD (the open.er-api.com / exchangerate shape).
FX_API_URL = os.getenv("CRAWLR_FX_API_URL", "https://open.er-api.com/v6/latest/USD")

# How long (hours) a cached live-rate snapshot stays fresh before we refetch.
FX_CACHE_HOURS = float(os.getenv("CRAWLR_FX_CACHE_HOURS", "12"))

# Cached live-rate snapshot lives alongside the DB / selector cache.
FX_CACHE_PATH = DATA_DIR / "fx_rates.json"

# Optional pinned-rate overrides, e.g. "EUR=0.92,GBP=0.79" (units per USD).
# Applied on top of the built-in pinned table; handy for reproducible reports.
FX_RATES_OVERRIDE = os.getenv("CRAWLR_FX_RATES", "")

# ---------------------------------------------------------------------------
# Remote fetch provider (unblocking / JS-render API)
# ---------------------------------------------------------------------------

# Big marketplaces block direct requests. Instead of fighting anti-bot ourselves,
# route fetches through a third-party rendering/unblocking API that returns clean
# HTML. "direct" (default) fetches ourselves. Built-in presets: scraperapi,
# scrapingbee, zyte. Use "custom" to wire up any URL-in / HTML-out service.
FETCH_PROVIDER = os.getenv("CRAWLR_FETCH_PROVIDER", "direct").strip().lower()
FETCH_PROVIDER_KEY = os.getenv("CRAWLR_FETCH_PROVIDER_KEY", "") or None
# Whether to ask the provider to render JavaScript (costs more credits).
FETCH_PROVIDER_RENDER = os.getenv("CRAWLR_FETCH_PROVIDER_RENDER", "true").lower() == "true"

# --- "custom" provider knobs (only needed when CRAWLR_FETCH_PROVIDER=custom) ---
FETCH_PROVIDER_ENDPOINT = os.getenv("CRAWLR_FETCH_PROVIDER_ENDPOINT", "") or None
FETCH_PROVIDER_METHOD = os.getenv("CRAWLR_FETCH_PROVIDER_METHOD", "GET").strip().upper()
# Query-param names for the target URL and API key (GET-style providers).
FETCH_PROVIDER_URL_PARAM = os.getenv("CRAWLR_FETCH_PROVIDER_URL_PARAM", "url")
FETCH_PROVIDER_KEY_PARAM = os.getenv("CRAWLR_FETCH_PROVIDER_KEY_PARAM", "") or None
# Or send the key in a header instead (e.g. "Authorization" / "X-API-Key").
FETCH_PROVIDER_KEY_HEADER = os.getenv("CRAWLR_FETCH_PROVIDER_KEY_HEADER", "") or None
# Extra static query params, e.g. "render=true&country_code=us".
FETCH_PROVIDER_EXTRA = os.getenv("CRAWLR_FETCH_PROVIDER_EXTRA", "")
# Response shape: "html" (body is raw HTML) or "json" (+ a dotted path to it).
FETCH_PROVIDER_RESPONSE = os.getenv("CRAWLR_FETCH_PROVIDER_RESPONSE", "html").strip().lower()
FETCH_PROVIDER_HTML_PATH = os.getenv("CRAWLR_FETCH_PROVIDER_HTML_PATH", "")

# ---------------------------------------------------------------------------
# JavaScript rendering (headless browser via the optional `js` extra)
# ---------------------------------------------------------------------------

# Automatically render with a headless browser when a page is blocked by
# anti-bot or looks like an empty JS shell — no --js flag needed. Requires the
# `js` extra (pip install 'crawlr[js]'). Set false to stay static-only.
AUTO_JS = os.getenv("CRAWLR_AUTO_JS", "true").lower() == "true"

# On the first JS render, auto-download the Chromium browser binary if it's
# missing (removes the manual `playwright install chromium` step). Set false to
# manage the browser install yourself.
AUTO_PLAYWRIGHT_INSTALL = (
    os.getenv("CRAWLR_AUTO_PLAYWRIGHT_INSTALL", "true").lower() == "true"
)

# On a block, retry with a real-Chrome TLS/JA3 fingerprint via the optional
# `curl_cffi` package (pip install 'crawlr[impersonate]'). This beats many
# Cloudflare/Akamai blocks without a headless browser. No-op if not installed.
IMPERSONATE = os.getenv("CRAWLR_IMPERSONATE", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Canvas: cross-retailer product search / comparison
# ---------------------------------------------------------------------------

# Optional YAML file adding your own retailers for `crawlr canvas`. Format:
#   retailers:
#     - name: My Shop
#       search_url: "https://myshop.com/search?q={q}"
CANVAS_RETAILERS_FILE = os.getenv("CRAWLR_CANVAS_RETAILERS", "") or None

# Preferred country for `crawlr canvas` (ISO-3166 alpha-2, e.g. "ph", "us").
# When set, canvas includes that country's local marketplaces (Lazada/Shopee for
# PH, etc.). If unset, canvas auto-detects it (see below) or infers it from the
# target currency (PHP -> ph).
CANVAS_COUNTRY = (os.getenv("CRAWLR_COUNTRY", "") or "").strip().lower() or None

# Auto-detect the canvas country from the machine's public IP when the user
# gives no country and no explicit currency. Fully graceful: any failure falls
# back to currency inference / global stores. Set false to disable (offline).
CANVAS_GEO = os.getenv("CRAWLR_GEO", "true").lower() == "true"
CANVAS_GEO_TIMEOUT = float(os.getenv("CRAWLR_GEO_TIMEOUT", "3.0"))
# The detected code is cached here so we don't hit the network every run.
CANVAS_GEO_CACHE_PATH = DATA_DIR / "geo_country.json"
CANVAS_GEO_CACHE_HOURS = float(os.getenv("CRAWLR_GEO_CACHE_HOURS", "168"))  # 7 days

# How many matching listings to keep per store (more = a fuller comparison).
CANVAS_PER_STORE = max(1, int(os.getenv("CRAWLR_CANVAS_PER_STORE", "6")))
# Search retailers concurrently with up to this many worker threads (1 = serial).
CANVAS_WORKERS = max(1, int(os.getenv("CRAWLR_CANVAS_WORKERS", "10")))
# Structured-API probe timeout (seconds) — shorter than the full fetch timeout so
# stores without a usable API fail fast instead of stalling the whole search.
CANVAS_API_TIMEOUT = float(os.getenv("CRAWLR_CANVAS_API_TIMEOUT", "8"))
# Keep expanding the query (plural/singular, drop brand/model, no-space, …) and
# retrying until at least this many products are found. 0 disables expansion.
CANVAS_MIN_RESULTS = max(0, int(os.getenv("CRAWLR_CANVAS_MIN_RESULTS", "20")))
# Persist every canvas result to build cross-store price history, so canvas can
# flag all-time lows and "% below the usual price". Set false to disable.
CANVAS_HISTORY = os.getenv("CRAWLR_CANVAS_HISTORY", "true").lower() == "true"
# How many days of canvas price history to consider when scoring a deal.
CANVAS_HISTORY_DAYS = max(0, int(os.getenv("CRAWLR_CANVAS_HISTORY_DAYS", "90")))

# Hosted API: when set, the JSON API requires this key (X-API-Key or Bearer).
# Left unset, the API is open (fine for local use).
API_KEY = os.getenv("CRAWLR_API_KEY", "") or None

# Interactive Telegram bot front-end for canvas (`crawlr telegram-bot`). Create a
# bot via @BotFather and put its token here. Separate from the alert-sink token.
TELEGRAM_BOT_TOKEN = os.getenv("CRAWLR_TELEGRAM_BOT_TOKEN") or None


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for the pluggable LLM provider.

    Supported providers: "openai", "anthropic", or "none" (heuristic fallback).
    Crawlr works fully offline with the heuristic provider; supplying an API
    key unlocks the higher-accuracy LLM selector generation.
    """

    provider: str = os.getenv("CRAWLR_LLM_PROVIDER", "none").lower()
    api_key: str | None = os.getenv("CRAWLR_LLM_API_KEY") or None
    model: str = os.getenv("CRAWLR_LLM_MODEL", "")
    base_url: str | None = os.getenv("CRAWLR_LLM_BASE_URL") or None
    timeout_seconds: float = float(os.getenv("CRAWLR_LLM_TIMEOUT", "60"))
    # Cost guardrails: hard cap on LLM calls within a single scrape, and an
    # estimated price per 1K tokens used only for spend reporting.
    max_calls_per_run: int = int(os.getenv("CRAWLR_LLM_MAX_CALLS", "2"))
    price_per_1k_tokens: float = float(os.getenv("CRAWLR_LLM_PRICE_PER_1K", "0.00015"))

    @property
    def enabled(self) -> bool:
        return self.provider in {"openai", "anthropic"} and bool(self.api_key)


@dataclass(frozen=True)
class FetchConfig:
    user_agent: str = os.getenv(
        "CRAWLR_USER_AGENT",
        "Mozilla/5.0 (compatible; Crawlr/0.1; +https://example.com/bot)",
    )
    timeout_seconds: float = float(os.getenv("CRAWLR_FETCH_TIMEOUT", "30"))
    max_retries: int = int(os.getenv("CRAWLR_FETCH_RETRIES", "3"))
    # Respect politeness: minimum delay between requests to the same host.
    min_delay_seconds: float = float(os.getenv("CRAWLR_MIN_DELAY", "1.0"))


@dataclass(frozen=True)
class AntiBotConfig:
    """Anti-bot resilience knobs."""

    # Comma-separated proxy URLs, e.g. "http://user:pass@host:port,http://host2:port".
    proxies: list[str] = field(
        default_factory=lambda: _split_csv(os.getenv("CRAWLR_PROXIES", ""))
    )
    respect_robots: bool = os.getenv("CRAWLR_RESPECT_ROBOTS", "true").lower() == "true"
    # Random extra delay (0..jitter seconds) added on top of min_delay per request.
    jitter_seconds: float = float(os.getenv("CRAWLR_JITTER", "0.75"))
    # Rotate through a small pool of realistic UA strings if enabled.
    rotate_user_agents: bool = os.getenv("CRAWLR_ROTATE_UA", "false").lower() == "true"


@dataclass(frozen=True)
class AlertConfig:
    """Notification sinks + thresholds for change alerts."""

    webhook_url: str | None = os.getenv("CRAWLR_ALERT_WEBHOOK") or None
    # Optional shared secret: when set, generic-webhook payloads are signed with
    # an `X-Crawlr-Signature: sha256=<hmac>` header so receivers can verify them.
    webhook_secret: str | None = os.getenv("CRAWLR_WEBHOOK_SECRET") or None
    slack_webhook_url: str | None = os.getenv("CRAWLR_ALERT_SLACK") or None
    discord_webhook_url: str | None = os.getenv("CRAWLR_ALERT_DISCORD") or None
    teams_webhook_url: str | None = os.getenv("CRAWLR_ALERT_TEAMS") or None
    # ntfy.sh (or self-hosted) topic URL, e.g. https://ntfy.sh/my-crawlr-alerts.
    ntfy_url: str | None = os.getenv("CRAWLR_ALERT_NTFY") or None
    # Telegram bot alerts: create a bot via @BotFather, then set the token and
    # your chat id (get it from @userinfobot). Free push notifications to phone.
    telegram_bot_token: str | None = os.getenv("CRAWLR_ALERT_TELEGRAM_TOKEN") or None
    telegram_chat_id: str | None = os.getenv("CRAWLR_ALERT_TELEGRAM_CHAT_ID") or None
    email_to: list[str] = field(
        default_factory=lambda: _split_csv(os.getenv("CRAWLR_ALERT_EMAIL_TO", ""))
    )
    smtp_host: str | None = os.getenv("CRAWLR_SMTP_HOST") or None
    smtp_port: int = int(os.getenv("CRAWLR_SMTP_PORT", "587"))
    smtp_user: str | None = os.getenv("CRAWLR_SMTP_USER") or None
    smtp_password: str | None = os.getenv("CRAWLR_SMTP_PASSWORD") or None
    smtp_from: str | None = os.getenv("CRAWLR_SMTP_FROM") or None
    # Only alert on price drops of at least this fraction (0.1 == 10%).
    min_price_drop_pct: float = float(os.getenv("CRAWLR_ALERT_MIN_DROP", "0.0"))
    # Suppress a repeat alert for the same (site, item, field) within this many
    # minutes, so a flapping value can't spam you. 0 disables throttling.
    throttle_minutes: int = int(os.getenv("CRAWLR_ALERT_THROTTLE_MINUTES", "0"))
    # Echo alerts to the console/log even when no sink is configured.
    console: bool = os.getenv("CRAWLR_ALERT_CONSOLE", "true").lower() == "true"


LLM = LLMConfig()
FETCH = FetchConfig()
ANTIBOT = AntiBotConfig()
ALERTS = AlertConfig()
