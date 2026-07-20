"""Per-field provenance is persisted per run and exposed in the watchlist."""

from __future__ import annotations

from crawlr import monitor, storage
from crawlr.models import ExtractionResult, MonitoredSite
from crawlr.verticals import ecommerce


def _result_with_sources(url: str) -> ExtractionResult:
    return ExtractionResult(
        url=url,
        schema_name="product",
        records=[{"title": "Widget", "price": 30.0, "availability": "In stock"}],
        field_source={"title": "both", "price": "structured", "availability": "selector"},
        quality="verified",
    )


def test_field_sources_persisted_and_in_watchlist(monkeypatch):
    sid = storage.add_site(MonitoredSite(url="https://s.test/p", schema_name="product"))
    monkeypatch.setattr(
        monitor, "scrape", lambda u, s, force_js=False: _result_with_sources(u)
    )
    monitor.run_once(sid, ecommerce.PRODUCT_SCHEMA)

    row = next(r for r in storage.watchlist() if r["id"] == sid)
    assert row["field_sources"] == {
        "title": "both",
        "price": "structured",
        "availability": "selector",
    }


def test_missing_field_sources_defaults_to_empty(monkeypatch):
    sid = storage.add_site(MonitoredSite(url="https://s.test/q", schema_name="product"))
    # No field_source provided on the result -> stored as NULL -> {} in watchlist.
    monkeypatch.setattr(
        monitor,
        "scrape",
        lambda u, s, force_js=False: ExtractionResult(
            url=u, schema_name="product", records=[{"title": "X", "price": 5.0}]
        ),
    )
    monitor.run_once(sid, ecommerce.PRODUCT_SCHEMA)
    row = next(r for r in storage.watchlist() if r["id"] == sid)
    assert row["field_sources"] == {}
