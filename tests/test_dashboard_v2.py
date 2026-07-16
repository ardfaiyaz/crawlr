"""Tests for the rewritten dashboard: health probes, XSS-safety, and actions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from crawlr import api, config, detect, storage
from crawlr.api import app
from crawlr.models import MonitoredSite


def _seed(title: str = "Widget") -> int:
    site_id = storage.add_site(
        MonitoredSite(url="https://shop.test/p", schema_name="product", interval_minutes=30)
    )
    storage.record_run(
        site_id,
        [{"title": title, "price": 10.0, "availability": "In stock"}],
        healed=False, used_llm=False,
    )
    return site_id


def test_health_and_ready():
    with TestClient(app) as client:
        health = client.get("/healthz").json()
        assert health["status"] == "ok" and health["version"]
        assert client.get("/readyz").json()["status"] == "ready"


def test_dashboard_escapes_scraped_html():
    _seed(title="<script>alert(1)</script>Evil")
    with TestClient(app) as client:
        body = client.get("/").text
        assert "<script>alert(1)</script>" not in body  # not rendered as raw HTML
        assert "&lt;script&gt;" in body                  # escaped instead


def test_pause_resume_delete(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    site_id = _seed()
    with TestClient(app) as client:
        client.post(f"/sites/{site_id}/pause")
        assert storage.get_site(site_id)["active"] == 0
        client.post(f"/sites/{site_id}/resume")
        assert storage.get_site(site_id)["active"] == 1
        client.post(f"/sites/{site_id}/delete")
        assert not any(s["id"] == site_id for s in client.get("/api/sites").json())


def test_site_detail_page():
    site_id = _seed()
    with TestClient(app) as client:
        page = client.get(f"/sites/{site_id}").text
        assert "Price history" in page
        assert client.get("/sites/99999").status_code == 404


def test_api_detect_endpoint(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    monkeypatch.setattr(detect, "detect_schema", lambda url, **kw: "jobs")
    with TestClient(app) as client:
        r = client.get("/api/detect", params={"url": "https://x.test/jobs/1"})
        assert r.status_code == 200
        assert r.json()["schema_name"] == "jobs"


def test_add_watch_autodetects_when_schema_blank(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    monkeypatch.setattr(detect, "detect_schema", lambda url, **kw: "product")
    monkeypatch.setattr(api, "_resolve_or_detect", lambda url, schema: schema or detect.detect_schema(url))
    with TestClient(app) as client:
        client.post("/sites", data={"url": "https://shop.test/auto", "schema_name": "", "interval": "45"})
        sites = client.get("/api/sites").json()
        assert any(s["url"] == "https://shop.test/auto" for s in sites)
