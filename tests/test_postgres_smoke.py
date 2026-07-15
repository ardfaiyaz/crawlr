"""Guarded Postgres backend smoke test.

Skipped unless ``CRAWLR_TEST_DATABASE_URL`` points at a reachable Postgres
instance (CI provides one via a service container). This exercises the *same*
db/storage/selector-cache code paths the SQLite suite uses, but against the
Postgres dialect — verifying placeholder adaptation, ``RETURNING id`` inserts,
``ON CONFLICT`` upserts, retention pruning, and the DB-backed selector cache.

It deliberately bypasses the sqlite-forcing autouse fixture by setting
``CRAWLR_DATABASE_URL`` and reloading the config-dependent modules itself.
"""

from __future__ import annotations

import importlib
import os

import pytest

PG_URL = os.getenv("CRAWLR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="set CRAWLR_TEST_DATABASE_URL to run the Postgres smoke test"
)


def test_postgres_backend_smoke(monkeypatch):
    pytest.importorskip("psycopg")

    monkeypatch.setenv("CRAWLR_DATABASE_URL", PG_URL)
    import crawlr.config as config

    importlib.reload(config)
    assert config.DATABASE_URL
    for name in ("crawlr.db", "crawlr.selector_cache", "crawlr.usage", "crawlr.storage"):
        importlib.reload(importlib.import_module(name))

    from crawlr import db, selector_cache, storage
    from crawlr.models import MonitoredSite
    from crawlr.verticals import ecommerce

    assert db.BACKEND == "postgres"

    # Start from a clean schema so repeated CI runs are deterministic.
    with db.connect() as conn:
        for table in ("changes", "records", "runs", "sites", "selectors"):
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    storage.init_db()

    # Sites: insert + upsert (ON CONFLICT) + RETURNING id.
    site = MonitoredSite(url="https://pg.test/x", schema_name="product_list", interval_minutes=5)
    site_id = storage.add_site(site)
    assert site_id
    assert storage.add_site(site) == site_id  # upsert returns same id
    assert any(s["id"] == site_id for s in storage.list_sites())

    # Runs + retention pruning across the Postgres dialect.
    storage.record_run(site_id, [{"title": "a", "price": 1.0}], healed=False, used_llm=False)
    storage.record_run(site_id, [{"title": "a", "price": 2.0}], healed=False, used_llm=False)
    assert storage.prune_site_runs(site_id, keep_runs=1) == 1

    # Selector cache round-trips through the selectors table.
    selector_cache.put("https://pg.test/x", ecommerce.PRODUCT_LIST_SCHEMA)
    cached = selector_cache.get("https://pg.test/x", ecommerce.PRODUCT_LIST_SCHEMA.name)
    assert cached is not None
