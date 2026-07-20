"""Tests for raw HTML snapshot archival + offline re-extraction."""

from __future__ import annotations

from crawlr import archive, extractor
from crawlr.verticals import ecommerce


def test_save_and_load_roundtrip():
    path = archive.save("https://x.test/p", "product", "<html>hi there</html>")
    assert path is not None and path.exists()
    assert archive.load_latest("https://x.test/p", "product") == "<html>hi there</html>"


def test_missing_snapshot_returns_none():
    assert archive.load_latest("https://nope.test/p", "product") is None


def test_empty_html_not_saved():
    assert archive.save("https://x.test/p", "product", "") is None


def test_reextract_from_html_offline():
    html = """
    <div itemtype="http://schema.org/Product">
      <h1 class="product-title">Archived Item</h1>
      <span class="price">12.50</span>
    </div>
    """
    result = extractor.reextract("https://x.test/p", ecommerce.PRODUCT_SCHEMA, html)
    assert result.records and result.records[0]["title"] == "Archived Item"
    assert result.records[0]["price"] == 12.5
