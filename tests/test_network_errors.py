"""A network failure (DNS/connection) is handled gracefully, not crashed on.

Regression test: previously an unreachable host raised httpx.ConnectError all the
way out of `crawlr monitor`. Now `fetch` converts it into a blocked result and
the monitor skips that site (leaving it "due" for a retry) without aborting.
"""

from __future__ import annotations

import httpx

from crawlr import extractor, fetcher, monitor, storage
from crawlr.fetcher import FetchResult
from crawlr.models import MonitoredSite
from crawlr.verticals import ecommerce


def test_fetch_returns_blocked_on_connect_error(monkeypatch):
    monkeypatch.setattr(fetcher, "_robots_allows", lambda url: True)
    monkeypatch.setattr(fetcher, "_respect_rate_limit", lambda url: None)

    def boom(url):
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

    monkeypatch.setattr(fetcher, "_fetch_static", boom)

    result = fetcher.fetch("https://unreachable.invalid/p")
    assert result.blocked is True
    assert result.html == ""
    assert "connection error" in (result.blocked_reason or "").lower()


def test_monitor_skips_unreachable_site_without_crashing(monkeypatch):
    sid = storage.add_site(
        MonitoredSite(url="https://unreachable.invalid/p", schema_name="product", interval_minutes=1)
    )

    def blocked_fetch(url, force_js=False):
        return FetchResult(
            url=url, html="", status_code=0, blocked=True,
            blocked_reason="connection error (ConnectError)",
        )

    monkeypatch.setattr(extractor, "fetch", blocked_fetch)

    # Must not raise, and must not record a (poisoned) run.
    result, changes = monitor.run_once(sid, ecommerce.PRODUCT_SCHEMA)
    assert result.blocked is True
    assert changes == []
    assert storage.latest_run(sid) is None  # nothing stored -> site stays due


def test_run_due_isolates_one_failing_site(monkeypatch):
    good = storage.add_site(
        MonitoredSite(url="https://ok.invalid/p", schema_name="product", interval_minutes=1)
    )
    bad = storage.add_site(
        MonitoredSite(url="https://boom.invalid/p", schema_name="product", interval_minutes=1)
    )

    def flaky(site_id, schema, watch_fields=None, force_js=False, send_alerts=True):
        if site_id == bad:
            raise RuntimeError("unexpected explosion")
        from crawlr.models import ExtractionResult
        return ExtractionResult(url="https://ok.invalid/p", schema_name="product"), []

    monkeypatch.setattr(monitor, "run_once", flaky)

    results = monitor.run_due(ecommerce.resolve)
    # Both sites appear in results; the failing one just has no changes.
    assert set(results) == {good, bad}
    assert results[bad] == []
