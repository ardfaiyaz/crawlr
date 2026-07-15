"""Value normalization: currency, numbers, and stock text -> canonical types.

Real-world price strings are messy ("$1,299.00", "1.299,00 EUR", "US$ 49"). A
dedicated normalization layer turns them into clean floats + currency codes, so
comparisons and change detection are accurate regardless of locale/formatting.
"""

from __future__ import annotations

import re

# Symbol -> ISO code. Order matters (check multi-char before single-char).
_CURRENCY_SYMBOLS = [
    ("US$", "USD"), ("R$", "BRL"), ("A$", "AUD"), ("C$", "CAD"), ("NZ$", "NZD"),
    ("$", "USD"), ("€", "EUR"), ("£", "GBP"), ("¥", "JPY"), ("₹", "INR"),
    ("₱", "PHP"), ("₩", "KRW"), ("₽", "RUB"),
]
_CURRENCY_CODES = {
    "USD", "EUR", "GBP", "JPY", "INR", "PHP", "BRL", "AUD", "CAD",
    "CNY", "KRW", "RUB", "NZD", "CHF", "SEK", "MXN", "SGD", "HKD",
}

_NUM_RE = re.compile(r"[-+]?\d[\d.,]*")


def parse_currency(text) -> str | None:
    if text is None:
        return None
    t = str(text)
    for sym, code in _CURRENCY_SYMBOLS:
        if sym in t:
            return code
    up = t.upper()
    for code in _CURRENCY_CODES:
        if re.search(rf"\b{code}\b", up):
            return code
    return None


def _clean_number(num: str) -> str:
    """Resolve thousands vs decimal separators into a plain float string."""
    has_comma, has_dot = "," in num, "." in num
    if has_comma and has_dot:
        # The right-most separator is the decimal point.
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif has_comma:
        # A lone comma with 1-2 trailing digits is a decimal (e.g. "19,99").
        parts = num.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            num = num.replace(",", ".")
        else:
            num = num.replace(",", "")
    elif num.count(".") > 1:
        # Multiple dots => thousands separators (e.g. "1.299.000").
        num = num.replace(".", "")
    return num


def normalize_number(text) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    match = _NUM_RE.search(str(text))
    if not match:
        return None
    try:
        return float(_clean_number(match.group(0).strip(".,")))
    except ValueError:
        return None


def normalize_price(text) -> tuple[float | None, str | None]:
    """Return (amount, currency_code) parsed from a messy price string."""
    return normalize_number(text), parse_currency(text)


_IN_STOCK = ("in stock", "in-stock", "in_stock", "instock", "available", "add to cart")
_OUT_OF_STOCK = ("out of stock", "out-of-stock", "sold out", "unavailable", "backorder")


def normalize_stock(text) -> bool | None:
    """Interpret availability text; None when it can't be determined."""
    if text is None:
        return None
    t = str(text).strip().lower()
    if not t:
        return None
    if any(k in t for k in _OUT_OF_STOCK):
        return False
    if any(k in t for k in _IN_STOCK):
        return True
    return None
