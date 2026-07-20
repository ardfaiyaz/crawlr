"""Page-level fallbacks fill title/price/etc. when structured + selectors miss."""

from __future__ import annotations

from selectolax.parser import HTMLParser

from crawlr import extractor, fallback
from crawlr.fetcher import FetchResult
from crawlr.verticals import ecommerce


def test_fallback_title_prefers_og_then_h1_then_doctitle():
    assert fallback.fallback_title(
        HTMLParser('<meta property="og:title" content="OG Name">')
    ) == "OG Name"
    assert fallback.fallback_title(HTMLParser("<h1>  Heading   Name </h1>")) == "Heading Name"
    assert fallback.fallback_title(
        HTMLParser("<title>Cool Product | My Shop</title>")
    ) == "Cool Product"


def test_fallback_price_from_priced_element():
    amount, cur = fallback.fallback_price(HTMLParser('<span class="price_color">£51.77</span>'))
    assert amount == 51.77
    assert cur == "GBP"


def test_fallback_price_from_data_attribute():
    amount, _ = fallback.fallback_price(HTMLParser('<div data-price-amount="129.00">x</div>'))
    assert amount == 129.0


def test_fallback_price_scans_text_any_currency_order():
    a1, c1 = fallback.fallback_price(HTMLParser("<body><p>Only $19.99 today</p></body>"))
    assert a1 == 19.99 and c1 == "USD"
    a2, c2 = fallback.fallback_price(HTMLParser("<body><p>Price: PHP 500.00</p></body>"))
    assert a2 == 500.0 and c2 == "PHP"


def test_fallback_availability_and_image():
    assert fallback.fallback_availability(HTMLParser("<body>In stock — add to cart</body>")) == "In stock"
    assert fallback.fallback_availability(HTMLParser("<body>Sold out</body>")) == "Out of stock"
    assert fallback.fallback_image(
        HTMLParser('<meta property="og:image" content="https://x/i.jpg">')
    ) == "https://x/i.jpg"


def _patch(monkeypatch, html: str):
    monkeypatch.setattr(
        extractor, "fetch",
        lambda u, force_js=False: FetchResult(url=u, html=html, status_code=200),
    )


def test_scrape_fills_price_via_fallback_when_selectors_miss(monkeypatch):
    # og:title gives the name; price hides in a non-standard element -> fallback.
    html = """
    <html><head><meta property="og:title" content="Mystery Widget"></head>
    <body><div class="weird-layout"><span class="totally-custom">$42.50</span>
    <p>In stock</p></div></body></html>
    """
    _patch(monkeypatch, html)
    rec = extractor.scrape("https://x.test/p", ecommerce.PRODUCT_SCHEMA).records[0]
    assert rec["title"] == "Mystery Widget"
    assert rec["price"] == 42.50


def test_scrape_fills_from_bare_html_no_structured_data(monkeypatch):
    # No schema.org, no og tags, oddball classes: title from <h1>, price from text.
    html = (
        "<html><head><title>Bare Product - Shop</title></head>"
        "<body><h1>Bare Product</h1><div class='xyz'>Now PHP 500.00</div>"
        "<p>Add to cart</p></body></html>"
    )
    _patch(monkeypatch, html)
    rec = extractor.scrape("https://x.test/p2", ecommerce.PRODUCT_SCHEMA).records[0]
    assert rec["title"] == "Bare Product"
    assert rec["price"] == 500.0
    assert rec["currency"] == "PHP"
