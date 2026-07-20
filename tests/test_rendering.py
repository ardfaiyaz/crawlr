"""Tests for block detection, blocked-run skipping, and stale-page detection."""

from __future__ import annotations

from crawlr import extractor, fetcher, monitor, storage
from crawlr.fetcher import FetchResult
from crawlr.models import MonitoredSite
from crawlr.verticals import ecommerce


def test_detect_block_status_and_markers():
    assert fetcher.detect_block(403, "<html></html>") == "http 403"
    assert fetcher.detect_block(200, "<html>Just a moment... Cloudflare</html>") == "anti-bot challenge"
    assert fetcher.detect_block(200, "<html>real content</html>") is None


def test_js_shell_detection():
    shell = "<html><body></body><script></script><script></script><script></script></html>"
    assert fetcher._looks_like_js_shell(shell) is True
    full = "<html><body>" + ("real product content " * 40) + "</body></html>"
    assert fetcher._looks_like_js_shell(full) is False


def _patch_fetch(monkeypatch, result: FetchResult):
    monkeypatch.setattr(extractor, "fetch", lambda url, force_js=False: result)


def test_blocked_run_is_not_recorded(monkeypatch):
    site_id = storage.add_site(
        MonitoredSite(url="https://shop.test/p", schema_name="product", interval_minutes=5)
    )
    _patch_fetch(
        monkeypatch,
        FetchResult(url="https://shop.test/p", html="", status_code=403,
                    blocked=True, blocked_reason="http 403"),
    )
    result, changes = monitor.run_once(site_id, ecommerce.PRODUCT_SCHEMA)
    assert result.blocked is True
    assert changes == []
    # Nothing persisted -> the site stays "due" for a retry.
    assert storage.latest_run(site_id) is None


def test_stale_page_detected(monkeypatch):
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type":"Product","name":"Widget","offers":{"price":"9.99","availability":"InStock"}}'
        "</script></head><body>Widget 9.99</body></html>"
    )
    site_id = storage.add_site(
        MonitoredSite(url="https://shop.test/p", schema_name="product", interval_minutes=5)
    )
    _patch_fetch(monkeypatch, FetchResult(url="https://shop.test/p", html=html, status_code=200))

    monitor.run_once(site_id, ecommerce.PRODUCT_SCHEMA)   # first run records the hash
    result, _ = monitor.run_once(site_id, ecommerce.PRODUCT_SCHEMA)  # identical content
    assert any("unchanged" in w.lower() for w in result.warnings)
    assert result.content_hash is not None
