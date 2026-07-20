"""Tests for new alert channels, signed webhooks, throttling, and history."""

from __future__ import annotations

import hashlib
import hmac
import types

from crawlr import alerts, extractor, monitor, storage
from crawlr.fetcher import FetchResult
from crawlr.models import MonitoredSite
from crawlr.verticals import ecommerce
from tests import fixtures


def test_send_teams(monkeypatch):
    calls: list = []
    monkeypatch.setattr(alerts, "_post_json", lambda url, p: calls.append((url, p)))
    monkeypatch.setattr(alerts, "ALERTS", types.SimpleNamespace(teams_webhook_url="https://teams/x"))
    alerts._send_teams("Price drop", ["Widget -10%"])
    assert calls[0][0] == "https://teams/x"
    assert "Widget" in calls[0][1]["text"]


def test_send_ntfy(monkeypatch):
    calls: list = []
    monkeypatch.setattr(alerts, "_post_raw", lambda url, content, headers: calls.append((url, content, headers)))
    monkeypatch.setattr(alerts, "ALERTS", types.SimpleNamespace(ntfy_url="https://ntfy.sh/t"))
    alerts._send_ntfy("Back in stock", ["Widget available"])
    assert calls[0][0] == "https://ntfy.sh/t"
    assert "Widget" in calls[0][1]
    assert calls[0][2]["Title"].startswith("Back in stock")


def test_webhook_is_signed_when_secret_set(monkeypatch):
    raw: list = []
    monkeypatch.setattr(alerts, "_post_raw", lambda url, content, headers: raw.append((url, content, headers)))
    monkeypatch.setattr(
        alerts, "ALERTS",
        types.SimpleNamespace(webhook_url="https://hook/x", webhook_secret="s3cret"),
    )
    alerts._send_webhook({"a": 1})
    _url, content, headers = raw[0]
    expected = "sha256=" + hmac.new(b"s3cret", content.encode(), hashlib.sha256).hexdigest()
    assert headers["X-Crawlr-Signature"] == expected


def test_webhook_unsigned_uses_json(monkeypatch):
    calls: list = []
    monkeypatch.setattr(alerts, "_post_json", lambda url, p: calls.append((url, p)))
    monkeypatch.setattr(
        alerts, "ALERTS",
        types.SimpleNamespace(webhook_url="https://hook/x", webhook_secret=None),
    )
    alerts._send_webhook({"a": 1})
    assert calls[0] == ("https://hook/x", {"a": 1})


def test_throttle_dedup_via_storage():
    storage.record_alert_event(1, "item", "price", "dropped 10%", ["console"], "1|price|item")
    assert storage.was_recently_alerted("1|price|item", 60) is True
    assert storage.was_recently_alerted("unknown-key", 60) is False
    assert storage.was_recently_alerted("1|price|item", 0) is False  # throttle disabled


def _patch_fetch(monkeypatch, html, url):
    monkeypatch.setattr(
        extractor, "fetch", lambda u, force_js=False: FetchResult(url=url, html=html, status_code=200)
    )


def test_run_once_records_alert_history(monkeypatch):
    url = "https://shop.test/search"
    site_id = storage.add_site(
        MonitoredSite(url=url, schema_name="product_list", interval_minutes=1)
    )
    _patch_fetch(monkeypatch, fixtures.LISTING_V1, url)
    monitor.run_once(site_id, ecommerce.PRODUCT_LIST_SCHEMA, watch_fields=["price"])
    _patch_fetch(monkeypatch, fixtures.LISTING_V2, url)
    monitor.run_once(site_id, ecommerce.PRODUCT_LIST_SCHEMA, watch_fields=["price"])

    events = storage.recent_alert_events()
    assert any(e["field"] == "price" for e in events)
