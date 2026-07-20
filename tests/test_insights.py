"""Tests for price-history analytics (storage, API, and CLI surfacing)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from crawlr import config, storage
from crawlr.api import app
from crawlr.cli import app as cli_app
from crawlr.models import MonitoredSite

runner = CliRunner()


def _seed(prices) -> int:
    site_id = storage.add_site(
        MonitoredSite(url="https://shop.test/p", schema_name="product", interval_minutes=30)
    )
    for p in prices:
        storage.record_run(site_id, [{"title": "W", "price": p}], healed=False, used_llm=False)
    return site_id


def test_price_insights():
    site_id = _seed([30.0, 20.0, 25.0])
    ins = storage.price_insights(site_id)  # single-product => item_key None
    assert ins["count"] == 3
    assert ins["low"] == 20.0
    assert ins["high"] == 30.0
    assert ins["current"] == 25.0
    assert ins["is_all_time_low"] is False


def test_watchlist_includes_low_and_all_time_low():
    site_id = _seed([30.0, 20.0])  # newest (last) is the lowest
    row = next(r for r in storage.watchlist() if r["id"] == site_id)
    assert row["low"] == 20.0
    assert row["is_all_time_low"] is True


def test_api_insights_endpoint(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    site_id = _seed([10.0])
    with TestClient(app) as client:
        data = client.get("/api/insights", params={"site_id": site_id}).json()
        assert data["count"] == 1 and data["low"] == 10.0


def test_cli_insights_json():
    site_id = _seed([5.0, 7.0])
    result = runner.invoke(cli_app, ["insights", str(site_id), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["low"] == 5.0 and data["high"] == 7.0
