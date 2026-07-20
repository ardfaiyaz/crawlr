"""Canvas: find a product across many retailers and compare prices.

You know *what* you want (e.g. "Wooting 60HE") but not *where* to buy it. Canvas
searches a set of retailers, extracts the best-matching product + price from each
search-results page, converts everything into one currency, and ranks them — so
you can comparison-shop ("canvas") in a single command:

    crawlr canvas "Wooting 60HE"

Reliability on hostile marketplaces (Amazon/Lazada/Shopee) depends on a fetch
provider being configured (see CRAWLR_FETCH_PROVIDER); scrape-friendly stores
work directly. Add your own stores via a YAML file (CRAWLR_CANVAS_RETAILERS).
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin

from . import config, currency
from .extractor import scrape
from .verticals import ecommerce

logger = logging.getLogger("crawlr.canvas")


@dataclass
class Retailer:
    name: str
    search_url: str  # template containing "{q}" where the query goes


@dataclass
class CanvasHit:
    retailer: str
    title: str
    price: float | None
    currency: str | None
    url: str
    converted: float | None  # price in the base currency (None if not convertible)
    score: float             # 0..1 title-match confidence


# Global retailers that ship broadly — a sensible default anywhere.
# The marketplace ones need a fetch provider to reliably get past anti-bot;
# scrape-friendly stores work directly.
_GLOBAL: dict[str, Retailer] = {
    "amazon": Retailer("Amazon", "https://www.amazon.com/s?k={q}"),
    "ebay": Retailer("eBay", "https://www.ebay.com/sch/i.html?_nkw={q}"),
    "walmart": Retailer("Walmart", "https://www.walmart.com/search?q={q}"),
    "newegg": Retailer("Newegg", "https://www.newegg.com/p/pl?d={q}"),
    "aliexpress": Retailer("AliExpress", "https://www.aliexpress.com/wholesale?SearchText={q}"),
}

# Local marketplaces by country (ISO-3166 alpha-2). AliExpress ships worldwide,
# so it's added to most regions as a fallback option.
_ALIEXPRESS = _GLOBAL["aliexpress"]
_REGIONS: dict[str, dict[str, Retailer]] = {
    "ph": {
        "lazada": Retailer("Lazada PH", "https://www.lazada.com.ph/catalog/?q={q}"),
        "shopee": Retailer("Shopee PH", "https://shopee.ph/search?keyword={q}"),
        "zalora": Retailer("Zalora PH", "https://www.zalora.com.ph/search/?q={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "sg": {
        "lazada": Retailer("Lazada SG", "https://www.lazada.sg/catalog/?q={q}"),
        "shopee": Retailer("Shopee SG", "https://shopee.sg/search?keyword={q}"),
        "amazon": Retailer("Amazon SG", "https://www.amazon.sg/s?k={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "my": {
        "lazada": Retailer("Lazada MY", "https://www.lazada.com.my/catalog/?q={q}"),
        "shopee": Retailer("Shopee MY", "https://shopee.com.my/search?keyword={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "id": {
        "lazada": Retailer("Lazada ID", "https://www.lazada.co.id/catalog/?q={q}"),
        "shopee": Retailer("Shopee ID", "https://shopee.co.id/search?keyword={q}"),
        "tokopedia": Retailer("Tokopedia", "https://www.tokopedia.com/search?q={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "th": {
        "lazada": Retailer("Lazada TH", "https://www.lazada.co.th/catalog/?q={q}"),
        "shopee": Retailer("Shopee TH", "https://shopee.co.th/search?keyword={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "vn": {
        "lazada": Retailer("Lazada VN", "https://www.lazada.vn/catalog/?q={q}"),
        "shopee": Retailer("Shopee VN", "https://shopee.vn/search?keyword={q}"),
        "tiki": Retailer("Tiki", "https://tiki.vn/search?q={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "us": {
        "amazon": _GLOBAL["amazon"],
        "ebay": _GLOBAL["ebay"],
        "walmart": _GLOBAL["walmart"],
        "newegg": _GLOBAL["newegg"],
        "bestbuy": Retailer("Best Buy", "https://www.bestbuy.com/site/searchpage.jsp?st={q}"),
    },
    "gb": {
        "amazon": Retailer("Amazon UK", "https://www.amazon.co.uk/s?k={q}"),
        "ebay": Retailer("eBay UK", "https://www.ebay.co.uk/sch/i.html?_nkw={q}"),
        "currys": Retailer("Currys", "https://www.currys.co.uk/search?q={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "in": {
        "amazon": Retailer("Amazon IN", "https://www.amazon.in/s?k={q}"),
        "flipkart": Retailer("Flipkart", "https://www.flipkart.com/search?q={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "au": {
        "amazon": Retailer("Amazon AU", "https://www.amazon.com.au/s?k={q}"),
        "ebay": Retailer("eBay AU", "https://www.ebay.com.au/sch/i.html?_nkw={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "jp": {
        "amazon": Retailer("Amazon JP", "https://www.amazon.co.jp/s?k={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "ca": {
        "amazon": Retailer("Amazon CA", "https://www.amazon.ca/s?k={q}"),
        "ebay": Retailer("eBay CA", "https://www.ebay.ca/sch/i.html?_nkw={q}"),
        "newegg": Retailer("Newegg CA", "https://www.newegg.ca/p/pl?d={q}"),
    },
}

# Infer a country from the target currency when one isn't given explicitly.
_CCY_COUNTRY: dict[str, str] = {
    "PHP": "ph", "SGD": "sg", "MYR": "my", "IDR": "id", "THB": "th",
    "VND": "vn", "USD": "us", "GBP": "gb", "INR": "in", "AUD": "au",
    "JPY": "jp", "CAD": "ca",
}

# Minimum title-similarity for a search result to count as "the product".
_MATCH_THRESHOLD = 0.3


def _load_user_retailers() -> dict[str, Retailer]:
    path = config.CANVAS_RETAILERS_FILE
    if not path:
        return {}
    import pathlib

    import yaml

    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return {}
    out: dict[str, Retailer] = {}
    for entry in data.get("retailers", []):
        name = entry.get("name")
        search_url = entry.get("search_url")
        if name and search_url and "{q}" in search_url:
            out[name.lower()] = Retailer(name, search_url)
    return out


# --- IP geolocation (best-effort country auto-detection) --------------------

# Endpoints tried in order; each returns JSON with an ISO country code under the
# given key. All free / keyless. Any failure just moves on to the next.
_GEO_ENDPOINTS: list[tuple[str, str]] = [
    ("https://ipapi.co/json/", "country_code"),
    ("https://ipwho.is/", "country_code"),
    ("http://ip-api.com/json/", "countryCode"),
]


def _read_geo_cache() -> str | None:
    """Return the cached country code if present and still fresh, else None."""
    p = config.CANVAS_GEO_CACHE_PATH
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    ts, code = data.get("fetched_at"), data.get("country")
    if not ts or not code:
        return None
    try:
        fetched = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0
    if age_hours >= max(0.0, config.CANVAS_GEO_CACHE_HOURS):
        return None
    return str(code).lower()


def _write_geo_cache(code: str) -> None:
    try:
        config.CANVAS_GEO_CACHE_PATH.write_text(
            json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "country": code}),
            "utf-8",
        )
    except OSError as exc:  # pragma: no cover - disk-only failure
        logger.warning("Could not cache geo country: %s", exc)


def _lookup_ip_country() -> str | None:
    """Query the geolocation endpoints. Returns a lowercase ISO code or None."""
    try:
        import httpx
    except Exception:  # pragma: no cover - httpx is a hard dependency
        return None
    for url, key in _GEO_ENDPOINTS:
        try:
            resp = httpx.get(url, timeout=config.CANVAS_GEO_TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # network/parse failure -> try the next endpoint
            logger.debug("Geo lookup via %s failed: %s", url, exc)
            continue
        code = data.get(key) if isinstance(data, dict) else None
        if isinstance(code, str) and len(code) == 2 and code.isalpha():
            return code.lower()
    logger.info("Canvas: IP geolocation unavailable; falling back.")
    return None


def detect_country_by_ip() -> str | None:
    """Best-effort ISO country code from the machine's public IP.

    Cached to disk (see CRAWLR_GEO_CACHE_HOURS). Any failure returns None so
    callers fall back gracefully. Disable entirely with CRAWLR_GEO=false.
    """
    if not config.CANVAS_GEO:
        return None
    cached = _read_geo_cache()
    if cached:
        return cached
    code = _lookup_ip_country()
    if code:
        _write_geo_cache(code)
    return code


def _resolve_country(
    country: str | None,
    explicit_ccy: str | None,
    use_geo: bool,
) -> tuple[str | None, str]:
    """Return ``(country_code, source)``.

    Priority: explicit ``--country`` > ``CRAWLR_COUNTRY`` > explicit ``--to``
    currency > IP geolocation > default reporting currency (``CRAWLR_FX_BASE``).
    ``source`` is one of flag/env/currency/ip/currency-default/global.
    """
    if country and country.strip():
        return country.strip().lower(), "flag"
    if config.CANVAS_COUNTRY:
        return config.CANVAS_COUNTRY, "env"
    if explicit_ccy:
        c = _CCY_COUNTRY.get(explicit_ccy.upper())
        if c:
            return c, "currency"
    if use_geo:
        c = detect_country_by_ip()
        if c:
            return c, "ip"
    c = _CCY_COUNTRY.get(config.FX_BASE)
    if c:
        return c, "currency-default"
    return None, "global"


def resolve_country(country: str | None = None, base_ccy: str | None = None) -> str | None:
    """Work out which country's marketplaces to use (no network lookup).

    Priority: explicit ``country`` arg > ``CRAWLR_COUNTRY`` env > inferred from
    the target currency (e.g. PHP -> ph). Returns ``None`` if nothing matches.
    For IP auto-detection, use :func:`detect_country_by_ip` (invoked by
    :func:`search`).
    """
    if country and country.strip():
        return country.strip().lower()
    if config.CANVAS_COUNTRY:
        return config.CANVAS_COUNTRY
    if base_ccy:
        return _CCY_COUNTRY.get(base_ccy.upper())
    return None


def available_retailers(country: str | None = None) -> dict[str, Retailer]:
    """Known retailers for a country (or the global set), plus the user's YAML."""
    if country and country in _REGIONS:
        merged = dict(_REGIONS[country])
    else:
        merged = dict(_GLOBAL)
    merged.update(_load_user_retailers())  # user entries win / extend
    return merged


