"""Tests for anti-bot / block detection."""

from __future__ import annotations

from crawlr import fetcher


def test_blocking_status_codes():
    assert fetcher.detect_block(403, "") == "http 403"
    assert fetcher.detect_block(429, "") == "http 429"
    assert fetcher.detect_block(503, "") == "http 503"


def test_ok_response_not_blocked():
    assert fetcher.detect_block(200, "<html><body>hello</body></html>") is None


def test_anti_bot_markers():
    assert fetcher.detect_block(200, "<html>Just a moment... Cloudflare</html>") == "anti-bot challenge"
    assert fetcher.detect_block(200, "<div>Please complete the CAPTCHA</div>") == "anti-bot challenge"
