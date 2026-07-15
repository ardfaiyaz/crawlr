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
SELECTOR_CACHE_PATH = DATA_DIR / "selectors.json"

# Optional database URL. When it starts with "postgres", the Postgres backend is
# used; otherwise Crawlr falls back to the local SQLite file above.
DATABASE_URL = os.getenv("CRAWLR_DATABASE_URL", "") or None

# Directory scanned for user-defined YAML/JSON schema files.
SCHEMA_DIR = Path(os.getenv("CRAWLR_SCHEMA_DIR", str(DATA_DIR / "schemas"))).resolve()

# User-editable rules template: "in circumstance X, do action Y" for alerts.
RULES_FILE = Path(os.getenv("CRAWLR_RULES_FILE", "crawlr.rules.yaml")).resolve()

# Plausibility guard: price changes beyond this factor (e.g. >20x or <1/20x) are
# treated as likely extraction errors and suppressed from alerts.
MAX_PRICE_CHANGE_FACTOR = float(os.getenv("CRAWLR_MAX_PRICE_FACTOR", "20"))


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
    slack_webhook_url: str | None = os.getenv("CRAWLR_ALERT_SLACK") or None
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
    # Echo alerts to the console/log even when no sink is configured.
    console: bool = os.getenv("CRAWLR_ALERT_CONSOLE", "true").lower() == "true"


LLM = LLMConfig()
FETCH = FetchConfig()
ANTIBOT = AntiBotConfig()
ALERTS = AlertConfig()
