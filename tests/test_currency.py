"""Tests for multi-currency conversion (pinned offline rates + overrides)."""

from __future__ import annotations

import importlib

from crawlr import currency


def test_pinned_rates_anchor_usd():
    rates = currency.pinned_rates()
    assert rates["USD"] == 1.0
    assert rates["EUR"] > 0
    assert rates["GBP"] > 0


def test_convert_same_currency_is_identity():
    assert currency.convert(42.0, "USD", "USD") == 42.0


def test_convert_across_currencies_roundtrips():
    rates = currency.pinned_rates()
    usd = 100.0
    eur = currency.convert(usd, "USD", "EUR", rates)
    assert eur is not None
    back = currency.convert(eur, "EUR", "USD", rates)
    assert back is not None
    assert abs(back - usd) < 0.01


def test_convert_unknown_currency_returns_none():
    assert currency.convert(10.0, "ZZZ", "USD") is None
    assert currency.convert(10.0, "USD", "ZZZ") is None
    assert currency.convert(10.0, None, "USD") is None
    assert currency.convert(None, "USD", "EUR") is None


def test_pinned_overrides_applied(monkeypatch):
    monkeypatch.setenv("CRAWLR_FX_RATES", "EUR=2.0")
    import crawlr.config as config

    importlib.reload(config)
    importlib.reload(currency)
    try:
        # 1 USD -> 2 EUR under the forced override.
        assert currency.convert(1.0, "USD", "EUR") == 2.0
    finally:
        monkeypatch.delenv("CRAWLR_FX_RATES", raising=False)
        importlib.reload(config)
        importlib.reload(currency)


def test_get_rates_offline_uses_pinned(monkeypatch):
    # FX_LIVE defaults to false in tests -> pinned source, no network.
    rates, source = currency.get_rates()
    assert source == "pinned"
    assert rates["USD"] == 1.0
