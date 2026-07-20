"""Per-site anomaly and retention overrides win over the global config."""

from __future__ import annotations

import datetime
import types

from crawlr import monitor, storage
from crawlr.models import MonitoredSite
from crawlr.verticals import ecommerce


def _fake_scrape(price: float, content_hash: str):
    def _scrape(url, schema, force_js=False):
        return types.SimpleNamespace(
            url=url, records=[{"title": "W", "price": price}], healed=False, used_llm=False,
            confidence=1.0, fetched_at=datetime.datetime.now(datetime.timezone.utc),
            field_confidence={}, field_source={}, quality="high", warnings=[], valid=True,
            blocked=False, rendered_with_js=False, content_hash=content_hash,
        )

    return _scrape


def test_overrides_persisted_on_site():
    sid = storage.add_site(
        MonitoredSite(
            url="https://s.test/p",
            schema_name="product",
            anomaly_zscore=3.0,
            anomaly_min_samples=4,
            retention_runs=2,
        )
    )
    site = storage.get_site(sid)
    assert site["anomaly_zscore"] == 3.0
    assert site["anomaly_min_samples"] == 4
    assert site["retention_runs"] == 2

    row = next(r for r in storage.watchlist() if r["id"] == sid)
    assert row["retention_runs"] == 2


def test_per_site_retention_prunes_runs(monkeypatch):
    sid = storage.add_site(
        MonitoredSite(url="https://s.test/r", schema_name="product", retention_runs=2)
    )
    # Seed some prior runs directly.
    for _ in range(4):
        storage.record_run(
            sid, [{"title": "W", "price": 100.0}], healed=False, used_llm=False, key_field="title"
        )

    monkeypatch.setattr(monitor, "scrape", _fake_scrape(101.0, "h1"))
    monitor.run_once(sid, ecommerce.PRODUCT_SCHEMA, watch_fields=["price"])

    # After the run + pruning, at most retention_runs (2) runs remain.
    with storage.db.connect() as conn:
        count = conn.execute(
            storage.db.q("SELECT COUNT(*) AS n FROM runs WHERE site_id=?"), (sid,)
        ).fetchone()["n"]
    assert count == 2


def test_per_site_anomaly_disable(monkeypatch):
    """anomaly_zscore=0 disables the guard even when the global default is on."""
    sid = storage.add_site(
        MonitoredSite(url="https://s.test/a", schema_name="product", anomaly_zscore=0)
    )
    # Build a flat history that a wild jump would normally trip.
    for _ in range(6):
        storage.record_run(
            sid, [{"title": "W", "price": 100.0}], healed=False, used_llm=False, key_field="title"
        )

    monkeypatch.setattr(monitor, "scrape", _fake_scrape(160.0, "h160"))
    _, changes = monitor.run_once(sid, ecommerce.PRODUCT_SCHEMA, watch_fields=["price"])

    # Guard disabled -> the price change is NOT quarantined.
    assert any(c.field == "price" and c.new_value == "160.0" for c in changes)
