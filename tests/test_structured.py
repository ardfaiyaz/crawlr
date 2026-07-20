"""Tests for the structured-data layer (JSON-LD / microdata / OpenGraph)."""

from __future__ import annotations

from crawlr import structured

JSONLD = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Widget",
 "image":"https://x/img.jpg",
 "aggregateRating":{"@type":"AggregateRating","ratingValue":"4.5"},
 "offers":{"@type":"Offer","price":"29.99","priceCurrency":"USD",
           "availability":"https://schema.org/InStock"}}
</script></head><body></body></html>
"""

MICRODATA = """
<div itemtype="http://schema.org/Product">
  <span itemprop="name">Gadget</span>
  <span itemprop="price" content="15.50">$15.50</span>
  <link itemprop="availability" href="https://schema.org/OutOfStock">
</div>
"""

OPENGRAPH = """
<html><head>
  <meta property="og:title" content="OG Item">
  <meta property="product:price:amount" content="99.00">
  <meta property="product:price:currency" content="EUR">
</head><body></body></html>
"""


def test_jsonld():
    d = structured.extract_structured(JSONLD)
    assert d["title"] == "Widget"
    assert d["price"] == 29.99
    assert d["currency"] == "USD"
    assert d["availability"] == "In stock"
    assert d["rating"] == 4.5
    assert d["image"] == "https://x/img.jpg"


def test_microdata():
    d = structured.extract_structured(MICRODATA)
    assert d["title"] == "Gadget"
    assert d["price"] == 15.5
    assert d["availability"] == "Out of stock"


def test_opengraph():
    d = structured.extract_structured(OPENGRAPH)
    assert d["title"] == "OG Item"
    assert d["price"] == 99.0
    assert d["currency"] == "EUR"


def test_empty_page():
    assert structured.extract_structured("<html><body><p>hi</p></body></html>") == {}
