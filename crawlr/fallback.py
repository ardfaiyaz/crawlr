"""Best-effort, page-level fallbacks for single-product pages.

When neither structured data (JSON-LD / microdata / OpenGraph) nor the schema's
CSS selectors produce a value, these heuristics try hard to still find the
essentials — title, price, currency, image, availability — so a watch returns
*something* useful even on unusual or hostile layouts.

They are intentionally aggressive and only ever used to **fill gaps**: the
extractor calls them after the consensus layer and never lets them overwrite a
value that structured data or a selector already produced.

Strategies, in order of reliability:
  * title       -> og:title / twitter:title meta -> <h1> -> cleaned <title>
  * price       -> price-ish elements (class/id/attr contains "price") -> a
                   currency-tagged number found anywhere in the visible text
  * availability-> in/out-of-stock phrases anywhere in the page text
  * image       -> og:image -> first content <img src>
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from . import normalize

# --- price detection in free text --------------------------------------------

# Currency symbols and ISO codes we recognize when scanning raw text.
_CUR_SYMBOL = r"(?:US\$|R\$|A\$|C\$|NZ\$|\$|€|£|¥|₹|₱|₩|₽)"
_CUR_CODE = r"(?:USD|EUR|GBP|JPY|INR|PHP|BRL|AUD|CAD|CNY|KRW|RUB|NZD|CHF|SEK|MXN|SGD|HKD)"
# A number with optional thousands/decimal separators (e.g. 1,299.00 or 1.299,00).
_NUM = r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
# A price token: a currency marker adjacent to a number, in any common order.
_PRICE_TOKEN_RE = re.compile(
    rf"(?:{_CUR_SYMBOL}\s?{_NUM}|{_CUR_CODE}\s?{_NUM}|{_NUM}\s?{_CUR_CODE})"
)

# Elements likely to hold a price (checked before scanning the whole page).
_PRICE_SELECTORS = (
    '[itemprop="price"]',
    "[data-price]",
    "[data-price-amount]",
    '[class*="price"]',
    '[class*="Price"]',
    '[class*="cost"]',
    '[class*="amount"]',
    '[class*="money"]',
    '[id*="price"]',
    '[id*="Price"]',
)

_TITLE_SEPARATORS = (" | ", " – ", " — ", " - ", " :: ", " • ")

_OUT_OF_STOCK_PHRASES = (
    "out of stock", "sold out", "unavailable", "currently unavailable", "out-of-stock",
)
_IN_STOCK_PHRASES = (
    "in stock", "in-stock", "add to cart", "add to basket", "add to bag", "buy now",
    "available",
)


def _meta(tree: HTMLParser, prop: str) -> str | None:
    for m in tree.css("meta"):
        key = m.attributes.get("property") or m.attributes.get("name")
        if key == prop:
            content = m.attributes.get("content")
            if content and content.strip():
                return content.strip()
    return None


def _clean_doc_title(text: str) -> str:
    """Strip a site suffix from a <title> ("Product | Store" -> "Product")."""
    for sep in _TITLE_SEPARATORS:
        if sep in text:
            parts = [p.strip() for p in text.split(sep) if p.strip()]
            if parts:
                # The product name is usually the longest segment.
                return max(parts, key=len)
    return text.strip()


def fallback_title(tree: HTMLParser) -> str | None:
    for prop in ("og:title", "twitter:title"):
        value = _meta(tree, prop)
        if value:
            return value
    h1 = tree.css_first("h1")
    if h1 and (h1.text() or "").strip():
        return " ".join((h1.text() or "").split())
    doc_title = tree.css_first("title")
    if doc_title and (doc_title.text() or "").strip():
        return _clean_doc_title(" ".join(doc_title.text().split()))
    return None


def _price_from_node(node) -> tuple[float | None, str | None]:
    # Attribute-carried prices are the cleanest (microdata/data-* patterns).
    for attr in ("content", "data-price", "data-price-amount", "value"):
        raw = node.attributes.get(attr)
        if raw:
            amount = normalize.normalize_number(raw)
            if amount and amount > 0:
                return amount, normalize.parse_currency(raw)
    text = (node.text() or "").strip()
    amount = normalize.normalize_number(text)
    if amount and amount > 0:
        return amount, normalize.parse_currency(text)
    return None, None


def fallback_price(tree: HTMLParser) -> tuple[float | None, str | None]:
    # 1) Elements whose class/id/attribute screams "price".
    for selector in _PRICE_SELECTORS:
        try:
            nodes = tree.css(selector)
        except Exception:  # pragma: no cover - defensive against odd selectors
            continue
        for node in nodes:
            amount, currency = _price_from_node(node)
            if amount is not None:
                return amount, currency
    # 2) Scan the visible text for a currency-tagged number.
    body = tree.body
    text = (body.text() if body else "") or ""
    for match in _PRICE_TOKEN_RE.finditer(text):
        token = match.group(0)
        amount = normalize.normalize_number(token)
        if amount and amount > 0:
            return amount, normalize.parse_currency(token)
    return None, None


def fallback_availability(tree: HTMLParser) -> str | None:
    body = tree.body
    text = ((body.text() if body else "") or "").lower()
    if not text:
        return None
    if any(p in text for p in _OUT_OF_STOCK_PHRASES):
        return "Out of stock"
    if any(p in text for p in _IN_STOCK_PHRASES):
        return "In stock"
    return None


def fallback_image(tree: HTMLParser) -> str | None:
    for prop in ("og:image", "twitter:image"):
        value = _meta(tree, prop)
        if value:
            return value
    img = tree.css_first("img[src]")
    if img:
        return img.attributes.get("src")
    return None
