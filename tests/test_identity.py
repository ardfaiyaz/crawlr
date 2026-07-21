"""Tests for the product-identity resolver used by canvas grouping."""

from __future__ import annotations

from dataclasses import dataclass

from crawlr import identity


@dataclass
class L:
    title: str
    sku: str | None = None
    gtin: str | None = None
    brand: str | None = None


def test_gtin_is_authoritative():
    a = L("Some Keyboard", gtin="1234567890123")
    b = L("Totally Different Name", gtin="1234567890123")
    assert identity.same_product(a, b) is True
    c = L("Some Keyboard", gtin="9999999999999")
    assert identity.same_product(a, c) is False


def test_different_brands_never_match():
    a = L("Logitech G Pro X Superlight")
    b = L("Razer Viper V3 Pro")
    assert identity.same_product(a, b) is False


def test_same_model_variants_match():
    a = L("Logitech G Pro X Superlight")
    b = L("Logitech G Pro X Superlight Wireless Gaming Mouse Black")
    assert identity.same_product(a, b) is True


def test_different_models_same_brand_do_not_match():
    a = L("Logitech G502 X Gaming Mouse")
    b = L("Logitech G Pro X Superlight")
    assert identity.same_product(a, b) is False


def test_model_tokens_and_gtin_normalize():
    assert "g502" in identity.model_tokens("Logitech G502 X")
    assert identity.normalize_gtin("12-3456 7890123") == "1234567890123"
    assert identity.normalize_gtin("123") is None


def test_canonical_key_prefers_gtin():
    assert identity.canonical_key("1234567890123", "SKU9", "Logitech") == "gtin:1234567890123"
    assert identity.canonical_key(None, "SKU9", "Logitech") == "sku:logitech:sku9"
    assert identity.canonical_key(None, None, None, "no id here") is None
