"""End-to-end offline tests for the extraction engine and monitoring layer.

These run without network or an LLM key: `fetch` is monkeypatched to return
local fixtures, and selector generation uses the heuristic path.
"""

from __future__ import annotations

from crawlr import extractor, monitor, storage
from crawlr.fetcher import FetchResult
from crawlr.models import ExtractionSchema, FieldSpec, FieldType
from crawlr.verticals import ecommerce
from tests import fixtures


def _patch_fetch(monkeypatch, html: str, url: str = "https://shop.test/search"):
    monkeypatch.setattr(
        extractor,
        "fetch",
        lambda u, force_js=False: FetchResult(url=url, html=html, status_code=200),
    )


def test_extract_product_list_heuristic(monkeypatch):
    _patch_fetch(monkeypatch, fixtures.LISTING_V1)
    result = extractor.scrape("https://shop.test/search", ecommerce.PRODUCT_LIST_SCHEMA)

    assert result.count == 2
    titles = {r["title"] for r in result.records}
    assert titles == {"Wireless Mouse", "Mechanical Keyboard"}
    prices = sorted(r["price"] for r in result.records)
    assert prices == [24.99, 79.0]
    # Prices coerced to float, urls extracted from href.
    assert all(r["url"].startswith("/p/") for r in result.records)


def test_extract_single_product(monkeypatch):
    _patch_fetch(monkeypatch, fixtures.PRODUCT_PAGE, url="https://shop.test/p/monitor")
    result = extractor.scrape("https://shop.test/p/monitor", ecommerce.PRODUCT_SCHEMA)

    assert result.count == 1
    rec = result.records[0]
    assert rec["title"] == '4K Monitor 27"'
    assert rec["price"] == 299.50
    assert rec["availability"] == "In Stock"
    assert rec["rating"] == 4.6


def test_self_heals_on_layout_change(monkeypatch):
    """Cache selectors on v1, then serve redesigned v2 and confirm self-heal."""
    url = "https://shop.test/search"

    _patch_fetch(monkeypatch, fixtures.LISTING_V1, url=url)
    first = extractor.scrape(url, ecommerce.PRODUCT_LIST_SCHEMA)
    assert first.count == 2
    assert first.healed is False  # first run just generates + caches

    # Now the site is redesigned: different container + class names.
    _patch_fetch(monkeypatch, fixtures.LISTING_V2, url=url)
    second = extractor.scrape(url, ecommerce.PRODUCT_LIST_SCHEMA)

    assert second.healed is True, "engine should detect breakage and regenerate"
    assert second.count == 2
    titles = {r["title"] for r in second.records}
    assert titles == {"Wireless Mouse", "Mechanical Keyboard"}


def test_change_detection_price_drop(monkeypatch):
    """Two monitored runs should log the mouse price drop 24.99 -> 19.99."""
    url = "https://shop.test/search"
    site_id = storage.add_site(
        __import__("crawlr.models", fromlist=["MonitoredSite"]).MonitoredSite(
            url=url, schema_name="product_list", interval_minutes=1
        )
    )

    _patch_fetch(monkeypatch, fixtures.LISTING_V1, url=url)
    monitor.run_once(site_id, ecommerce.PRODUCT_LIST_SCHEMA, watch_fields=["price"])

    _patch_fetch(monkeypatch, fixtures.LISTING_V2, url=url)
    _, changes = monitor.run_once(site_id, ecommerce.PRODUCT_LIST_SCHEMA, watch_fields=["price"])

    price_changes = [c for c in changes if c.field == "price"]
    assert len(price_changes) == 1
    change = price_changes[0]
    assert change.old_value == "24.99"
    assert change.new_value == "19.99"

    stored = storage.recent_changes(site_id)
    assert any(c["field"] == "price" and c["new_value"] == "19.99" for c in stored)


def test_custom_schema_general_purpose(monkeypatch):
    """The engine is general-purpose: a custom schema works too."""
    html = """<body><div class="job"><h2 class="role">Engineer</h2>
              <span class="salary">150000</span></div>
              <div class="job"><h2 class="role">Designer</h2>
              <span class="salary">120000</span></div></body>"""
    _patch_fetch(monkeypatch, html, url="https://jobs.test/list")

    schema = ExtractionSchema(
        name="jobs",
        item_selector=".job",
        fields=[
            FieldSpec(name="title", description="job role title", selector=".role"),
            FieldSpec(
                name="salary",
                description="annual salary",
                type=FieldType.NUMBER,
                selector=".salary",
            ),
        ],
    )
    result = extractor.scrape("https://jobs.test/list", schema)
    assert result.count == 2
    assert {r["title"] for r in result.records} == {"Engineer", "Designer"}
    assert sorted(r["salary"] for r in result.records) == [120000.0, 150000.0]
