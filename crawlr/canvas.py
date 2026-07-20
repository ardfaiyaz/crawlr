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
import logging
import re
from dataclasses import dataclass
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


# Built-in retailers. The marketplace ones need a fetch provider to reliably get
# past anti-bot; scrape-friendly stores work directly.
_BUILTIN: dict[str, Retailer] = {
    "amazon": Retailer("Amazon", "https://www.amazon.com/s?k={q}"),
    "ebay": Retailer("eBay", "https://www.ebay.com/sch/i.html?_nkw={q}"),
    "walmart": Retailer("Walmart", "https://www.walmart.com/search?q={q}"),
    "newegg": Retailer("Newegg", "https://www.newegg.com/p/pl?d={q}"),
    "lazada": Retailer("Lazada", "https://www.lazada.com.ph/catalog/?q={q}"),
    "aliexpress": Retailer("AliExpress", "https://www.aliexpress.com/wholesale?SearchText={q}"),
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


def available_retailers() -> dict[str, Retailer]:
    """All known retailers: built-ins plus any from the user's YAML file."""
    merged = dict(_BUILTIN)
    merged.update(_load_user_retailers())
    return merged


def _select(names: list[str] | None) -> list[Retailer]:
    catalog = available_retailers()
    if not names:
        return list(catalog.values())
    chosen: list[Retailer] = []
    for n in names:
        r = catalog.get(n.strip().lower())
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
    force_js: bool = False,
) -> dict:
    """Search each retailer for ``query`` and return ranked price hits."""
    base_ccy = (base or config.FX_BASE).upper()
    rates, fx_source = currency.get_rates()
    hits: list[CanvasHit] = []

    for retailer in _select(retailers):
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
    return {"query": query, "base": base_ccy, "fx_source": fx_source, "hits": hits}
