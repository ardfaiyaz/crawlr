"""Tests for the multi-strategy product extraction engine."""

from __future__ import annotations

from crawlr import strategies


def test_nextdata_products():
    html = (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"products":['
        '{"name":"MAD60 HE Keyboard","price":3499,"currency":"PHP","url":"/p/mad60",'
        '"sku":"KB1","image":"/img/1.jpg","ratingValue":4.7,"reviewCount":88},'
        '{"name":"Wooting 60HE","sellingPrice":"9999","productUrl":"/p/wooting",'
        '"gtin":"1234567890123"}]}}}</script></body></html>'
    )
    prods, used = strategies.extract_products(html, "https://shop.test/search?q=x")
    assert "embedded_state" in used
    by_title = {p["title"]: p for p in prods}
    assert by_title["MAD60 HE Keyboard"]["price"] == 3499.0
    assert by_title["MAD60 HE Keyboard"]["url"] == "https://shop.test/p/mad60"
    assert by_title["MAD60 HE Keyboard"]["sku"] == "KB1"
    assert by_title["Wooting 60HE"]["price"] == 9999.0
    assert by_title["Wooting 60HE"]["gtin"] == "1234567890123"


def test_redux_state_products():
    html = (
        "<html><body><script>window.__INITIAL_STATE__ = "
        '{"catalog":{"items":[{"title":"Razer Viper V3","finalPrice":3200,'
        '"link":"/razer-viper","productId":"RZ1"}]}};</script></body></html>'
    )
    prods, used = strategies.extract_products(html, "https://shop.test/")
    assert "embedded_state" in used
    assert prods[0]["title"] == "Razer Viper V3"
    assert prods[0]["price"] == 3200.0
    assert prods[0]["url"] == "https://shop.test/razer-viper"


def test_inline_json_products():
    html = (
        "<html><body><script>var data = "
        '{"results":[{"name":"Logitech G Pro","price":"5,495.00","href":"/logi","id":"L1"}]}'
        "</script></body></html>"
    )
    prods, used = strategies.extract_products(html, "https://shop.test/")
    assert "inline_json" in used
    assert prods[0]["title"] == "Logitech G Pro"
    assert prods[0]["price"] == 5495.0


def test_jsonld_products_via_engine():
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type":"Product","name":"MAD60 HE","offers":{"price":"3499",'
        '"priceCurrency":"PHP"},"url":"https://shop.test/p/1"}</script></head><body></body></html>'
    )
    prods, used = strategies.extract_products(html, "https://shop.test/")
    assert "jsonld" in used
    assert prods[0]["title"] == "MAD60 HE" and prods[0]["price"] == 3499.0


def test_empty_and_junk_html():
    assert strategies.extract_products("", "https://x/") == ([], [])
    # Config-like JSON with a stray "price" but no product identity -> nothing.
    html = '<html><body><script>window.__CFG__ = {"shipping":{"price":50}}</script></body></html>'
    prods, _ = strategies.extract_products(html, "https://x/")
    assert prods == []


def test_balanced_json_helper():
    assert strategies._balanced_json('{"a":{"b":1}} tail', 0) == '{"a":{"b":1}}'
    assert strategies._balanced_json('[1,[2,3]] tail', 0) == "[1,[2,3]]"
