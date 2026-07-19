"""Tests for deal scoring, availability stats, and persisted quality."""

from __future__ import annotations

from crawlr import storage
from crawlr.models import MonitoredSite


def _add() -> int:
    return storage.add_site(
        MonitoredSite(url="https://shop.test/p", schema_name="product", interval_minutes=5)
    )


def _run(site_id: int, price: float, availability: str) -> None:
    storage.record_run(
        site_id, [{"title": "W", "price": price, "availability": availability}],
        healed=False, used_llm=False, key_field="title",
    )


def test_deal_score_and_availability():
    site_id = _add()
    _run(site_id, 100.0, "In stock")
    _run(site_id, 100.0, "Out of stock")
    _run(site_id, 80.0, "In stock")   # now cheapest + back in stock

    ins = storage.price_insights(site_id, "W")
    assert ins["deal_score"] == 100      # all-time low + rarely this cheap
    assert ins["is_all_time_low"] is True

    av = storage.availability_stats(site_id, "W")
    assert av["samples"] == 3
    assert av["restocks"] == 1
    assert av["currently_in_stock"] is True


def test_quality_persisted_and_surfaced_in_watchlist():
    site_id = _add()
    storage.record_run(
        site_id, [{"title": "W", "price": 10.0}],
        healed=False, used_llm=False, key_field="title", quality="verified",
    )
    row = next(r for r in storage.watchlist() if r["id"] == site_id)
    assert row["quality"] == "verified"
