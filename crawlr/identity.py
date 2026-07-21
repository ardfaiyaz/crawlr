"""Product identity — decide when two listings are the *same* product.

Lexical title matching alone lumps different models together ("Logitech Pro X"
keyboard vs. the "G Pro X Superlight" mouse). This module resolves identity by
the strongest available signal:

    1. GTIN / EAN / UPC  — a global barcode: exact match = same product.
    2. SKU + compatible brand.
    3. Brand + shared model tokens (e.g. "g502", "60he", "rtx5070") + title
       similarity — with a hard rule that *different* known brands are never
       the same product.

Used by canvas for accurate cross-store grouping and comparison.
"""

from __future__ import annotations

import difflib
import re
from typing import Protocol


class _Listing(Protocol):
    title: str
    sku: str | None
    gtin: str | None
    brand: str | None


# Brands we recognise in a title so "Logitech …" vs "Razer …" never merge.
_KNOWN_BRANDS = {
    "logitech", "razer", "steelseries", "asus", "acer", "lenovo", "hp", "dell",
    "msi", "gigabyte", "corsair", "hyperx", "cooler", "nzxt", "intel", "amd",
    "nvidia", "samsung", "apple", "sony", "lg", "xiaomi", "redragon", "keychron",
    "akko", "royal", "glorious", "pulsar", "nike", "adidas", "canon", "nikon",
    "bosch", "makita", "anker", "baseus", "ugreen", "seagate", "wd", "kingston",
    "adata", "crucial", "tplink", "dlink", "epson", "brother", "lexar", "sandisk",
}

_STOPWORDS = {
    "the", "and", "for", "with", "pro", "plus", "max", "mini", "new", "set",
    "wireless", "wired", "gaming", "mouse", "keyboard", "headset", "black",
    "white", "rgb", "edition", "version", "official", "brand", "original",
}


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", s)
    return re.sub(r"\s+", " ", s)


def normalize_gtin(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits if len(digits) in (8, 12, 13, 14) else None


def brand_of(title: str, explicit: str | None = None) -> str | None:
    """Best-effort brand: an explicit field, else the first known brand token."""
    if explicit and explicit.strip():
        return explicit.strip().lower()
    for tok in re.split(r"\W+", (title or "").lower()):
        if tok in _KNOWN_BRANDS:
            return tok
    return None


def model_tokens(title: str) -> set[str]:
    """Distinguishing tokens — alphanumerics containing a digit (g502, 60he,
    rtx5070, 005882) — which pin down the exact model. Kept intact (not split on
    the letter/digit boundary) so 'g502' and 'm502' stay different."""
    toks: set[str] = set()
    for raw in re.split(r"[^a-z0-9]+", (title or "").lower()):
        if raw and any(ch.isdigit() for ch in raw) and raw not in _STOPWORDS:
            toks.add(raw)
    return toks


def canonical_key(
    gtin: str | None, sku: str | None, brand: str | None, title: str = ""
) -> str | None:
    """A stable join key when we have a strong identity signal, else None."""
    g = normalize_gtin(gtin)
    if g:
        return f"gtin:{g}"
    b = brand_of(title, brand)
    if sku and b:
        return f"sku:{b}:{sku.strip().lower()}"
    return None


def _brands_compatible(a: _Listing, b: _Listing) -> bool:
    ba = brand_of(a.title, a.brand)
    bb = brand_of(b.title, b.brand)
    if ba and bb:
        return ba == bb
    return True  # unknown brand on either side: don't rule it out


def same_product(a: _Listing, b: _Listing) -> bool:
    """True if two listings are (very likely) the same product."""
    ga, gb = normalize_gtin(a.gtin), normalize_gtin(b.gtin)
    if ga and gb:
        return ga == gb  # barcodes are authoritative

    if not _brands_compatible(a, b):
        return False  # different known brands => different product

    if a.sku and b.sku and a.sku.strip().lower() == b.sku.strip().lower():
        return True

    ta, tb = _norm(a.title), _norm(b.title)
    if not ta or not tb:
        return False
    if ta == tb:
        return True

    ma, mb = model_tokens(a.title), model_tokens(b.title)
    if ma and mb:
        if not (ma & mb):
            return False  # both have model numbers but none shared => different
        shared = len(ma & mb) / min(len(ma), len(mb))
        if shared >= 0.5:
            return True
    elif ma or mb:
        # One side has a model number, the other doesn't — require containment.
        return ta in tb or tb in ta

    if ta in tb or tb in ta:
        return True
    return difflib.SequenceMatcher(None, ta, tb).ratio() >= 0.82
