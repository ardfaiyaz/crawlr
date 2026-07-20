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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urldefrag, urljoin

import httpx

from . import config, currency
from .extractor import scrape
from .verticals import ecommerce

logger = logging.getLogger("crawlr.canvas")

# A search adapter takes a query and returns product dicts
# ({title, price, currency, url}) straight from a store's JSON API — far more
# reliable than scraping a JS-rendered search page. Returns [] on any failure.
SearchAdapter = Callable[[str], list[dict]]


@dataclass
class Retailer:
    name: str
    search_url: str  # template containing "{q}" where the query goes
    adapter: SearchAdapter | None = None  # optional structured-API search


@dataclass
class CanvasHit:
    retailer: str
    title: str
    price: float | None
    currency: str | None
    url: str
    converted: float | None  # price in the base currency (None if not convertible)
    score: float             # 0..1 title-match confidence
    image: str | None = None
    rating: float | None = None       # 0..5 stars
    reviews: int | None = None        # number of ratings/reviews
    sold: int | None = None           # units sold (popularity)
    original_price: float | None = None
    discount_pct: int | None = None
    in_stock: bool | None = None
    seller: str | None = None
    official: bool = False            # official-store / mall badge


# --- Structured-API search adapters -----------------------------------------
# Big marketplaces render their search results with JavaScript, so scraping the
# HTML yields nothing. But their own apps call JSON endpoints that return clean
# product data — we use those directly (best-effort; fall back to HTML on error).


def _to_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return None
    m = re.search(r"[\d][\d,.]*", str(value))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _to_int(value: object) -> int | None:
    """Parse a count that may be formatted like '1.2k sold' or '3,455'."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not value:
        return None
    s = str(value).lower().replace(",", "").strip()
    m = re.search(r"([\d.]+)\s*([km]?)", s)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    mult = {"k": 1_000, "m": 1_000_000}.get(m.group(2), 1)
    return int(num * mult)


def _discount_pct(value: object) -> int | None:
    """Parse a discount like '-13%' or 13 into an int percentage."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return abs(int(value))
    if not value:
        return None
    m = re.search(r"(\d+)", str(value))
    return int(m.group(1)) if m else None


