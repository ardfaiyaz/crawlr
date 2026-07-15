"""Tests for the hosted JSON API: auth gate + programmatic endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from crawlr import api, config
from crawlr.api import app
from crawlr.models import ExtractionResult


def test_api_open_when_no_key(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    with TestClient(app) as client:
        assert client.get("/api/sites").status_code == 200


def test_api_requires_key_when_configured(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "secret")
    with TestClient(app) as client:
        assert client.get("/api/sites").status_code == 401
        assert client.get("/api/sites", headers={"X-API-Key": "secret"}).status_code == 200
        assert client.get(
            "/api/sites", headers={"Authorization": "Bearer secret"}
        ).status_code == 200


def test_api_scrape_endpoint(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    monkeypatch.setattr(
        api, "scrape_url",
        lambda url, schema: ExtractionResult(
            url=url, schema_name="product", records=[{"title": "X", "price": 1.0}]
        ),
    )
    with TestClient(app) as client:
        r = client.post("/api/scrape", json={"url": "https://x.test/p", "schema_name": "product"})
        assert r.status_code == 200
        assert r.json()["records"][0]["title"] == "X"


def test_api_watch_endpoint(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    with TestClient(app) as client:
        r = client.post(
            "/api/watch",
            json={"url": "https://x.test/p", "schema_name": "product",
                  "trigger": "price_below", "target_price": 25},
        )
        assert r.status_code == 200
        assert r.json()["trigger"] == "price_below"
        assert len(client.get("/api/sites").json()) == 1
