"""Tests for the change digest (periodic rollup of all changes)."""

from __future__ import annotations

from crawlr import alerts, digest, storage
from crawlr.models import MonitoredSite, PriceChange


def _seed():
    sid = storage.add_site(MonitoredSite(url="https://s.test/p", schema_name="product"))
    storage.record_changes(
        sid,
        [
            PriceChange(product_url="Widget", field="price", old_value="10", new_value="8"),
            PriceChange(
                product_url="Widget", field="availability",
                old_value="Out of stock", new_value="In stock",
            ),
        ],
    )
    return sid


def test_build_groups_changes_by_site():
    _seed()
    report = digest.build(hours=24)
    assert report["total"] == 2
    assert any("s.test" in url for url in report["sites"])


def test_build_empty_window():
    assert digest.build(hours=24)["total"] == 0


def test_summary_highlights_price_and_stock():
    _seed()
    lines = "\n".join(digest.summarize_lines(digest.build(hours=24)))
    assert "price down" in lines
    assert "back in stock" in lines


def test_send_dispatches_to_sinks(monkeypatch):
    _seed()
    captured: dict = {}
    monkeypatch.setattr(
        alerts, "send_message",
        lambda subject, lines, payload_extra=None: captured.update(subject=subject, lines=lines),
    )
    report = digest.send(hours=24)
    assert report["total"] == 2
    assert "Crawlr digest" in captured["subject"]
    assert captured["lines"]


def test_send_no_changes_is_noop(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(alerts, "send_message", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    report = digest.send(hours=24)
    assert report["total"] == 0
    assert called["n"] == 0
