"""Tests for the alerting module + threshold rules (roadmap item 1)."""

from __future__ import annotations

from crawlr import alerts
from crawlr.config import AlertConfig
from crawlr.models import PriceChange


def _pc(field: str, old, new, key: str = "p1") -> PriceChange:
    return PriceChange(product_url=key, field=field, old_value=old, new_value=new)


def test_alertable_filters_small_price_drops(monkeypatch):
    monkeypatch.setattr(alerts, "ALERTS", AlertConfig(min_price_drop_pct=0.1))
    small = _pc("price", "100", "95")  # 5% drop -> below threshold
    big = _pc("price", "100", "80")  # 20% drop -> alert
    out = alerts.alertable([small, big])
    assert big in out and small not in out


def test_alertable_passes_non_price_fields(monkeypatch):
    monkeypatch.setattr(alerts, "ALERTS", AlertConfig(min_price_drop_pct=0.5))
    change = _pc("availability", "Out of Stock", "In Stock")
    assert alerts.alertable([change]) == [change]


def test_notify_dispatches_to_webhook(monkeypatch):
    monkeypatch.setattr(alerts, "ALERTS", AlertConfig(min_price_drop_pct=0.0, console=False))
    captured: dict = {}
    monkeypatch.setattr(alerts, "_send_webhook", lambda payload: captured.update(payload))

    sent = alerts.notify("https://shop.test", [_pc("price", "10", "8")])

    assert len(sent) == 1
    assert captured["site"] == "https://shop.test"
    assert captured["count"] == 1


def test_price_drop_description(monkeypatch):
    monkeypatch.setattr(alerts, "ALERTS", AlertConfig(min_price_drop_pct=0.0))
    text = alerts._describe(_pc("price", "100", "75"))
    assert "dropped" in text and "25.0%" in text
