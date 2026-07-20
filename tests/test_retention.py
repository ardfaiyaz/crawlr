"""Tests for automatic history retention/pruning (scalability hygiene)."""

from __future__ import annotations

from crawlr import config, db, extractor, monitor, storage
from crawlr.fetcher import FetchResult
from crawlr.models import MonitoredSite
from crawlr.verticals import ecommerce
from tests import fixtures


def _patch_fetch(monkeypatch, html: str, url: str):
    monkeypatch.setattr(
        extractor,
        "fetch",
        lambda u, force_js=False: FetchResult(url=url, html=html, status_code=200),
    )


def _run_count(site_id: int) -> int:
    with db.connect() as conn:
        row = conn.execute(
            db.q("SELECT COUNT(*) AS c FROM runs WHERE site_id=?"), (site_id,)
        ).fetchone()
    return int(row["c"])


def test_prune_site_runs_keeps_most_recent():
    site_id = storage.add_site(
        MonitoredSite(url="https://shop.test/x", schema_name="product_list", interval_minutes=1)
    )
    for _ in range(5):
        storage.record_run(site_id, [{"title": "a", "price": 1.0}], healed=False, used_llm=False)
    assert _run_count(site_id) == 5

    deleted = storage.prune_site_runs(site_id, keep_runs=2)
    assert deleted == 3
    assert _run_count(site_id) == 2

    # keep_runs <= 0 is a no-op.
    assert storage.prune_site_runs(site_id, keep_runs=0) == 0
    assert _run_count(site_id) == 2


def test_retention_applied_in_run_once_preserves_diffing(monkeypatch):
    monkeypatch.setattr(config, "RETENTION_RUNS", 1)
    url = "https://shop.test/search"
    site_id = storage.add_site(
        MonitoredSite(url=url, schema_name="product_list", interval_minutes=1)
    )

    _patch_fetch(monkeypatch, fixtures.LISTING_V1, url)
    monitor.run_once(site_id, ecommerce.PRODUCT_LIST_SCHEMA, watch_fields=["price"])

    _patch_fetch(monkeypatch, fixtures.LISTING_V2, url)
    _, changes = monitor.run_once(site_id, ecommerce.PRODUCT_LIST_SCHEMA, watch_fields=["price"])

    # Change detection still works even though only one run is retained.
    price_changes = [c for c in changes if c.field == "price"]
    assert len(price_changes) == 1
    assert price_changes[0].new_value == "19.99"
    # Retention kept exactly one run.
    assert _run_count(site_id) == 1
