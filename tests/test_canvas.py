"""Tests for the cross-retailer product search / comparison ("canvas")."""

from __future__ import annotations

import pytest

from crawlr import canvas
from crawlr.models import ExtractionResult


@pytest.fixture(autouse=True)
def _adapters_offline(monkeypatch):
    """Canvas API adapters must never hit the network in tests — force the HTML
    fallback (which tests mock via `scrape`). Individual tests can override."""

    def _offline(*args, **kwargs):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(canvas, "_api_get", _offline)


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



def test_detect_country_by_ip_is_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(canvas.config, "CANVAS_GEO", True)
    monkeypatch.setattr(canvas.config, "CANVAS_GEO_CACHE_PATH", tmp_path / "geo.json")
    monkeypatch.setattr(canvas.config, "CANVAS_GEO_CACHE_HOURS", 168.0)
    calls = {"n": 0}

    def fake_lookup():
        calls["n"] += 1
        return "ph"

    monkeypatch.setattr(canvas, "_lookup_ip_country", fake_lookup)
    assert canvas.detect_country_by_ip() == "ph"
    assert canvas.detect_country_by_ip() == "ph"  # served from disk cache
    assert calls["n"] == 1  # network hit only once


def test_detect_country_disabled_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(canvas.config, "CANVAS_GEO", False)
    monkeypatch.setattr(canvas.config, "CANVAS_GEO_CACHE_PATH", tmp_path / "geo.json")
    monkeypatch.setattr(canvas, "_lookup_ip_country", lambda: "ph")
    assert canvas.detect_country_by_ip() is None


def test_search_uses_ip_when_no_hints(monkeypatch):
    monkeypatch.setattr(canvas.config, "CANVAS_GEO", True)
    monkeypatch.setattr(canvas.config, "CANVAS_COUNTRY", None)
    monkeypatch.setattr(canvas, "detect_country_by_ip", lambda: "ph")
    mapping = {"lazada.com.ph": [{"title": "MAD60 HE", "price": 3500.0, "currency": "PHP", "url": "/p/1"}]}
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("MAD60 HE")  # no --to, no --country
    assert report["country"] == "ph"
    assert report["country_source"] == "ip"


def test_explicit_currency_overrides_ip(monkeypatch):
    monkeypatch.setattr(canvas.config, "CANVAS_GEO", True)
    monkeypatch.setattr(canvas.config, "CANVAS_COUNTRY", None)
    monkeypatch.setattr(canvas, "detect_country_by_ip", lambda: "ph")  # would be PH…
    monkeypatch.setattr(
        canvas, "scrape",
        _fake_scrape({"amazon": [{"title": "x", "price": 1.0, "currency": "USD", "url": "/a"}]}),
    )
    report = canvas.search("x", base="USD")  # …but explicit currency wins
    assert report["country"] == "us"
    assert report["country_source"] == "currency"



def test_canvas_filters_junk_results(monkeypatch):
    mapping = {
        "amazon": [
            {"title": "Results for mad60 he", "price": 60.0, "currency": "USD", "url": "/s"},
            {"title": "MAD60 HE Keyboard", "price": 100.0, "currency": "USD", "url": "/p/1"},
        ]
    }
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("mad60 he", retailers=["amazon"], base="USD")
    titles = [h.title for h in report["hits"]]
    assert "MAD60 HE Keyboard" in titles
    assert all("Results for" not in t for t in titles)  # page chrome rejected


def test_canvas_returns_multiple_listings_per_store(monkeypatch):
    mapping = {
        "amazon": [
            {"title": "MAD60 HE Black", "price": 100.0, "currency": "USD", "url": "/p/1"},
            {"title": "MAD60 HE White", "price": 110.0, "currency": "USD", "url": "/p/2"},
            {"title": "MAD60 HE Blue", "price": 120.0, "currency": "USD", "url": "/p/3"},
        ]
    }
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("mad60 he", retailers=["amazon"], base="USD", per_store=2)
    assert len(report["hits"]) == 2  # capped per store


def test_canvas_reports_blocked_retailers(monkeypatch):
    def _scrape(url, schema, force_js=False):
        res = ExtractionResult(url=url, schema_name="product_list", records=[])
        res.blocked = True
        return res

    monkeypatch.setattr(canvas, "scrape", _scrape)
    report = canvas.search("x", retailers=["amazon", "ebay"], base="USD")
    assert set(report["blocked"]) == {"Amazon", "eBay"}
    assert report["hits"] == []


