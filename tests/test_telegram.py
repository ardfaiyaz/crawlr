"""Tests for the Telegram bot front-end (offline: canvas + storage mocked)."""

from __future__ import annotations

from crawlr import canvas, telegram
from crawlr.canvas import CanvasHit


def _report(hits, base="PHP"):
    return {
        "hits": hits, "base": base, "shops": len({h.retailer for h in hits}),
        "stats": {"min": 5295, "max": 7795, "avg": 6500, "median": 6000,
                  "savings": 2500, "count": len(hits)},
        "blocked": [], "strategies_used": ["store_api"],
    }


def _hit(retailer, price, url, **kw):
    return CanvasHit(
        retailer=retailer, title=kw.get("title", "Logitech G Pro X Superlight"),
        price=price, currency="PHP", url=url, converted=price, score=0.95,
        discount_pct=kw.get("discount_pct"), rating=kw.get("rating"),
        all_time_low=kw.get("all_time_low", False), hist_count=kw.get("hist_count", 0),
        hist_avg=kw.get("hist_avg"),
    )


def test_help_message():
    assert "Crawlr price bot" in telegram.handle_text("/help")
    assert "Crawlr price bot" in telegram.handle_text("")


def test_parse_watch():
    assert telegram._parse_watch("logitech g pro x 5000") == ("logitech g pro x", 5000.0)
    assert telegram._parse_watch("logitech mouse") == ("logitech mouse", None)
    assert telegram._parse_watch("razer viper ₱3,200") == ("razer viper", 3200.0)


def test_format_results_flags_all_time_low():
    hits = [_hit("DynaQuest PC", 5295.0, "https://dq/p", all_time_low=True, hist_count=5, hist_avg=6000.0)]
    out = telegram.format_results("logitech g pro x superlight", _report(hits))
    assert "Best:" in out and "all-time low" in out
    assert "DynaQuest PC" in out and "PHP" in out


def test_format_results_empty():
    out = telegram.format_results("nope", {"hits": [], "base": "PHP", "blocked": ["Amazon"]})
    assert "No results" in out


def test_handle_search(monkeypatch):
    hits = [_hit("DataBlitz", 7795.0, "https://db/p"), _hit("GameXtreme", 5295.0, "https://gx/p")]
    monkeypatch.setattr(canvas, "search", lambda q, **kw: _report(hits))
    out = telegram.handle_text("logitech g pro x superlight")
    assert "listing(s) across" in out
    assert "GameXtreme" in out and "DataBlitz" in out


def test_handle_watch_registers(monkeypatch):
    from crawlr import storage

    hits = [_hit("DataBlitz", 7795.0, "https://www.datablitz.com.ph/products/gpx?a=1")]
    monkeypatch.setattr(canvas, "search", lambda q, **kw: _report(hits))
    reply = telegram.handle_text("/watch logitech g pro x superlight 5000")
    assert "Now watching" in reply
    assert any("datablitz.com.ph" in (row.get("url") or "") for row in storage.watchlist())
