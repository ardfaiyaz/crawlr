"""Tests for per-site stats and the golden accuracy eval harness."""

from __future__ import annotations

from crawlr import eval as crawlr_eval
from crawlr import monitor, storage
from crawlr.models import ExtractionResult, MonitoredSite
from crawlr.verticals import ecommerce


def test_site_stats(monkeypatch):
    sid = storage.add_site(MonitoredSite(url="https://s.test/p", schema_name="product"))
    monkeypatch.setattr(
        monitor, "scrape",
        lambda u, s, force_js=False: ExtractionResult(
            url=u, schema_name="product",
            records=[{"title": "W", "price": 9.99, "availability": "In stock"}],
            confidence=0.9,
        ),
    )
    monitor.run_once(sid, ecommerce.PRODUCT_SCHEMA)
    row = next(r for r in storage.site_stats() if r["id"] == sid)
    assert row["runs"] == 1
    assert row["avg_confidence"] is not None


def test_golden_eval_passes():
    result = crawlr_eval.run_eval()
    assert result["cases"] >= 2
    assert result["accuracy"] == 1.0, result["failures"]