def _api_get(url: str, headers: dict[str, str], timeout: float | None = None) -> Any:
    """GET a JSON endpoint. Returns the decoded JSON (dict or list)."""
    resp = httpx.get(
        url,
        headers={"User-Agent": config.FETCH.user_agent, "Accept": "application/json", **headers},
        timeout=timeout or config.CANVAS_API_TIMEOUT,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.json()


def _lazada_adapter(domain: str, ccy: str) -> SearchAdapter:
    """Lazada exposes its search results as JSON via ?ajax=true."""

    def _search(query: str) -> list[dict]:
        url = (
            f"https://{domain}/catalog/?ajax=true&isFirstRequest=true&q={quote_plus(query)}"
        )
        data = _api_get(url, {"Referer": f"https://{domain}/"})
        items = ((data or {}).get("mods") or {}).get("listItems") or []
        out: list[dict] = []
        for it in items:
            name = it.get("name")
            if not name:
                continue
            purl = str(it.get("itemUrl") or it.get("productUrl") or "")
            if not purl and it.get("itemId"):
                purl = f"//{domain}/products/pdp-i{it.get('itemId')}.html"
            if purl.startswith("//"):
                purl = "https:" + purl
            image = str(it.get("image") or "")
            if image.startswith("//"):
                image = "https:" + image
            out.append(
                {
                    "title": name,
                    "price": _to_float(it.get("price") or it.get("priceShow")),
                    "original_price": _to_float(it.get("originalPrice")),
                    "discount_pct": _discount_pct(it.get("discount")),
                    "currency": ccy,
                    "url": purl,
                    "image": image or None,
                    "rating": _to_float(it.get("ratingScore")),
                    "reviews": _to_int(it.get("review")),
                    "sold": _to_int(it.get("itemSoldCntShow") or it.get("itemSoldCnt")),
                    "seller": it.get("sellerName"),
                    "official": bool(it.get("mallType") or it.get("isLazMall")),
                    "location": it.get("location"),
                }
            )
        return out

    return _search


def _shopee_adapter(domain: str, ccy: str) -> SearchAdapter:
    """Shopee's app calls /api/v4/search/search_items, which returns JSON.
    Prices come in micro-units (actual price = price / 100000)."""

    def _search(query: str) -> list[dict]:
        api = (
            f"https://{domain}/api/v4/search/search_items?by=relevancy"
            f"&keyword={quote_plus(query)}&limit=60&newest=0&order=desc"
            "&page_type=search&scenario=PAGE_GLOBAL_SEARCH&version=2"
        )
        data = _api_get(
            api,
            {
                "Referer": f"https://{domain}/search?keyword={quote_plus(query)}",
                "x-api-source": "pc",
                "x-shopee-language": "en",
                "af-ac-enc-dat": "",
            },
        )
        out: list[dict] = []
        for it in data.get("items") or []:
            basic = it.get("item_basic") or it
            name = basic.get("name")
            price = basic.get("price")
            if not name or not isinstance(price, (int, float)):
                continue
            shopid, itemid = basic.get("shopid"), basic.get("itemid")
            purl = (
                f"https://{domain}/product/{shopid}/{itemid}"
                if shopid and itemid
                else f"https://{domain}/search?keyword={quote_plus(query)}"
            )
            before = basic.get("price_before_discount")
            image_hash = basic.get("image")
            rating = (basic.get("item_rating") or {}).get("rating_star")
            out.append(
                {
                    "title": name,
                    "price": price / 100000.0,
                    "original_price": (before / 100000.0)
                    if isinstance(before, (int, float)) and before else None,
                    "discount_pct": _discount_pct(basic.get("raw_discount")),
                    "currency": ccy,
                    "url": purl,
                    "image": f"https://cf.shopee.ph/file/{image_hash}" if image_hash else None,
                    "rating": round(float(rating), 1) if isinstance(rating, (int, float)) else None,
                    "reviews": _to_int(basic.get("cmt_count")),
                    "sold": _to_int(basic.get("historical_sold") or basic.get("sold")),
                    "in_stock": (basic.get("stock") or 0) > 0 if basic.get("stock") is not None else None,
                    "official": bool(basic.get("is_official_shop") or basic.get("shopee_verified")),
                    "location": basic.get("shop_location"),
                }
            )
        return out

    return _search


def _shopify_adapter(domain: str, ccy: str) -> SearchAdapter:
    """Any Shopify store answers /search/suggest.json with product results."""

    def _search(query: str) -> list[dict]:
        url = (
            f"https://{domain}/search/suggest.json?q={quote_plus(query)}"
            "&resources[type]=product&resources[limit]=10"
        )
        data = _api_get(url, {"Referer": f"https://{domain}/"})
        products = (
            ((data or {}).get("resources") or {}).get("results") or {}
        ).get("products") or []
        out: list[dict] = []
        for p in products:
            name = p.get("title")
            if not name:
                continue
            purl = str(p.get("url") or "")
            if purl.startswith("/"):
                purl = f"https://{domain}{purl}"
            # suggest.json prices are decimal strings in the store currency;
            # only trust a value that clearly looks like money (has a separator).
            raw_price = p.get("price")
            price = _to_float(raw_price) if raw_price and re.search(r"[.,]", str(raw_price)) else None
            out.append(
                {
                    "title": name,
                    "price": price,
                    "currency": ccy,
                    "url": purl,
                    "image": p.get("image") or p.get("featured_image"),
                    "seller": p.get("vendor"),
                    "in_stock": p.get("available"),
                }
            )
        return out

    return _search


def _woocommerce_adapter(domain: str, ccy: str) -> SearchAdapter:
    """WooCommerce's public Store API returns products (no auth needed)."""

    def _search(query: str) -> list[dict]:
        url = f"https://{domain}/wp-json/wc/store/products?search={quote_plus(query)}&per_page=20"
        data = _api_get(url, {"Referer": f"https://{domain}/"})
        items: list = data if isinstance(data, list) else []
        out: list[dict] = []
        for it in items:
            name = it.get("name")
            if not name:
                continue
            prices = it.get("prices") or {}
            unit = int(prices.get("currency_minor_unit") or 2)
            divisor = 10**unit

            def _minor(v: object) -> float | None:
                try:
                    return int(str(v)) / divisor if v not in (None, "") else None
                except (TypeError, ValueError):
                    return None

            images = it.get("images") or []
            out.append(
                {
                    "title": name,
                    "price": _minor(prices.get("price")),
                    "original_price": _minor(prices.get("regular_price")),
                    "currency": prices.get("currency_code") or ccy,
                    "url": it.get("permalink") or "",
                    "image": images[0].get("src") if images else None,
                    "in_stock": it.get("is_in_stock"),
                }
            )
        return out

    return _search


def _auto_adapter(domain: str, ccy: str) -> SearchAdapter:
    """Multi-strategy adapter for stores whose platform we don't hardcode: try
    Shopify then WooCommerce APIs, returning the first that yields products."""
    strategies = [_shopify_adapter(domain, ccy), _woocommerce_adapter(domain, ccy)]

    def _search(query: str) -> list[dict]:
        for strat in strategies:
            try:
                recs = strat(query)
            except Exception:  # try the next strategy
                continue
            if recs:
                return recs
        return []

    return _search


def _store(name: str, domain: str, ccy: str = "PHP") -> Retailer:
    """A retailer whose platform we auto-detect (Shopify/WooCommerce), falling
    back to scraping its /search page. Covers the many smaller shops."""
    return Retailer(name, f"https://{domain}/search?q={{q}}", _auto_adapter(domain, ccy))


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
        "lazada": Retailer(
            "Lazada PH", "https://www.lazada.com.ph/catalog/?q={q}",
            _lazada_adapter("www.lazada.com.ph", "PHP"),
        ),
        "shopee": Retailer(
            "Shopee PH", "https://shopee.ph/search?keyword={q}",
            _shopee_adapter("shopee.ph", "PHP"),
        ),
        "zalora": Retailer("Zalora PH", "https://www.zalora.com.ph/search/?q={q}"),
        "galleon": Retailer("Galleon PH", "https://www.galleon.ph/catalogsearch/result/?q={q}"),
        "carousell": Retailer("Carousell PH", "https://www.carousell.ph/search/{q}"),
        # Smaller PH tech/retail shops (platform auto-detected: Shopify/WooCommerce).
        "datablitz": _store("DataBlitz", "www.datablitz.com.ph"),
        "dynaquest": _store("DynaQuest PC", "dynaquestpc.com"),
        "easypc": _store("EasyPC", "easypc.com.ph"),
        "pcexpress": _store("PC Express", "pcexpress.com.ph"),
        "gamextreme": _store("GameXtreme", "www.gamextreme.ph"),
        "villman": _store("Villman", "villman.com"),
        "aliexpress": _ALIEXPRESS,
        "amazon": _GLOBAL["amazon"],
        "ebay": _GLOBAL["ebay"],
    },
    "sg": {
        "lazada": Retailer(
            "Lazada SG", "https://www.lazada.sg/catalog/?q={q}",
            _lazada_adapter("www.lazada.sg", "SGD"),
        ),
        "shopee": Retailer(
            "Shopee SG", "https://shopee.sg/search?keyword={q}",
            _shopee_adapter("shopee.sg", "SGD"),
        ),
        "amazon": Retailer("Amazon SG", "https://www.amazon.sg/s?k={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "my": {
        "lazada": Retailer(
            "Lazada MY", "https://www.lazada.com.my/catalog/?q={q}",
            _lazada_adapter("www.lazada.com.my", "MYR"),
        ),
        "shopee": Retailer(
            "Shopee MY", "https://shopee.com.my/search?keyword={q}",
            _shopee_adapter("shopee.com.my", "MYR"),
        ),
        "aliexpress": _ALIEXPRESS,
    },
    "id": {
        "lazada": Retailer(
            "Lazada ID", "https://www.lazada.co.id/catalog/?q={q}",
            _lazada_adapter("www.lazada.co.id", "IDR"),
        ),
        "shopee": Retailer(
            "Shopee ID", "https://shopee.co.id/search?keyword={q}",
            _shopee_adapter("shopee.co.id", "IDR"),
        ),
        "tokopedia": Retailer("Tokopedia", "https://www.tokopedia.com/search?q={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "th": {
        "lazada": Retailer(
            "Lazada TH", "https://www.lazada.co.th/catalog/?q={q}",
            _lazada_adapter("www.lazada.co.th", "THB"),
        ),
        "shopee": Retailer(
            "Shopee TH", "https://shopee.co.th/search?keyword={q}",
            _shopee_adapter("shopee.co.th", "THB"),
        ),
        "aliexpress": _ALIEXPRESS,
    },
    "vn": {
        "lazada": Retailer(
            "Lazada VN", "https://www.lazada.vn/catalog/?q={q}",
            _lazada_adapter("www.lazada.vn", "VND"),
        ),
        "shopee": Retailer(
            "Shopee VN", "https://shopee.vn/search?keyword={q}",
            _shopee_adapter("shopee.vn", "VND"),
        ),
        "tiki": Retailer("Tiki", "https://tiki.vn/search?q={q}"),
        "aliexpress": _ALIEXPRESS,
    },
    "us": {
        "amazon": _GLOBAL["amazon"],
        "ebay": _GLOBAL["ebay"],
        "walmart": _GLOBAL["walmart"],
        "newegg": _GLOBAL["newegg"],
        "bestbuy": Retailer("Best Buy", "https://www.bestbuy.com/site/searchpage.jsp?st={q}"),
        "target": Retailer("Target", "https://www.target.com/s?searchTerm={q}"),
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

# The local currency for each supported country, so canvas can price results in
# the shopper's own currency when a country is detected (no --to needed).
_COUNTRY_CCY: dict[str, str] = {
    "ph": "PHP", "sg": "SGD", "my": "MYR", "id": "IDR", "th": "THB",
    "vn": "VND", "us": "USD", "gb": "GBP", "in": "INR", "au": "AUD",
    "jp": "JPY", "ca": "CAD",
}


def _country_currency(country: str | None) -> str | None:
    return _COUNTRY_CCY.get(country) if country else None

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


# Search/category-page chrome that is not an actual product listing. These get
# scraped by mistake on JS-heavy pages, so we reject them outright.
_JUNK_RE = re.compile(
    r"^(results?|search results?|showing|no results|did you mean|sponsored|"
    r"related searches|filters?|sort by|categories?|see all|view all|"
    r"best sellers?|recommended|you may also|price|shop by)\b"
    r"|results? for\b|search results?\b|view all\b|\bads? in\b|\ball listings\b"
    r"|\bbrowse\b|for sale in\b",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    """Lowercase, collapse whitespace, and split letter<->digit boundaries so
    'Wooting 60HE' and 'wooting 60 he' match ('60he' -> '60 he')."""
    s = s.lower().strip()
    s = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", s)
    return re.sub(r"\s+", " ", s)


def _clean_title(title: object) -> str:
    """Strip surrounding quotes/whitespace a search page often wraps around the
    echoed query, e.g. '"logitech mouse"' -> 'logitech mouse'."""
    return str(title).strip().strip("\"'\u201c\u201d").strip()


def _is_junk_title(title: str | None) -> bool:
    """True if ``title`` looks like search/category page chrome (e.g. 'Results
    for X', 'Search results', 'Sort by') rather than a real product name."""
    if not title:
        return True
    t = _clean_title(title)
    if len(t) < 3:
        return True
    return bool(_JUNK_RE.search(t))


def _links_to_product(rec_url: object, search_url: str | None) -> bool:
    """A real listing links to a *distinct* detail page — not back to the search
    page (or just a #fragment of it, or nowhere)."""
    if not rec_url:
        return False
    if not search_url:
        return True
    resolved = urldefrag(urljoin(search_url, str(rec_url)))[0]
    return resolved != urldefrag(search_url)[0]


def _score(query: str, title: str | None) -> float:
    """0..1 confidence that ``title`` is the product named by ``query``.

    Token overlap dominates (a match should contain the query's words), with the
    character-level sequence ratio as a tie-breaker. Normalization makes
    '60HE' == '60 he'.
    """
    if not title:
        return 0.0
    q, t = _norm(query), _norm(title)
    words = [w for w in re.split(r"\W+", q) if w]
    ratio = difflib.SequenceMatcher(None, q, t).ratio()
    if not words:
        return round(ratio, 4)
    overlap = sum(1 for w in words if w in t) / len(words)
    return round(0.8 * overlap + 0.2 * ratio, 4)


def _top_matches(
    query: str, records: list[dict], limit: int, search_url: str | None = None
) -> list[dict]:
    """Return up to ``limit`` best product matches, junk-filtered and deduped."""
    scored: list[tuple[float, str, dict]] = []
    seen: set[tuple] = set()
    for rec in records:
        raw_title = rec.get("title")
        if _is_junk_title(raw_title):
            continue
        title = _clean_title(raw_title)
        # A real listing links to its own distinct product page; search-page
        # headings / query echoes link back to the search page (or nowhere).
        if not _links_to_product(rec.get("url"), search_url):
            continue
        score = _score(query, title)
        # Real product cards carry a price — small reward as a tie-breaker.
        if isinstance(rec.get("price"), (int, float)):
            score += 0.05
        if score < _MATCH_THRESHOLD:
            continue
        key = (title.lower(), rec.get("url"))
        if key in seen:
            continue
        seen.add(key)
        scored.append((min(score, 1.0), title, rec))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {"rec": rec, "score": round(sc, 2), "title": title}
        for sc, title, rec in scored[: max(1, limit)]
    ]


def _search_one(
    retailer: Retailer,
    query: str,
    base_ccy: str,
    rates: dict,
    per_store: int,
    force_js: bool,
) -> tuple[str, list[CanvasHit]]:
    """Search a single retailer. Returns ``(status, hits)`` where status is one
    of ``ok`` / ``blocked`` / ``error`` / ``nomatch``. Never raises."""
    url = retailer.search_url.format(q=quote_plus(query))

    # 1) Prefer the store's structured JSON API (reliable products + prices).
    records: list[dict] = []
    if retailer.adapter is not None:
        try:
            records = retailer.adapter(query) or []
        except Exception as exc:  # API changed / blocked -> fall back to HTML
            logger.info("Canvas: %s API adapter failed (%s); trying HTML", retailer.name, exc)
            records = []

    # 2) Fall back to scraping the HTML search page (auto JS-rendered if needed).
    if not records:
        try:
            result = scrape(url, ecommerce.PRODUCT_LIST_SCHEMA, force_js=force_js)
        except Exception as exc:  # one retailer failing must not stop the canvas
            logger.warning("Canvas: %s failed: %s", retailer.name, exc)
            return "error", []
        if getattr(result, "blocked", False):
            logger.warning("Canvas: %s blocked or unreachable", retailer.name)
            return "blocked", []
        records = result.records

    hits: list[CanvasHit] = []
    for match in _top_matches(query, records, per_store, search_url=url):
        rec = match["rec"]
        price = rec.get("price") if isinstance(rec.get("price"), (int, float)) else None
        native_ccy = rec.get("currency")
        converted = currency.convert(price, native_ccy or base_ccy, base_ccy, rates)
        orig = rec.get("original_price") if isinstance(rec.get("original_price"), (int, float)) else None
        discount = rec.get("discount_pct")
        if discount is None and orig and price and orig > price:
            discount = round((orig - price) / orig * 100)
        hits.append(
            CanvasHit(
                retailer=retailer.name,
                title=match.get("title") or _clean_title(rec.get("title")) or query,
                price=price,
                currency=native_ccy,
                url=urljoin(url, rec.get("url")) if rec.get("url") else url,
                converted=converted,
                score=match["score"],
                image=rec.get("image"),
                rating=rec.get("rating") if isinstance(rec.get("rating"), (int, float)) else None,
                reviews=rec.get("reviews") if isinstance(rec.get("reviews"), int) else None,
                sold=rec.get("sold") if isinstance(rec.get("sold"), int) else None,
                original_price=orig,
                discount_pct=int(discount) if discount else None,
                in_stock=rec.get("in_stock"),
                seller=rec.get("seller"),
                official=bool(rec.get("official")),
            )
        )
    return ("ok" if hits else "nomatch"), hits


def _expand_query(query: str) -> list[str]:
    """Ordered query variants to widen coverage when results are thin: no-space
    and spaced-digit forms, plural/singular, and dropping the model/brand token."""
    variants: list[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        v = v.strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            variants.append(v)

    q = query.strip()
    add(q)
    add(_norm(q))                       # "60HE" -> "60 he"
    add(re.sub(r"\s+", "", q))          # collapse spaces: "rtx 5070" -> "rtx5070"
    add(q[:-1] if q.lower().endswith("s") else q + "s")  # plural/singular
    tokens = q.split()
    if len(tokens) > 1:
        add(" ".join(tokens[:-1]))      # drop trailing model/spec token
        add(" ".join(tokens[1:]))       # drop leading brand token
    return variants


def _dedup_key(h: CanvasHit) -> tuple:
    return (h.retailer.lower(), (h.url or "").lower() or _norm(h.title))


def _sort_hits(hits: list[CanvasHit], sort: str) -> list[CanvasHit]:
    """Order hits by the requested key; price-less/unknown values sink last."""
    def price_key(h: CanvasHit) -> tuple:
        return (h.converted is None, h.converted if h.converted is not None else 0.0)

    if sort == "price_high":
        hits.sort(key=lambda h: (h.converted is None, -(h.converted or 0.0)))
    elif sort == "rating":
        hits.sort(key=lambda h: (h.rating is None, -(h.rating or 0.0)))
    elif sort == "reviews":
        hits.sort(key=lambda h: (h.reviews is None, -(h.reviews or 0)))
    elif sort in ("popular", "sold"):
        hits.sort(key=lambda h: (h.sold is None, -(h.sold or 0)))
    elif sort == "discount":
        hits.sort(key=lambda h: (h.discount_pct is None, -(h.discount_pct or 0)))
    elif sort == "match":
        hits.sort(key=lambda h: -h.score)
    else:  # "price" (cheapest first) — the default
        hits.sort(key=price_key)
    return hits


def _price_stats(hits: list[CanvasHit]) -> dict:
    """Min/max/avg/median (+ savings) over the converted prices we have."""
    import statistics

    vals = sorted(h.converted for h in hits if h.converted is not None)
    if not vals:
        return {}
    return {
        "min": round(vals[0], 2),
        "max": round(vals[-1], 2),
        "avg": round(statistics.mean(vals), 2),
        "median": round(statistics.median(vals), 2),
        "savings": round(vals[-1] - vals[0], 2),
        "count": len(vals),
    }


def search(
    query: str,
    retailers: list[str] | None = None,
    base: str | None = None,
    country: str | None = None,
    force_js: bool = False,
    per_store: int | None = None,
    sort: str = "price",
    expand: bool | None = None,
) -> dict:
    """Search each retailer for ``query`` and return ranked price hits.

    ``country`` (ISO-3166 alpha-2) selects local marketplaces. When omitted, it's
    resolved in this order: ``CRAWLR_COUNTRY`` > the explicit ``base`` currency >
    IP geolocation (auto) > the default reporting currency > global stores.

    Retailers are searched concurrently, up to ``per_store`` listings each. If
    fewer than ``CRAWLR_CANVAS_MIN_RESULTS`` products are found, the query is
    automatically expanded (plural/singular, drop brand/model, …) and retried.
    """
    per = per_store if per_store and per_store > 0 else config.CANVAS_PER_STORE
    resolved_country, country_source = _resolve_country(
        country, explicit_ccy=base, use_geo=config.CANVAS_GEO
    )
    catalog = available_retailers(resolved_country)
    rates, fx_source = currency.get_rates()
    # Display currency: an explicit --to wins; otherwise price in the detected
    # country's own currency (e.g. PH -> PHP); else fall back to CRAWLR_FX_BASE.
    candidate = (base or _country_currency(resolved_country) or config.FX_BASE).upper()
    base_ccy = candidate if candidate in rates else config.FX_BASE.upper()
    if base_ccy not in rates:
        base_ccy = "USD"
    currency_source = (
        "flag" if base else ("country" if _country_currency(resolved_country) else "default")
    )
    selected = _select(retailers, catalog)

    def _run_all(q: str) -> tuple[list[CanvasHit], list[str], list[str]]:
        hits_: list[CanvasHit] = []
        blocked_: list[str] = []
        errored_: list[str] = []

        def _run(r: Retailer) -> tuple[Retailer, str, list[CanvasHit]]:
            status, rhits = _search_one(r, q, base_ccy, rates, per, force_js)
            return r, status, rhits

        workers = min(len(selected), config.CANVAS_WORKERS) if selected else 1
        if workers > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=workers) as pool:
                outcomes = list(pool.map(_run, selected))
        else:
            outcomes = [_run(r) for r in selected]
        for retailer, status, rhits in outcomes:
            if status == "blocked":
                blocked_.append(retailer.name)
            elif status == "error":
                errored_.append(retailer.name)
            hits_.extend(rhits)
        return hits_, blocked_, errored_

    hits, blocked, errored = _run_all(query)
    seen = {_dedup_key(h) for h in hits}
    tried = [query]

    # Auto-retry with expanded queries until we hit the coverage threshold.
    do_expand = config.CANVAS_MIN_RESULTS > 0 if expand is None else expand
    if do_expand and len(hits) < config.CANVAS_MIN_RESULTS:
        for variant in _expand_query(query)[1:]:  # [0] is the original query
            if len(hits) >= config.CANVAS_MIN_RESULTS:
                break
            extra, _, _ = _run_all(variant)
            tried.append(variant)
            for h in extra:
                key = _dedup_key(h)
                if key not in seen:
                    seen.add(key)
                    hits.append(h)

    _sort_hits(hits, sort)
    # Cap the final results per store (expansion may have gathered extras).
    if per:
        capped: list[CanvasHit] = []
        counts: dict[str, int] = {}
        for h in hits:
            if counts.get(h.retailer, 0) < per:
                capped.append(h)
                counts[h.retailer] = counts.get(h.retailer, 0) + 1
        hits = capped
    return {
        "query": query,
        "base": base_ccy,
        "currency_source": currency_source,
        "country": resolved_country,
        "country_source": country_source,
        "fx_source": fx_source,
        "retailers_searched": [r.name for r in selected],
        "queries_tried": tried,
        "blocked": blocked,
        "errored": errored,
        "shops": len({h.retailer for h in hits}),
        "stats": _price_stats(hits),
        "hits": hits,
    }
