"""Health check (`crawlr doctor`) — verify the environment in one command.

Runs a set of quick, offline-safe checks (data dir, database, schemas, LLM,
JS rendering, alert sinks, robots policy) and reports OK / WARN / FAIL so new
users can confirm their setup instantly.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass

from . import alerts, config, db, schemas, storage


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "fail"
    detail: str = ""


def run_checks() -> list[Check]:
    checks: list[Check] = []

    v = sys.version_info
    checks.append(
        Check("Python", "ok" if v >= (3, 10) else "fail", f"{v.major}.{v.minor}.{v.micro}")
    )

    try:
        probe = config.DATA_DIR / ".doctor"
        probe.write_text("ok")
        probe.unlink()
        checks.append(Check("Data directory", "ok", str(config.DATA_DIR)))
    except Exception as exc:
        checks.append(Check("Data directory", "fail", str(exc)))

    try:
        storage.init_db()
        storage.list_sites()
        checks.append(Check("Database", "ok", f"backend={db.BACKEND}"))
    except Exception as exc:
        checks.append(Check("Database", "fail", str(exc)))

    try:
        checks.append(Check("Schemas", "ok", f"{len(schemas.available())} available"))
    except Exception as exc:
        checks.append(Check("Schemas", "fail", str(exc)))

    if config.LLM.enabled:
        checks.append(
            Check("LLM provider", "ok", f"{config.LLM.provider} ({config.LLM.model or 'default'})")
        )
    else:
        checks.append(
            Check("LLM provider", "warn", "none — offline heuristic (set CRAWLR_LLM_* for accuracy)")
        )

    has_playwright = importlib.util.find_spec("playwright") is not None
    checks.append(
        Check(
            "JS rendering",
            "ok" if has_playwright else "warn",
            "playwright installed" if has_playwright else "not installed (pip install 'crawlr[js]')",
        )
    )

    provider = config.FETCH_PROVIDER
    if provider and provider != "direct":
        has_key = bool(config.FETCH_PROVIDER_KEY)
        checks.append(
            Check(
                "Fetch provider",
                "ok" if has_key else "warn",
                provider if has_key else f"{provider} (CRAWLR_FETCH_PROVIDER_KEY not set)",
            )
        )
    else:
        checks.append(
            Check("Fetch provider", "ok", "direct (set CRAWLR_FETCH_PROVIDER for marketplaces)")
        )

    sinks = alerts.configured_sinks()
    non_console = [s for s in sinks if s != "console"]
    checks.append(
        Check(
            "Alert sinks",
            "ok" if non_console else "warn",
            ", ".join(sinks) if sinks else "none (alerts won't be delivered)",
        )
    )

    checks.append(
        Check(
            "robots.txt",
            "ok",
            "respected" if config.ANTIBOT.respect_robots else "ignored (CRAWLR_RESPECT_ROBOTS=false)",
        )
    )
    return checks


def has_failures(checks: list[Check]) -> bool:
    return any(c.status == "fail" for c in checks)
