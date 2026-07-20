"""Tests for zero-config schema auto-detection."""

from __future__ import annotations

from crawlr import detect


def _jsonld(type_name: str) -> str:
    return (
        f'<html><head><script type="application/ld+json">'
        f'{{"@type": "{type_name}", "name": "X"}}</script></head><body></body></html>'
    )


def test_detects_product_from_jsonld():
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"Widget","offers":{"price":"9.99"}}</script>'
    )
    assert detect.detect_from_html(html, "https://shop.test/p/1") == "product"


def test_detects_jobposting():
    assert detect.detect_from_html(_jsonld("JobPosting"), "https://x.test/x") == "jobs"


def test_detects_real_estate():
    assert detect.detect_from_html(_jsonld("RealEstateListing"), "https://x.test/x") == "real_estate"


def test_detects_news_article():
    assert detect.detect_from_html(_jsonld("NewsArticle"), "https://x.test/x") == "news"


def test_detects_listing_from_repeating_cards():
    html = "<body>" + "".join("<div class='product'>x</div>" for _ in range(4)) + "</body>"
    assert detect.detect_from_html(html, "https://shop.test/search") == "product_list"


def test_product_with_many_cards_is_listing():
    cards = "".join("<div class='product'>x</div>" for _ in range(3))
    html = (
        '<script type="application/ld+json">{"@type":"Product","name":"X"}</script>'
        f"<body>{cards}</body>"
    )
    assert detect.detect_from_html(html, "https://shop.test/c") == "product_list"


def test_url_keyword_fallback_when_no_signals():
    assert detect.detect_from_html("<html></html>", "https://x.test/jobs/123") == "jobs"


def test_defaults_to_product():
    assert detect.detect_from_html("<html><body>hi</body></html>", "https://x.test/") == "product"


def test_detect_schema_uses_given_html_without_fetching():
    # html supplied -> no network call.
    assert detect.detect_schema("https://x.test/x", html=_jsonld("JobPosting")) == "jobs"
