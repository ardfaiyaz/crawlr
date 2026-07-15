"""Tests for `crawlr doctor` health checks and notification sink helpers."""

from __future__ import annotations

from crawlr import alerts, doctor
from crawlr.config import AlertConfig


def test_run_checks_covers_key_areas():
    checks = doctor.run_checks()
    names = {c.name for c in checks}
    assert {"Python", "Data directory", "Database", "Schemas", "LLM provider"} <= names


def test_healthy_env_has_no_failures():
    # In the isolated temp env everything should be OK or WARN, never FAIL.
    assert not doctor.has_failures(doctor.run_checks())


def test_configured_sinks_default_console():
    assert "console" in alerts.configured_sinks()


def test_configured_sinks_reports_webhook(monkeypatch):
    monkeypatch.setattr(alerts, "ALERTS", AlertConfig(webhook_url="https://x.test", console=False))
    assert alerts.configured_sinks() == ["webhook"]
