"""Tests for enriched structured-data extraction, discounts, and provenance."""

from __future__ import annotations

from crawlr import extractor, normalize, structured
from crawlr.fetcher import FetchResult
from crawlr.verticals import ecommerce

JSONLD_RICH = """
<html><head><script type="application/ld+json">
{"@type":"Product","name":"Widget Pro","brand":{"@type":"Brand","name":"Acme"},
 "sku":"SKU123","mpn":"MPN9","gtin13":"0123456789012",
 "aggregateRating":{"ratingValue":"4.2","reviewCount":"87"},
 "offers":{"@type":"AggregateOffer","lowPrice":"89.99","highPrice":"129.99",
           "priceCurrency":"USD","availability":"https://schema.org/InStock"}}
</script></head><body>
<div itemtype="http://schema.org/Product">
  <h1 class="product-title">Widget Pro</h1>
  <span class="price">89.99</span>
  <div class="availability">In stock</div>
</div></body></html>
"""


def test_structured_extracts_rich_fields():
    d = structured.extract_structured(JSONLD_RICH)
    assert d["brand"] == "Acme"
    assert d["sku"] == "SKU123"
    assert d["mpn"] == "MPN9"
    assert d["gtin"] == "0123456789012"
    assert d["rating"] == 4.2
    assert d["review_count"] == 87.0
    assert d["price"] == 89.99          # AggregateOffer lowPrice
    assert d["original_price"] == 129.99  # AggregateOffer highPrice
    assert d["currency"] == "USD"
    assert d["availability"] == "In stock"


def test_availability_enum_variants():
    def avail(value: str) -> str | None:
        html = (
            '<script type="application/ld+json">{"@type":"Product","name":"X",'
            f'"offers":{{"price":"1","availability":"{value}"}}}}</script>'
        )
        return structured.extract_structured(html)["availability"]

    assert avail("https://schema.org/PreOrder") == "Pre-order"
    assert avail("https://schema.org/BackOrder") == "Backorder"
    assert avail("https://schema.org/Discontinued") == "Discontinued"


def test_compute_discount():
    assert normalize.compute_discount(100, 80) == 20.0
    assert normalize.compute_discount(100, 100) is None   # no real discount
    assert normalize.compute_discount(None, 5) is None
    assert normalize.compute_discount("50", "40") == 20.0


def _patch(monkeypatch, html: str):
    monkeypatch.setattr(
        extractor, "fetch",
        lambda u, force_js=False: FetchResult(url=u, html=html, status_code=200),
    )


def test_scrape_merges_extras_and_labels_quality(monkeypatch):
    _patch(monkeypatch, JSONLD_RICH)
    result = extractor.scrape("https://shop.test/p", ecommerce.PRODUCT_SCHEMA)
    rec = result.records[0]

    # Rich structured-only fields are merged into the record.
    assert rec["brand"] == "Acme"
    assert rec["sku"] == "SKU123"
    assert rec["currency"] == "USD"
    assert rec["original_price"] == 129.99
    assert rec["discount_pct"] > 0            # computed from original vs current

    # Provenance + quality labelling.
    assert result.field_source["price"] == "both"
    assert result.quality == "verified"       # structured-backed, high confidence
