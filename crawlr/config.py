"""Runtime configuration loaded from environment variables / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Root directory where the tool stores its database, selector cache, snapshots.
DATA_DIR = Path(os.getenv("CRAWLR_DATA_DIR", "./.crawlr")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "crawlr.db"
SELECTOR_CACHE_PATH = DATA_DIR / "selectors.json"


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


LLM = LLMConfig()
FETCH = FetchConfig()