def test_canvas_prices_in_local_currency_when_region_detected(monkeypatch):
    monkeypatch.setattr(canvas.config, "CANVAS_GEO", True)
    monkeypatch.setattr(canvas.config, "CANVAS_COUNTRY", None)
    monkeypatch.setattr(canvas, "detect_country_by_ip", lambda: "ph")
    monkeypatch.setattr(canvas, "scrape", _fake_scrape({}))
    report = canvas.search("mad60 he")  # no --to, PH detected from IP
    assert report["country"] == "ph"
    assert report["base"] == "PHP"          # priced in the region's currency
    assert report["currency_source"] == "country"



def test_canvas_rejects_search_page_echo(monkeypatch):
    # A quoted echo of the query that only links to the search page (a #fragment)
    # is page chrome, not a product listing.
    mapping = {
        "amazon": [
            {"title": '"logitech mouse"', "price": 179.99, "currency": "USD", "url": "#main-content"}
        ]
    }
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("logitech mouse", retailers=["amazon"], base="USD")
    assert report["hits"] == []



def test_lazada_adapter_parses_json(monkeypatch):
    payload = {
        "mods": {
            "listItems": [
                {"name": "MAD60 HE Keyboard", "price": "3499.00",
                 "productUrl": "//www.lazada.com.ph/products/x.html"},
                {"name": "Keycaps", "priceShow": "₱1,299", "productUrl": "https://www.lazada.com.ph/y.html"},
            ]
        }
    }
    monkeypatch.setattr(canvas, "_api_get", lambda url, headers: payload)
    recs = canvas._lazada_adapter("www.lazada.com.ph", "PHP")("mad60 he")
    assert recs[0]["title"] == "MAD60 HE Keyboard"
    assert recs[0]["price"] == 3499.0
    assert recs[0]["currency"] == "PHP"
    assert recs[0]["url"].startswith("https://")
    assert recs[1]["price"] == 1299.0  # parsed from "₱1,299"


def test_shopee_adapter_parses_json(monkeypatch):
    payload = {"items": [{"item_basic": {"name": "MAD60 HE", "price": 349900000, "shopid": 1, "itemid": 2}}]}
    monkeypatch.setattr(canvas, "_api_get", lambda url, headers: payload)
    recs = canvas._shopee_adapter("shopee.ph", "PHP")("mad60 he")
    assert recs[0]["title"] == "MAD60 HE"
    assert recs[0]["price"] == 3499.0                       # micro-units / 100000
    assert recs[0]["url"] == "https://shopee.ph/product/1/2"


def test_canvas_uses_store_api_when_available(monkeypatch):
    payload = {
        "mods": {"listItems": [
            {"name": "MAD60 HE Wired Keyboard", "price": "3499",
             "productUrl": "https://www.lazada.com.ph/products/x.html"}
        ]}
    }
    monkeypatch.setattr(canvas, "_api_get", lambda url, headers: payload)
    monkeypatch.setattr(canvas, "scrape", _fake_scrape({}))  # HTML would find nothing
    report = canvas.search("mad60 he", retailers=["lazada"], base="PHP", country="ph")
    assert any(h.retailer == "Lazada PH" and h.price == 3499.0 for h in report["hits"])


def test_canvas_api_failure_falls_back_to_html(monkeypatch):
    # Adapter raises (offline fixture); HTML fallback (mocked) still yields a hit.
    mapping = {"lazada.com.ph": [
        {"title": "MAD60 HE Keyboard", "price": 3499.0, "currency": "PHP", "url": "/p/1"}
    ]}
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("mad60 he", retailers=["lazada"], base="PHP", country="ph")
    assert any(h.retailer == "Lazada PH" for h in report["hits"])


def test_canvas_filters_view_all_ads(monkeypatch):
    mapping = {"amazon": [
        {"title": "mad60+he - View all mad60+he ads in Carousell Philippines",
         "price": 60.0, "currency": "PHP", "url": "/s"},
        {"title": "MAD60 HE Keyboard", "price": 3499.0, "currency": "PHP", "url": "/p/1"},
    ]}
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("mad60 he", retailers=["amazon"], base="PHP")
    titles = [h.title for h in report["hits"]]
    assert "MAD60 HE Keyboard" in titles
    assert all("View all" not in t for t in titles)  # heading rejected



def test_expand_query_variants():
    variants = canvas._expand_query("RTX 5070")
    assert variants[0] == "RTX 5070"
    joined = " | ".join(variants).lower()
    assert "rtx5070" in joined   # no-space form
    assert "5070" in joined      # brand dropped
    assert "rtx" in joined       # model dropped


