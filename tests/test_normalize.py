"""Tests for value normalization (currency / number / stock)."""

from __future__ import annotations

from crawlr import normalize


def test_number_us_format():
    assert normalize.normalize_number("$1,299.00") == 1299.0


def test_number_eu_format():
    assert normalize.normalize_number("1.299,00 €") == 1299.0


def test_number_lone_comma_decimal():
    assert normalize.normalize_number("19,99") == 19.99


def test_number_thousands_dots():
    assert normalize.normalize_number("1.299.000") == 1299000.0


def test_number_plain_and_invalid():
    assert normalize.normalize_number("49") == 49.0
    assert normalize.normalize_number("out of stock") is None
    assert normalize.normalize_number(None) is None


def test_parse_currency():
    assert normalize.parse_currency("$5.00") == "USD"
    assert normalize.parse_currency("€5") == "EUR"
    assert normalize.parse_currency("5 GBP") == "GBP"
    assert normalize.parse_currency("5") is None


def test_normalize_price_tuple():
    assert normalize.normalize_price("$1,299.00") == (1299.0, "USD")


def test_normalize_stock():
    assert normalize.normalize_stock("In Stock") is True
    assert normalize.normalize_stock("Sold Out") is False
    assert normalize.normalize_stock("mystery") is None
