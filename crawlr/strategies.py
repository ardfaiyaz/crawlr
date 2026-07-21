"""Multi-strategy product extraction — never depend on a single technique.

Modern stores expose product data in many shapes: schema.org JSON-LD, framework
hydration state (Next.js ``__NEXT_DATA__``, Nuxt, Apollo, Redux), or ad-hoc JSON
blobs in ``<script>`` tags. This module runs *every* applicable strategy over a
single fetched HTML document and merges the results, so if one parser finds
nothing another usually will.

Each strategy returns a list of product dicts with any of:
    title, price, original_price, currency, url, image, sku, gtin, brand,
    rating, reviews, availability

Public entry point:
    extract_products(html, base_url) -> (products, strategies_used)
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from . import normalize, structured

# Field-name candidates used by the generic product-JSON walker. Deliberately
# broad — the caller (canvas) re-scores against the query and requires a real
# product URL, so over-extraction is filtered downstream.
_NAME_KEYS = ("name", "title", "productName", "product_name", "displayName", "label")
_PRICE_KEYS = (
    "price", "currentPrice", "current_price", "sellingPrice", "selling_price",
    "finalPrice", "final_price", "salePrice", "sale_price", "offerPrice",
    "priceAmount", "price_min", "min_price", "minPrice", "lowPrice", "amount",
)
_ORIG_KEYS = (
    "originalPrice", "original_price", "listPrice", "list_price", "wasPrice",
    "regularPrice", "regular_price", "strikePrice", "price_before_discount",
    "highPrice", "msrp", "oldPrice",
)
_URL_KEYS = (
    "url", "productUrl", "product_url", "itemUrl", "link", "href", "canonicalUrl",
    "seoUrl", "permalink", "slug", "detailUrl",
)
_IMAGE_KEYS = (
    "image", "imageUrl", "image_url", "img", "thumbnail", "thumb",
    "featured_image", "mainImage", "coverImage",
)
_SKU_KEYS = ("sku", "skuId", "sku_id", "productId", "product_id", "itemId", "item_id")
_GTIN_KEYS = ("gtin", "gtin13", "gtin12", "gtin8", "ean", "upc", "barcode")
_BRAND_KEYS = ("brand", "brandName", "brand_name", "manufacturer", "vendor")
_RATING_KEYS = ("rating", "ratingValue", "averageRating", "rating_star", "stars", "avgRating")
_REVIEW_KEYS = (
    "reviewCount", "ratingCount", "review_count", "reviews", "numReviews",
    "cmt_count", "totalReviews",
)

# Framework hydration globals we know how to read.
_STATE_VARS = (
    "__APOLLO_STATE__", "__INITIAL_STATE__", "__PRELOADED_STATE__",
    "__REDUX_STATE__", "__NUXT__", "__wovn_initial_data__", "__data__",
)

_MAX_NODES = 60_000  # walker budget so a huge blob can't hang a run


def _num(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ("value", "amount", "raw", "centAmount", "price"):
            if k in value:
                n = _num(value[k])
                if n is not None:
                    # Commerce tools often store minor units (cents) as ints.
                    if k == "centAmount" and isinstance(value[k], int):
                        return n / 100.0
                    return n
        return None
    return normalize.normalize_number(value)


def _first(node: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        v = node.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def _str(value: object) -> str | None:
    if value in (None, "") or isinstance(value, (dict, list)):
        return None
    return str(value).strip() or None


def _currency_of(node: dict) -> str | None:
    cur = _first(node, ("currency", "priceCurrency", "currencyCode", "currency_code"))
    if isinstance(cur, dict):
        cur = cur.get("code") or cur.get("currencyCode")
    return _str(cur)


def _looks_like_product(node: dict) -> bool:
    name = _first(node, _NAME_KEYS)
    if not isinstance(name, str) or not (3 <= len(name.strip()) <= 300):
        return False
    has_price = _first(node, _PRICE_KEYS) is not None or bool(
        node.get("offers") or node.get("offer") or node.get("prices")
    )
    # Require some product-identity signal to avoid config/nav blobs.
    has_ident = any(node.get(k) not in (None, "", [], {}) for k in _URL_KEYS + _SKU_KEYS + _IMAGE_KEYS)
    return has_price and has_ident


def _product_from_node(node: dict) -> dict | None:
    if not _looks_like_product(node):
        return None
    price = _num(_first(node, _PRICE_KEYS))
    currency = _currency_of(node)
    offers = node.get("offers") or node.get("offer") or node.get("prices")
    offer = offers[0] if isinstance(offers, list) and offers else offers
    if price is None and isinstance(offer, dict):
        price = _num(_first(offer, _PRICE_KEYS + ("price",)))
        currency = currency or _currency_of(offer)
    brand = _first(node, _BRAND_KEYS)
    if isinstance(brand, dict):
        brand = brand.get("name")
    img = _first(node, _IMAGE_KEYS)
    if isinstance(img, dict):
        img = img.get("url") or img.get("src")
    if isinstance(img, list) and img:
        img = img[0].get("url") if isinstance(img[0], dict) else img[0]
    rating = node.get("aggregateRating")
    rating_val = _num(rating.get("ratingValue")) if isinstance(rating, dict) else _num(_first(node, _RATING_KEYS))
    review_val = (
        _num(rating.get("reviewCount") or rating.get("ratingCount"))
        if isinstance(rating, dict) else _num(_first(node, _REVIEW_KEYS))
    )
    return {
        "title": _str(_first(node, _NAME_KEYS)),
        "price": price,
        "original_price": _num(_first(node, _ORIG_KEYS)),
        "currency": currency,
        "url": _str(_first(node, _URL_KEYS)),
        "image": _str(img),
        "sku": _str(_first(node, _SKU_KEYS)),
        "gtin": _str(_first(node, _GTIN_KEYS)),
        "brand": _str(brand),
        "rating": rating_val,
        "reviews": int(review_val) if review_val else None,
    }


def _walk(obj: Any, out: list[dict], budget: list[int]) -> None:
    """Depth-first search for product-shaped dicts anywhere in a JSON tree."""
    if budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(obj, dict):
        prod = _product_from_node(obj)
        if prod and prod.get("title") and prod.get("price") is not None:
            out.append(prod)
        for v in obj.values():
            if isinstance(v, (dict, list)):
                _walk(v, out, budget)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _walk(item, out, budget)


def _walk_products(data: Any) -> list[dict]:
    out: list[dict] = []
    _walk(data, out, [_MAX_NODES])
    return out


# ---------------------------------------------------------------------------
# Pulling JSON out of <script> tags
# ---------------------------------------------------------------------------


def _balanced_json(text: str, start: int) -> str | None:
    """From ``start`` (index of a '{' or '['), return the balanced JSON substring."""
    if start < 0 or start >= len(text):
        return None
    open_ch = text[start]
    close_ch = {"{": "}", "[": "]"}.get(open_ch)
    if close_ch is None:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _assignment_json(text: str, var_names: tuple[str, ...]) -> Iterator[Any]:
    """Yield parsed JSON assigned to ``window.X = {...}`` / ``X = {...}``."""
    for var in var_names:
        for m in re.finditer(re.escape(var) + r"\s*=\s*", text):
            brace = text.find("{", m.end())
            bracket = text.find("[", m.end())
            candidates = [i for i in (brace, bracket) if i != -1]
            if not candidates:
                continue
            blob = _balanced_json(text, min(candidates))
            if not blob:
                continue
            try:
                yield json.loads(blob)
            except (json.JSONDecodeError, ValueError):
                continue


def _script_texts(tree: HTMLParser) -> Iterator[tuple[str, str]]:
    for s in tree.css("script"):
        text = s.text() or ""
        if text.strip():
            yield (s.attributes.get("type") or "").lower(), text


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def from_jsonld(html: str, base_url: str) -> list[dict]:
    """schema.org JSON-LD Product / ItemList (the cleanest, most standard source)."""
    return structured.extract_product_list(html)


def from_embedded_state(html: str, base_url: str) -> list[dict]:
    """Framework hydration state: Next.js __NEXT_DATA__, Nuxt/Apollo/Redux globals."""
    tree = HTMLParser(html)
    products: list[dict] = []

    # Next.js ships a clean JSON <script id="__NEXT_DATA__" type="application/json">.
    node = tree.css_first("#__NEXT_DATA__")
    if node is not None and node.text():
        try:
            products.extend(_walk_products(json.loads(node.text())))
        except (json.JSONDecodeError, ValueError):
            pass

    # Redux/Apollo/Nuxt-style ``window.__X__ = {...}`` assignments.
    for _type, text in _script_texts(tree):
        if not any(v in text for v in _STATE_VARS):
            continue
        for data in _assignment_json(text, _STATE_VARS):
            products.extend(_walk_products(data))
    return products


def from_inline_json(html: str, base_url: str) -> list[dict]:
    """Generic scan: any <script> JSON that contains product-shaped objects."""
    tree = HTMLParser(html)
    products: list[dict] = []
    for stype, text in _script_texts(tree):
        if "ld+json" in stype:
            continue  # handled by from_jsonld
        low = text.lower()
        if '"price' not in low and "'price" not in low and "price:" not in low:
            continue
        # Whole-script JSON (application/json or a bare literal).
        parsed = False
        stripped = text.strip()
        if stripped[:1] in "{[":
            blob = _balanced_json(stripped, 0)
            if blob:
                try:
                    products.extend(_walk_products(json.loads(blob)))
                    parsed = True
                except (json.JSONDecodeError, ValueError):
                    pass
        if not parsed:
            # Largest embedded object after any ``= {`` / ``:{`` assignment.
            for m in re.finditer(r"[=(]\s*", text):
                idx = text.find("{", m.end())
                if idx == -1 or idx - m.end() > 3:
                    continue
                blob = _balanced_json(text, idx)
                if not blob or len(blob) < 40:
                    continue
                try:
                    products.extend(_walk_products(json.loads(blob)))
                except (json.JSONDecodeError, ValueError):
                    continue
                break
    return products


# Ordered by trust: JSON-LD (standard) > hydration state (rich) > inline scan.
_STRATEGIES: tuple[tuple[str, Any], ...] = (
    ("jsonld", from_jsonld),
    ("embedded_state", from_embedded_state),
    ("inline_json", from_inline_json),
)


def _key(prod: dict) -> tuple:
    gtin = prod.get("gtin")
    if gtin:
        return ("gtin", str(gtin))
    url = prod.get("url") or ""
    title = (prod.get("title") or "").strip().lower()
    return ("u", str(url).split("?")[0].rstrip("/")) if url else ("t", title)


def _merge_into(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if dst.get(k) in (None, "", [], {}) and v not in (None, "", [], {}):
            dst[k] = v


def extract_products(html: str, base_url: str = "") -> tuple[list[dict], list[str]]:
    """Run every extraction strategy over ``html`` and merge the products.

    Returns ``(products, strategies_used)``. Products keep the first strategy's
    value per field and fill gaps from later ones; URLs/images are absolutised
    against ``base_url``.
    """
    if not html:
        return [], []
    merged: dict[tuple, dict] = {}
    used: list[str] = []
    for name, fn in _STRATEGIES:
        try:
            found = fn(html, base_url)
        except Exception:  # a broken strategy must never break the rest
            continue
        kept = 0
        for prod in found:
            if not prod.get("title") or prod.get("price") is None:
                continue
            key = _key(prod)
            if key in merged:
                _merge_into(merged[key], prod)
            else:
                merged[key] = dict(prod)
            kept += 1
        if kept:
            used.append(name)

    products: list[dict] = []
    for prod in merged.values():
        if base_url:
            if prod.get("url"):
                prod["url"] = urljoin(base_url, str(prod["url"]))
            if prod.get("image"):
                prod["image"] = urljoin(base_url, str(prod["image"]))
        products.append(prod)
    return products, used
