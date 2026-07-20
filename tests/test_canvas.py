"""Tests for the cross-retailer product search / comparison ("canvas")."""

from __future__ import annotations

from crawlr import canvas
from crawlr.models import ExtractionResult


def _fake_scrape(mapping: dict[str, list[dict]]):
    def _scrape(url, schema, force_js=False):
        for key, records in mapping.items():
            if key in url:
                return ExtractionResult(url=url, schema_name="product_list", records=records)
        return ExtractionResult(url=url, schema_name="product_list", records=[])

    return _scrape


def test_canvas_ranks_cheapest_first(monkeypatch):
    mapping = {
        "amazon": [{"title": "Wooting 60HE Keyboard", "price": 180.0, "currency": "USD", "url": "/d/1"}],
        "ebay": [{"title": "Wooting 60HE", "price": 160.0, "currency": "USD", "url": "https://ebay.com/itm/2"}],
    }
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("Wooting 60HE", retailers=["amazon", "ebay"], base="USD")
    hits = report["hits"]
    assert [h.retailer for h in hits][0] == "eBay"     # cheaper wins the top spot
    assert hits[0].converted == 160.0


def test_canvas_converts_currencies(monkeypatch):
    mapping = {
        "amazon": [{"title": "Wooting 60HE", "price": 100.0, "currency": "USD", "url": "/a"}],
        "lazada": [{"title": "Wooting 60HE", "price": 100.0, "currency": "EUR", "url": "/l"}],
    }
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("Wooting 60HE", retailers=["amazon", "lazada"], base="USD")
    # 100 EUR converts to > 100 USD, so the USD listing is cheaper and ranks first.
    assert report["hits"][0].retailer == "Amazon"
    lazada = next(h for h in report["hits"] if h.retailer == "Lazada PH")
    assert lazada.converted is not None and lazada.converted > 100


def test_canvas_skips_nonmatch_and_blocked(monkeypatch):
    def _scrape(url, schema, force_js=False):
        if "amazon" in url:
            return ExtractionResult(
                url=url, schema_name="product_list",
                records=[{"title": "Totally Unrelated Gadget", "price": 5.0, "currency": "USD"}],
            )
        res = ExtractionResult(url=url, schema_name="product_list", records=[])
        res.blocked = True
        return res

    monkeypatch.setattr(canvas, "scrape", _scrape)
    report = canvas.search("Wooting 60HE", retailers=["amazon", "ebay"], base="USD")
    assert report["hits"] == []  # amazon has no title match; ebay was blocked


def test_canvas_resolves_relative_product_url(monkeypatch):
    mapping = {"amazon": [{"title": "Wooting 60HE", "price": 10.0, "currency": "USD", "url": "/dp/123"}]}
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("Wooting 60HE", retailers=["amazon"], base="USD")
    assert report["hits"][0].url.startswith("https://www.amazon.com/")



def test_canvas_infers_country_from_currency():
    # PHP -> Philippines local marketplaces; USD -> US.
    assert canvas.resolve_country(None, "PHP") == "ph"
    assert canvas.resolve_country(None, "USD") == "us"
    assert canvas.resolve_country("SG", "USD") == "sg"  # explicit wins
    ph = canvas.available_retailers("ph")
    assert "Lazada PH" in {r.name for r in ph.values()}
    assert "Shopee PH" in {r.name for r in ph.values()}


def test_canvas_ph_region_selected_for_php(monkeypatch):
    mapping = {"lazada.com.ph": [{"title": "MAD60 HE", "price": 3500.0, "currency": "PHP", "url": "/p/1"}]}
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("MAD60 HE", base="PHP")
    assert report["country"] == "ph"
    assert report["hits"] and report["hits"][0].retailer == "Lazada PH"
