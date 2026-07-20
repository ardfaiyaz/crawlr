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



def _patch_fetch_internals(monkeypatch):
    monkeypatch.setattr(fetcher, "_robots_allows", lambda url: True)
    monkeypatch.setattr(fetcher, "_respect_rate_limit", lambda url: None)
    monkeypatch.setattr(fetcher.providers, "enabled", lambda: False)


def test_auto_js_escalates_on_block(monkeypatch):
    # A blocked static fetch is automatically re-rendered with a browser — no --js.
    _patch_fetch_internals(monkeypatch)
    blocked = FetchResult(
        url="https://shop.test/p", html="<html>Access Denied</html>",
        status_code=403, blocked=True, blocked_reason="http 403",
    )
    rendered = FetchResult(
        url="https://shop.test/p",
        html="<html><body>" + ("real product " * 40) + "</body></html>",
        status_code=200, rendered_with_js=True,
    )
    monkeypatch.setattr(fetcher, "_fetch_static", lambda url: blocked)
    monkeypatch.setattr(fetcher, "_fetch_js", lambda url: rendered)
    result = fetcher.fetch("https://shop.test/p")
    assert result.rendered_with_js is True
    assert result.blocked is False


def test_auto_js_can_be_disabled(monkeypatch):
    _patch_fetch_internals(monkeypatch)
    monkeypatch.setattr(fetcher, "AUTO_JS", False)
    blocked = FetchResult(
        url="https://shop.test/p", html="x", status_code=403,
        blocked=True, blocked_reason="http 403",
    )
    monkeypatch.setattr(fetcher, "_fetch_static", lambda url: blocked)

    def _should_not_render(url):
        raise AssertionError("JS render must not run when CRAWLR_AUTO_JS is off")

    monkeypatch.setattr(fetcher, "_fetch_js", _should_not_render)
    assert fetcher.fetch("https://shop.test/p").blocked is True


def test_auto_js_missing_browser_is_graceful(monkeypatch):
    _patch_fetch_internals(monkeypatch)
    blocked = FetchResult(
        url="https://shop.test/p", html="x", status_code=403,
        blocked=True, blocked_reason="http 403",
    )
    monkeypatch.setattr(fetcher, "_fetch_static", lambda url: blocked)

    def _unavailable(url):
        raise RuntimeError("browser unavailable")

    monkeypatch.setattr(fetcher, "_fetch_js", _unavailable)
    # Falls back to the blocked static result instead of crashing.
    assert fetcher.fetch("https://shop.test/p").blocked is True


def test_is_missing_browser_detection():
    assert fetcher._is_missing_browser(Exception("Executable doesn't exist at /x")) is True
    assert fetcher._is_missing_browser(Exception("please run: playwright install")) is True
    assert fetcher._is_missing_browser(Exception("net::ERR_TIMED_OUT")) is False
