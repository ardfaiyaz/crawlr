"""Zero-config schema detection.

Given a URL (or already-fetched HTML), guess which extraction schema fits best
so users can run ``crawlr watch <url>`` without passing ``--schema``.

Detection is content-first (most reliable) with a URL-keyword fallback:

1. schema.org ``@type`` in JSON-LD  (Product, JobPosting, RealEstateListing, ...)
2. microdata ``itemtype`` and OpenGraph ``og:type``
3. presence of repeating product cards -> a listing page
4. keywords in the URL path (``/jobs/``, ``/property/`` ...)

The result is always a schema name that actually resolves in the registry; if
nothing matches we fall back to the single-product schema.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from selectolax.parser import HTMLParser

from . import schemas as schema_registry

# schema.org @type (lower-cased) -> Crawlr schema name.
_TYPE_MAP = {
    "product": "product",
    "individualproduct": "product",
    "productmodel": "product",
    "offer": "product",
    "aggregateoffer": "product",
    "jobposting": "jobs",
    "realestatelisting": "real_estate",
    "apartment": "real_estate",
    "house": "real_estate",
    "singlefamilyresidence": "real_estate",
    "residence": "real_estate",
    "accommodation": "real_estate",
    "newsarticle": "news",
    "article": "news",
    "blogposting": "news",
    "reportagenewsarticle": "news",
    "liveblogposting": "news",
}

_OG_TYPE_MAP = {
    "product": "product",
    "product.item": "product",
    "article": "news",
    "website": "",  # ambiguous -> ignore
}

# URL path keyword -> schema name (last-resort fallback).
_URL_KEYWORDS = [
    ("jobs", "jobs"),
    ("job", "jobs"),
    ("career", "jobs"),
    ("vacanc", "jobs"),
    ("real-estate", "real_estate"),
    ("realestate", "real_estate"),
    ("property", "real_estate"),
    ("properties", "real_estate"),
    ("listing", "real_estate"),
    ("homes", "real_estate"),
    ("rent", "real_estate"),
    ("news", "news"),
    ("article", "news"),
    ("blog", "news"),
    ("story", "news"),
    ("product", "product"),
]

_LIST_HINTS = ("/search", "/category", "/collections", "/shop", "/c/", "/s?", "?q=", "&q=")

# Fallback when nothing is detected.
DEFAULT_SCHEMA = "product"


def _available_names() -> set[str]:
    return {s["name"] for s in schema_registry.available()}


def _iter_types(data) -> list[str]:
    """Collect every schema.org @type string from a nested JSON-LD structure."""
    found: list[str] = []
    if isinstance(data, dict):
        raw = data.get("@type")
        if isinstance(raw, str):
            found.append(raw)
        elif isinstance(raw, list):
            found.extend(t for t in raw if isinstance(t, str))
        for value in data.values():
            found.extend(_iter_types(value))
    elif isinstance(data, list):
        for item in data:
            found.extend(_iter_types(item))
    return found


def _jsonld_types(tree: HTMLParser) -> list[str]:
    types: list[str] = []
    for script in tree.css('script[type="application/ld+json"]'):
        text = script.text()
        if not text:
            continue
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        types.extend(_iter_types(data))
    return [t.lower() for t in types]


def _microdata_types(tree: HTMLParser) -> list[str]:
    out: list[str] = []
    for node in tree.css("[itemtype]"):
        itemtype = node.attributes.get("itemtype") or ""
        # itemtype is a full schema.org URL; take the trailing type token.
        token = re.split(r"[/#]", itemtype.rstrip("/"))[-1]
        if token:
            out.append(token.lower())
    return out


def _og_type(tree: HTMLParser) -> str | None:
    for m in tree.css("meta"):
        prop = m.attributes.get("property") or m.attributes.get("name")
        if prop in ("og:type", "product:type"):
            content = m.attributes.get("content")
            if content:
                return content.lower()
    return None


def _looks_like_listing(tree: HTMLParser) -> bool:
    """Heuristic: several repeating product-ish cards suggests a listing page."""
    for selector in (
        "[itemtype*='Product']",
        ".product",
        ".product-item",
        ".product-card",
        "li.product",
        ".s-result-item",
    ):
        if len(tree.css(selector)) >= 3:
            return True
    return False


def detect_from_html(html: str, url: str = "") -> str:
    """Detect the best schema name from page HTML (and optionally the URL)."""
    available = _available_names()

    def _pick(name: str) -> str | None:
        return name if name in available else None

    tree = HTMLParser(html or "")

    # 1. JSON-LD + microdata @type — the strongest signal.
    typed = _jsonld_types(tree) + _microdata_types(tree)
    is_product_type = any(t in _TYPE_MAP and _TYPE_MAP[t] == "product" for t in typed)
    for t in typed:
        mapped = _TYPE_MAP.get(t)
        if not mapped:
            continue
        # A product page that also shows many cards is really a listing.
        if mapped == "product" and _looks_like_listing(tree):
            picked = _pick("product_list")
            if picked:
                return picked
        picked = _pick(mapped)
        if picked:
            return picked

    # 2. OpenGraph type.
    og = _og_type(tree)
    if og:
        mapped = _OG_TYPE_MAP.get(og)
        if mapped:
            picked = _pick(mapped)
            if picked:
                return picked

    # 3. Structural: many product cards with no explicit product type.
    if not is_product_type and _looks_like_listing(tree):
        picked = _pick("product_list")
        if picked:
            return picked

    # 4. URL keyword fallback.
    picked = _detect_from_url(url, available)
    if picked:
        return picked

    return DEFAULT_SCHEMA if DEFAULT_SCHEMA in available else "product"


def _detect_from_url(url: str, available: set[str]) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()
    haystack = f"{path}?{query}"

    if any(hint in haystack for hint in _LIST_HINTS) and "product_list" in available:
        return "product_list"
    for keyword, name in _URL_KEYWORDS:
        if keyword in path and name in available:
            return name
    return None


def detect_schema(url: str, html: str | None = None, *, force_js: bool = False) -> str:
    """Detect the best schema for ``url``. Fetches the page if HTML isn't given.

    Fetching is imported lazily so importing this module stays cheap and the
    heavy fetcher dependency is only loaded when we actually need the network.
    """
    if html is None:
        from .fetcher import fetch

        try:
            html = fetch(url, force_js=force_js).html
        except Exception:
            # Network/parse failure: fall back to URL-only detection.
            return _detect_from_url(url, _available_names()) or DEFAULT_SCHEMA
    return detect_from_html(html, url)
