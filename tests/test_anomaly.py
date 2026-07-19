"""Tests for the statistical price-anomaly guard."""

from __future__ import annotations

import datetime
import types

from crawlr import anomaly, monitor, storage
from crawlr.models import MonitoredSite
from crawlr.verticals import ecommerce


def test_outlier_detected_via_mad():
    history = [100, 101, 99, 100, 102, 98]
    assert anomaly.is_price_outlier(500, history) is True
    assert anomaly.is_price_outlier(103, history) is False


def test_thin_history_is_never_flagged():
    assert anomaly.is_price_outlier(9999, [100, 101]) is False


def test_flat_history_flags_clear_jump():
    assert anomaly.is_price_outlier(160, [100] * 6) is True
    assert anomaly.is_price_outlier(101, [100] * 6) is False


def test_disabled_when_threshold_zero():
    assert anomaly.is_price_outlier(9999, [100] * 10, z_threshold=0) is False


def test_run_once_quarantines_anomalous_price(monkeypatch):
    site_id = storage.add_site(
        MonitoredSite(url="https://shop.test/p", schema_name="product", interval_minutes=5)
    )
    for _ in range(6):
        storage.record_run(
            site_id, [{"title": "W", "price": 100.0}],
            healed=False, used_llm=False, key_field="title",
        )

    def fake_scrape(url, schema, force_js=False):
        return types.SimpleNamespace(
            url=url, records=[{"title": "W", "price": 160.0}], healed=False, used_llm=False,
            confidence=1.0, fetched_at=datetime.datetime.now(datetime.timezone.utc),
            field_confidence={}, field_source={}, quality="high", warnings=[], valid=True,
        )

    monkeypatch.setattr(monitor, "scrape", fake_scrape)
    result, changes = monitor.run_once(site_id, ecommerce.PRODUCT_SCHEMA, watch_fields=["price"])

    assert [c for c in changes if c.field == "price"] == []  # quarantined
    assert any("nomal" in w.lower() for w in result.warnings)
