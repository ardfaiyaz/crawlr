"""Tests for the plausibility guard on price changes."""

from __future__ import annotations

from crawlr import monitor
from crawlr.models import PriceChange


def _pc(field, old, new):
    return PriceChange(product_url="p", field=field, old_value=old, new_value=new)


def test_normal_change_is_plausible():
    assert monitor._plausible_change(_pc("price", "100", "95"))


def test_zero_or_missing_new_price_rejected():
    assert not monitor._plausible_change(_pc("price", "100", "0"))
    assert not monitor._plausible_change(_pc("price", "100", "not-a-price"))


def test_extreme_moves_rejected():
    assert not monitor._plausible_change(_pc("price", "100", "5000"))  # 50x up
    assert not monitor._plausible_change(_pc("price", "100", "2"))     # 50x down


def test_non_price_changes_always_pass():
    assert monitor._plausible_change(_pc("availability", "Out of stock", "In stock"))
    assert monitor._plausible_change(_pc("_new_item", None, "x"))
