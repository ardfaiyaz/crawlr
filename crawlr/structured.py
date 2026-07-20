"""Structured-data extraction — the most reliable layer for e-commerce.

Many stores embed exact product data as schema.org JSON-LD, microdata, or
OpenGraph tags. Reading that is far more accurate and redesign-proof than CSS
selectors, so Crawlr consults it first and cross-checks it against selectors.

`extract_structured(html)` returns any of these fields it can find:
    title, price, original_price, currency, availability, rating, review_count,
    brand, sku, gtin, mpn, image, url
"""

from __future__ import annotations

import json

from selectolax.parser import HTMLParser

from . import normalize

_CANONICAL = (
    "title", "price", "original_price", "currency", "availability", "rating",
    "review_count", "brand", "sku", "gtin", "mpn", "image", "url",
)


def extract_structured(html: str) -> dict:
    tree = HTMLParser(html)
    out: dict = {}
    for source in (_from_jsonld(tree), _from_microdata(tree), _from_opengraph(tree)):
        for key, val in source.items():
            if val not in (None, "") and out.get(key) in (None, ""):
                out[key] = val
    return {k: v for k, v in out.items() if k in _CANONICAL}


def _availability_text(value) -> str | None:
    if not value:
        return None
    v = str(value)
    low = v.lower()
    if "outofstock" in low or "out of stock" in low or "soldout" in low:
        return "Out of stock"
    if "discontinued" in low:
        return "Discontinued"
    if "preorder" in low or "pre-order" in low:
        return "Pre-order"
    if "backorder" in low or "back order" in low:
        return "Backorder"
    if "limitedavailability" in low:
        return "Limited availability"
    if "instock" in low or "in stock" in low or "onlineonly" in low:
        return "In stock"
    return v


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _image_url(value):
    value = _first(value)
    if isinstance(value, dict):
        return value.get("url")
    return value


def _as_str(value) -> str | None:
    """Coerce a scalar to a clean string; ignore dicts/lists/empties."""
    if value in (None, "") or isinstance(value, (dict, list)):
        return None
    return str(value).strip() or None


def _brand_name(value) -> str | None:
    """Brand can be a bare string or an Organization/Brand object."""
    value = _first(value)
    if isinstance(value, dict):
        return _as_str(value.get("name"))
    return _as_str(value)


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------


def _iter_nodes(data):
    """Yield every dict in a nested JSON-LD structure."""
    if isinstance(data, dict):
        yield data
        for v in data.values():
            yield from _iter_nodes(v)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)


def _from_jsonld(tree: HTMLParser) -> dict:
    out: dict = {}
    for script in tree.css('script[type="application/ld+json"]'):
        text = script.text()
        if not text:
            continue
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _iter_nodes(data):
            types = node.get("@type", "")
            types = types if isinstance(types, list) else [types]
            is_product = any("product" in str(t).lower() for t in types)
            if not (is_product or "offers" in node):
                continue
            _fill(out, "title", _as_str(node.get("name")))
            _fill(out, "image", _image_url(node.get("image")))
            _fill(out, "url", _as_str(node.get("url")))
            _fill(out, "brand", _brand_name(node.get("brand")))
            _fill(out, "sku", _as_str(node.get("sku")))
            _fill(out, "mpn", _as_str(node.get("mpn")))
            _fill(out, "gtin", _as_str(
                node.get("gtin") or node.get("gtin13") or node.get("gtin12") or node.get("gtin8")
            ))
            rating = node.get("aggregateRating")
            if isinstance(rating, dict):
                _fill(out, "rating", normalize.normalize_number(rating.get("ratingValue")))
                _fill(out, "review_count", normalize.normalize_number(
                    rating.get("reviewCount") or rating.get("ratingCount")
                ))
            offer = _first(node.get("offers"))
            if isinstance(offer, dict):
                price = offer.get("price") or offer.get("lowPrice")
                spec = offer.get("priceSpecification")
                if price is None and isinstance(spec, dict):
                    price = spec.get("price")
                _fill(out, "price", normalize.normalize_number(price))
                # AggregateOffer highPrice (or an explicit list price) = "was" price.
                _fill(out, "original_price", normalize.normalize_number(
                    offer.get("highPrice") or offer.get("listPrice")
                ))
                _fill(out, "currency", _as_str(
                    offer.get("priceCurrency")
                    or (spec.get("priceCurrency") if isinstance(spec, dict) else None)
                ))
                _fill(out, "availability", _availability_text(offer.get("availability")))
    return out


# ---------------------------------------------------------------------------
# Microdata (itemprop)
# ---------------------------------------------------------------------------


def _prop(scope, name: str) -> str | None:
    node = scope.css_first(f'[itemprop="{name}"]')
    if node is None:
        return None
    for attr in ("content", "href", "src"):
        val = node.attributes.get(attr)
        if val:
            return val
    text = node.text()
    return text.strip() if text else None


def _from_microdata(tree: HTMLParser) -> dict:
    scope = tree.css_first('[itemtype*="Product"]') or tree.body
    if scope is None:
        return {}
    out: dict = {}
    _fill(out, "title", _prop(scope, "name"))
    _fill(out, "price", normalize.normalize_number(_prop(scope, "price")))
    _fill(out, "currency", _prop(scope, "priceCurrency"))
    _fill(out, "availability", _availability_text(_prop(scope, "availability")))
    _fill(out, "rating", normalize.normalize_number(_prop(scope, "ratingValue")))
    _fill(out, "review_count", normalize.normalize_number(_prop(scope, "reviewCount")))
    _fill(out, "brand", _prop(scope, "brand"))
    _fill(out, "sku", _prop(scope, "sku"))
    _fill(out, "image", _prop(scope, "image"))
    return out


# ---------------------------------------------------------------------------
# OpenGraph / product meta
# ---------------------------------------------------------------------------


def _meta(tree: HTMLParser, keys: tuple[str, ...]) -> str | None:
    for m in tree.css("meta"):
        prop = m.attributes.get("property") or m.attributes.get("name")
        if prop in keys:
            content = m.attributes.get("content")
            if content:
                return content
    return None


def _from_opengraph(tree: HTMLParser) -> dict:
    out: dict = {}
    _fill(out, "title", _meta(tree, ("og:title",)))
    _fill(out, "image", _meta(tree, ("og:image",)))
    _fill(out, "url", _meta(tree, ("og:url",)))
    _fill(out, "price", normalize.normalize_number(
        _meta(tree, ("product:price:amount", "og:price:amount"))
    ))
    _fill(out, "currency", _meta(tree, ("product:price:currency", "og:price:currency")))
    _fill(out, "brand", _meta(tree, ("product:brand", "og:brand")))
    _fill(out, "availability", _availability_text(
        _meta(tree, ("product:availability", "og:availability"))
    ))
    return out


def _fill(out: dict, key: str, value) -> None:
    if value not in (None, "") and out.get(key) in (None, ""):
        out[key] = value
