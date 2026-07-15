"""Tests for the dashboard actions: add-site + run-now (roadmap item 8)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from crawlr import monitor
from crawlr.api import app
from crawlr.models import ExtractionResult


def test_add_site_and_run_now(monkeypatch):
    monkeypatch.setattr(
        monitor,
        "scrape",
        lambda url, schema, force_js=False: ExtractionResult(
            url=url, schema_name="product", records=[{"title": "Widget", "price": 9.99}]
        ),
    )

    with TestClient(app) as client:
        client.post(
            "/sites",
            data={"url": "https://shop.test/p1", "schema_name": "product", "interval": "30"},
        )

        sites = client.get("/api/sites").json()
        assert len(sites) == 1
        site_id = sites[0]["id"]

        assert "shop.test" in client.get("/").text

        client.post(f"/sites/{site_id}/run")
        records = client.get(f"/api/sites/{site_id}/records").json()
        assert records and records[0]["title"] == "Widget"


def test_dashboard_lists_schemas():
    with TestClient(app) as client:
        names = {s["name"] for s in client.get("/api/schemas").json()}
        assert {"product", "product_list"} <= names
