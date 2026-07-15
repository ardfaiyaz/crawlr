"""Tests for the consensus layer: structured data vs selectors + confidence."""

from __future__ import annotations

from crawlr import extractor
from crawlr.fetcher import FetchResult
from crawlr.verticals import ecommerce

# Selector price (219) disagrees with JSON-LD price (199) -> structured wins.
DISAGREE = """
<html><head>
<script type="application/ld+json">
{"@type":"Product","name":"Headphones",
 "offers":{"price":"199.00","priceCurrency":"USD","availability":"https://schema.org/InStock"}}
</script></head><body>
<div itemtype="http://schema.org/Product">
  <h1 class="product-title">Headphones</h1>
  <span class="price">219.00</span>
  <div class="availability">In stock</div>
</div>
</body></html>
"""

# Selector has no price; JSON-LD fills it.
FILL = """
<html><head>
<script type="application/ld+json">
{"@type":"Product","name":"Mouse","offers":{"price":"49.99","priceCurrency":"USD"}}
</script></head><body>
<div itemtype="http://schema.org/Product"><h1 class="product-title">Mouse</h1></div>
</body></html>
"""


def _patch(monkeypatch, html):
    monkeypatch.setattr(
        extractor, "fetch",
        lambda u, force_js=False: FetchResult(url=u, html=html, status_code=200),
    )


def test_structured_wins_on_disagreement(monkeypatch):
    _patch(monkeypatch, DISAGREE)
    result = extractor.scrape("https://shop.test/p", ecommerce.PRODUCT_SCHEMA)
    rec = result.records[0]
    assert rec["price"] == 199.0  # structured value preferred over selector's 219
    assert result.field_confidence["price"] == 0.5  # disagreement
    assert result.field_confidence["title"] == 1.0  # agreement
    assert any("disagreed" in w for w in result.warnings)


def test_structured_fills_missing_field(monkeypatch):
    _patch(monkeypatch, FILL)
    result = extractor.scrape("https://shop.test/p2", ecommerce.PRODUCT_SCHEMA)
    rec = result.records[0]
    assert rec["price"] == 49.99  # filled from JSON-LD
    assert result.field_confidence["price"] == 0.7  # only structured present