def test_canvas_auto_expands_when_results_low(monkeypatch):
    mapping = {"amazon": [{"title": "MAD60 HE Keyboard", "price": 100.0, "currency": "USD", "url": "/p/1"}]}
    monkeypatch.setattr(canvas, "scrape", _fake_scrape(mapping))
    report = canvas.search("mad60 he", retailers=["amazon"], base="USD")
    assert len(report["queries_tried"]) > 1          # expanded because < min results
    report2 = canvas.search("mad60 he", retailers=["amazon"], base="USD", expand=False)
    assert report2["queries_tried"] == ["mad60 he"]  # expansion off


def test_price_stats():
    def hit(p):
        return canvas.CanvasHit("S", "x", p, "USD", "http://s/" + str(p), p, 0.9)
    stats = canvas._price_stats([hit(100.0), hit(200.0), hit(300.0)])
    assert stats["min"] == 100.0 and stats["max"] == 300.0
    assert stats["avg"] == 200.0 and stats["median"] == 200.0
    assert stats["savings"] == 200.0 and stats["count"] == 3


def test_sort_hits_by_rating_and_price():
    a = canvas.CanvasHit("A", "x", 1.0, "USD", "u1", 1.0, 0.9, rating=3.0)
    b = canvas.CanvasHit("B", "y", 2.0, "USD", "u2", 2.0, 0.9, rating=4.8)
    assert canvas._sort_hits([a, b], "rating")[0].rating == 4.8
    assert canvas._sort_hits([a, b], "price")[0].converted == 1.0


def test_lazada_adapter_rich_fields(monkeypatch):
    payload = {"mods": {"listItems": [{
        "name": "MAD60 HE", "price": "3499", "originalPrice": "3999", "discount": "-13%",
        "ratingScore": "4.8", "review": "120", "itemSoldCntShow": "1.2k sold",
        "productUrl": "https://www.lazada.com.ph/p/x.html", "image": "//img.lazada/x.jpg",
        "sellerName": "KB Store", "mallType": "1",
    }]}}
    monkeypatch.setattr(canvas, "_api_get", lambda url, headers, timeout=None: payload)
    recs = canvas._lazada_adapter("www.lazada.com.ph", "PHP")("mad60 he")
    r = recs[0]
    assert r["rating"] == 4.8 and r["reviews"] == 120 and r["sold"] == 1200
    assert r["original_price"] == 3999.0 and r["discount_pct"] == 13
    assert r["official"] is True and r["image"].startswith("https://")


def test_shopify_adapter_parses(monkeypatch):
    payload = {"resources": {"results": {"products": [
        {"title": "MAD60 HE", "price": "3,499.00", "url": "/products/mad60",
         "image": "https://img", "vendor": "KB", "available": True}
    ]}}}
    monkeypatch.setattr(canvas, "_api_get", lambda url, headers, timeout=None: payload)
    recs = canvas._shopify_adapter("shop.example", "PHP")("mad60")
    assert recs[0]["title"] == "MAD60 HE" and recs[0]["price"] == 3499.0
    assert recs[0]["url"] == "https://shop.example/products/mad60"


def test_woocommerce_adapter_parses(monkeypatch):
    payload = [{
        "name": "MAD60 HE",
        "prices": {"price": "349900", "regular_price": "399900",
                   "currency_minor_unit": 2, "currency_code": "PHP"},
        "permalink": "https://shop.example/p/mad60",
        "images": [{"src": "https://img"}], "is_in_stock": True,
    }]
    monkeypatch.setattr(canvas, "_api_get", lambda url, headers, timeout=None: payload)
    recs = canvas._woocommerce_adapter("shop.example", "PHP")("mad60")
    assert recs[0]["price"] == 3499.0 and recs[0]["original_price"] == 3999.0
    assert recs[0]["in_stock"] is True


def test_canvas_hit_carries_rich_fields(monkeypatch):
    payload = {"mods": {"listItems": [{
        "name": "MAD60 HE Keyboard", "price": "3499", "ratingScore": "4.8",
        "review": "120", "productUrl": "https://www.lazada.com.ph/p/x.html",
    }]}}
    monkeypatch.setattr(canvas, "_api_get", lambda url, headers, timeout=None: payload)
    report = canvas.search("mad60 he", retailers=["lazada"], base="PHP", country="ph", expand=False)
    hit = next(h for h in report["hits"] if h.retailer == "Lazada PH")
    assert hit.rating == 4.8 and hit.reviews == 120
    assert report["stats"]["count"] >= 1
