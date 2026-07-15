"""Tests for the watch workflow: storage of trigger/target, watchlist, dashboard."""

from __future__ import annotations

from fastapi.testclient import TestClient

from crawlr import monitor, storage
from crawlr.api import app
from crawlr.models import ExtractionResult, MonitoredSite, TriggerType
from crawlr.verticals import ecommerce


def _result(url: str, price: float, availability: str) -> ExtractionResult:
    return ExtractionResult(
        url=url,
        schema_name="product",
        records=[{"title": "Widget", "price": price, "availability": availability}],
    )


def test_site_stores_trigger_and_target():
    sid = storage.add_site(
        MonitoredSite(
            url="https://s.test/p",
            schema_name="product",
            trigger=TriggerType.PRICE_BELOW,
            target_price=25,
        )
    )
    site = storage.get_site(sid)
    assert site["alert_trigger"] == "price_below"
    assert site["target_price"] == 25


def test_watchlist_assembles_price_movement_and_stock(monkeypatch):
    sid = storage.add_site(
        MonitoredSite(url="https://s.test/p", schema_name="product", trigger=TriggerType.PRICE_DROP)
    )
    monkeypatch.setattr(monitor, "scrape", lambda u, s, force_js=False: _result(u, 30.0, "In stock"))
    monitor.run_once(sid, ecommerce.PRODUCT_SCHEMA)
    monkeypatch.setattr(monitor, "scrape", lambda u, s, force_js=False: _result(u, 24.0, "In stock"))
    monitor.run_once(sid, ecommerce.PRODUCT_SCHEMA)

    row = next(r for r in storage.watchlist() if r["id"] == sid)
    assert row["price"] == 24.0
    assert row["prev_price"] == 30.0
    assert row["change_pct"] == -20.0
    assert row["in_stock"] is True
    assert row["status"] == "price dropped"


def test_dashboard_add_watch_with_trigger():
    with TestClient(app) as client:
        client.post(
            "/sites",
            data={
                "url": "https://shop.test/p",
                "schema_name": "product",
                "alert_trigger": "price_below",
                "target_price": "25",
                "interval": "30",
            },
        )
        sites = client.get("/api/sites").json()
        assert len(sites) == 1
        assert sites[0]["alert_trigger"] == "price_below"
        assert sites[0]["target_price"] == 25.0
        assert len(client.get("/api/watchlist").json()) == 1
