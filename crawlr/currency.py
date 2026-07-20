"""Multi-currency conversion with a pinned offline table and optional live FX.

Comparing the same product across shops that price in different currencies needs
a common denominator. Crawlr ships a *pinned* rate table (expressed as units per
1 USD) so conversion works fully offline and deterministically. Set
``CRAWLR_FX_LIVE=true`` to refresh rates from a public API instead; live rates
are cached to disk with a TTL and we fall back to the pinned table on any
failure, so conversion never hard-depends on the network.

All rates are stored USD-relative (``rate[C]`` = how many units of ``C`` one USD
buys), which makes any pair convertible: ``to_amount = amount / rate[from] * rate[to]``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from . import config

logger = logging.getLogger("crawlr.currency")

# Pinned, USD-relative reference rates (units per 1 USD). These are deliberately
# approximate — they make offline comparison possible without pretending to be a
# real-time trading feed. Enable CRAWLR_FX_LIVE for up-to-date figures.
_PINNED_RATES: dict[str, float] = {
    "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 156.0, "INR": 83.3,
    "PHP": 58.5, "BRL": 5.4, "AUD": 1.51, "CAD": 1.36, "CNY": 7.24,
    "KRW": 1370.0, "RUB": 90.0, "NZD": 1.65, "CHF": 0.89, "SEK": 10.6,
    "MXN": 18.5, "SGD": 1.35, "HKD": 7.81,
}


def _parse_overrides(raw: str) -> dict[str, float]:
    """Parse ``"EUR=0.92,GBP=0.79"`` into a rates dict (bad entries ignored)."""
    out: dict[str, float] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        code, _, value = pair.partition("=")
        try:
            out[code.strip().upper()] = float(value)
        except ValueError:
            logger.warning("Ignoring invalid FX override %r", pair)
    return out


def pinned_rates() -> dict[str, float]:
    """The built-in pinned table merged with any ``CRAWLR_FX_RATES`` overrides."""
    rates = dict(_PINNED_RATES)
    rates.update(_parse_overrides(config.FX_RATES_OVERRIDE))
    rates["USD"] = 1.0  # anchor: everything is USD-relative
    return rates


def _read_cache() -> dict | None:
    path = config.FX_CACHE_PATH
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _cache_is_fresh(cached: dict) -> bool:
    ts = cached.get("fetched_at")
    if not ts:
        return False
    try:
        fetched = datetime.fromisoformat(ts)
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0
    return age_hours < max(0.0, config.FX_CACHE_HOURS)


def _write_cache(rates: dict[str, float]) -> None:
    try:
        config.FX_CACHE_PATH.write_text(
            json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "rates": rates}),
            "utf-8",
        )
    except OSError as exc:  # pragma: no cover - disk-only failure
        logger.warning("Could not cache FX rates: %s", exc)


def _fetch_live_rates() -> dict[str, float] | None:
    """Fetch USD-relative rates from the configured API. None on any failure."""
    try:
        import httpx

        resp = httpx.get(config.FX_API_URL, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # pragma: no cover - network/parse failure
        logger.warning("Live FX fetch failed (%s); using pinned rates.", exc)
        return None
    raw = data.get("rates") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return None
    rates: dict[str, float] = {}
    for code, value in raw.items():
        try:
            rates[str(code).upper()] = float(value)
        except (TypeError, ValueError):
            continue
    if "USD" not in rates or rates.get("USD", 0) <= 0:
        return None
    return rates


def get_rates() -> tuple[dict[str, float], str]:
    """Return ``(rates, source)`` where source is ``live`` | ``cached`` | ``pinned``.

    Pinned overrides are always layered on top so a user can force a specific
    rate for a currency even when live rates are enabled.
    """
    base = pinned_rates()
    if not config.FX_LIVE:
        return base, "pinned"

    cached = _read_cache()
    if cached and _cache_is_fresh(cached) and isinstance(cached.get("rates"), dict):
        base.update({k: float(v) for k, v in cached["rates"].items()})
        base.update(_parse_overrides(config.FX_RATES_OVERRIDE))
        return base, "cached"

    live = _fetch_live_rates()
    if live:
        _write_cache(live)
        base.update(live)
        base.update(_parse_overrides(config.FX_RATES_OVERRIDE))
        return base, "live"

    # Live requested but unavailable: fall back to a stale cache, else pinned.
    if cached and isinstance(cached.get("rates"), dict):
        base.update({k: float(v) for k, v in cached["rates"].items()})
        base.update(_parse_overrides(config.FX_RATES_OVERRIDE))
        return base, "cached"
    return base, "pinned"


def supported(rates: dict[str, float] | None = None) -> set[str]:
    """Currency codes we can convert between with the active rate table."""
    return set((rates or pinned_rates()).keys())


def convert(
    amount: float | None,
    from_ccy: str | None,
    to_ccy: str,
    rates: dict[str, float] | None = None,
) -> float | None:
    """Convert ``amount`` from ``from_ccy`` to ``to_ccy``; None if not possible.

    A missing/unknown source or target currency returns None rather than a
    misleading number, so callers can fall back to a currency-safe comparison.
    """
    if amount is None or from_ccy is None:
        return None
    table = rates if rates is not None else pinned_rates()
    src = str(from_ccy).upper()
    dst = str(to_ccy).upper()
    rate_from = table.get(src)
    rate_to = table.get(dst)
    if not rate_from or not rate_to:
        return None
    if src == dst:
        return round(float(amount), 4)
    return round(float(amount) / rate_from * rate_to, 4)