def _flat_catalog() -> dict[str, Retailer]:
    """Every known retailer, for resolving explicitly-named stores regardless of
    the active region. First-seen wins for shared keys (so ``lazada`` -> PH),
    then canonical global names and the user's own entries take precedence."""
    flat: dict[str, Retailer] = {}
    for region in _REGIONS.values():
        for key, r in region.items():
            flat.setdefault(key, r)
    flat.update(_GLOBAL)
    flat.update(_load_user_retailers())
    return flat


def _select(names: list[str] | None, catalog: dict[str, Retailer]) -> list[Retailer]:
    if not names:
        return list(catalog.values())
    fallback = _flat_catalog()
    chosen: list[Retailer] = []
    for n in names:
        key = n.strip().lower()
        r = catalog.get(key) or fallback.get(key)
        if r:
            chosen.append(r)
    return chosen


def _score(query: str, title: str | None) -> float:
    """0..1 confidence that ``title`` is the product named by ``query``.

    Token overlap dominates (a match should contain the query's words), with the
    character-level sequence ratio as a tie-breaker.
    """
    if not title:
        return 0.0
    q, t = query.lower().strip(), title.lower().strip()
    words = [w for w in re.split(r"\W+", q) if w]
    ratio = difflib.SequenceMatcher(None, q, t).ratio()
    if not words:
        return round(ratio, 4)
    overlap = sum(1 for w in words if w in t) / len(words)
    return round(0.8 * overlap + 0.2 * ratio, 4)


