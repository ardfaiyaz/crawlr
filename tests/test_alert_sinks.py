"""Tests for the Discord and Telegram alert sinks."""

from __future__ import annotations

import types

from crawlr import alerts


def test_send_discord(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(alerts, "_post_json", lambda url, payload: calls.append((url, payload)))
    monkeypatch.setattr(alerts, "ALERTS", types.SimpleNamespace(discord_webhook_url="https://d/hook"))

    alerts._send_discord("Price drop", ["Widget price dropped 10%"])

    assert calls[0][0] == "https://d/hook"
    assert "Widget" in calls[0][1]["content"]


def test_send_telegram(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(alerts, "_post_json", lambda url, payload: calls.append((url, payload)))
    monkeypatch.setattr(
        alerts, "ALERTS",
        types.SimpleNamespace(telegram_bot_token="TOKEN", telegram_chat_id="42"),
    )

    alerts._send_telegram("Back in stock", ["Widget available"])

    assert "TOKEN" in calls[0][0] and calls[0][0].endswith("/sendMessage")
    assert calls[0][1]["chat_id"] == "42"
    assert "Widget" in calls[0][1]["text"]


def test_configured_sinks_includes_discord_and_telegram(monkeypatch):
    monkeypatch.setattr(
        alerts, "ALERTS",
        types.SimpleNamespace(
            webhook_url=None, slack_webhook_url=None, discord_webhook_url="https://d/hook",
            telegram_bot_token="t", telegram_chat_id="c", email_to=[], smtp_host=None, console=False,
        ),
    )
    assert set(alerts.configured_sinks()) == {"discord", "telegram"}


def test_sinks_skip_when_unconfigured(monkeypatch):
    calls: list = []
    monkeypatch.setattr(alerts, "_post_json", lambda url, payload: calls.append(payload))
    monkeypatch.setattr(
        alerts, "ALERTS",
        types.SimpleNamespace(discord_webhook_url=None, telegram_bot_token=None, telegram_chat_id=None),
    )
    alerts._send_discord("s", ["l"])
    alerts._send_telegram("s", ["l"])
    assert calls == []
