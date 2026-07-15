"""Tests for the async concurrent runner + scheduler (roadmap items 5 & 6)."""

from __future__ import annotations

import asyncio

from crawlr import monitor, scheduler, storage
from crawlr.models import ExtractionResult, MonitoredSite
from crawlr.verticals import ecommerce


def _fake_result(url: str) -> ExtractionResult:
    return ExtractionResult(
        url=url, schema_name="product", records=[{"title": "X", "price": 1.0}]
    )


def test_run_due_async_runs_all_due_sites(monkeypatch):
    ids = [
        storage.add_site(
            MonitoredSite(url=f"https://s{i}.test/p", schema_name="product", interval_minutes=60)
        )
        for i in range(3)
    ]
    monkeypatch.setattr(monitor, "scrape", lambda url, schema, force_js=False: _fake_result(url))

    results = asyncio.run(monitor.run_due_async(ecommerce.resolve, concurrency=2))

    assert set(results.keys()) == set(ids)


def test_scheduler_runs_bounded_iterations(monkeypatch):
    async def fake_run_due_async(resolver, concurrency=5, force_js=False):
        return {}

    monkeypatch.setattr(monitor, "run_due_async", fake_run_due_async)
    iterations = asyncio.run(scheduler.run_forever(poll_seconds=0, max_iterations=3))
    assert iterations == 3