def _best_match(query: str, records: list[dict]) -> dict | None:
    best, best_score = None, 0.0
    for rec in records:
        score = _score(query, rec.get("title"))
        # Prefer results that actually carry a price.
        if isinstance(rec.get("price"), (int, float)):
            score += 0.05
        if score > best_score:
            best, best_score = rec, score
    if best is None or best_score < _MATCH_THRESHOLD:
        return None
    return {"rec": best, "score": round(min(best_score, 1.0), 2)}


def search(
    query: str,
    retailers: list[str] | None = None,
    base: str | None = None,
    country: str | None = None,
    force_js: bool = False,
) -> dict:
    """Search each retailer for ``query`` and return ranked price hits.

    ``country`` (ISO-3166 alpha-2) selects local marketplaces. When omitted, it's
    resolved in this order: ``CRAWLR_COUNTRY`` > the explicit ``base`` currency >
    IP geolocation (auto) > the default reporting currency > global stores.
    """
    base_ccy = (base or config.FX_BASE).upper()
    resolved_country, country_source = _resolve_country(
        country, explicit_ccy=base, use_geo=config.CANVAS_GEO
    )
    catalog = available_retailers(resolved_country)
    rates, fx_source = currency.get_rates()
    hits: list[CanvasHit] = []
    selected = _select(retailers, catalog)

    for retailer in selected:
        url = retailer.search_url.format(q=quote_plus(query))
        try:
            result = scrape(url, ecommerce.PRODUCT_LIST_SCHEMA, force_js=force_js)
        except Exception as exc:  # one retailer failing must not stop the canvas
            logger.warning("Canvas: %s failed: %s", retailer.name, exc)
            continue
        if getattr(result, "blocked", False):
            logger.warning("Canvas: %s blocked or unreachable", retailer.name)
            continue
        match = _best_match(query, result.records)
        if match is None:
            continue
        rec = match["rec"]
        price = rec.get("price") if isinstance(rec.get("price"), (int, float)) else None
        native_ccy = rec.get("currency")
        converted = currency.convert(price, native_ccy or base_ccy, base_ccy, rates)
        hits.append(
            CanvasHit(
                retailer=retailer.name,
                title=rec.get("title") or query,
                price=price,
                currency=native_ccy,
                url=urljoin(url, rec.get("url")) if rec.get("url") else url,
                converted=converted,
                score=match["score"],
            )
        )

    # Cheapest first; hits without a convertible price sink to the bottom.
    hits.sort(key=lambda h: (h.converted is None, h.converted if h.converted is not None else 0.0))
    return {
        "query": query,
        "base": base_ccy,
        "country": resolved_country,
        "country_source": country_source,
        "fx_source": fx_source,
        "retailers_searched": [r.name for r in selected],
        "hits": hits,
    }
