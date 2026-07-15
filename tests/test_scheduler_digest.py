"""Tests for scheduler-integrated digests."""

from __future__ import annotations

import asyncio

from crawlr import digest as digest_module
from crawlr import monitor, scheduler


def test_digest_due_helper():
    assert scheduler._digest_due(0.0, 0, 999999) is False  # disabled
    assert scheduler._digest_due(0.0, 1, 3600) is True
    assert scheduler._digest_due(0.0, 1, 100) is False


def test_scheduler_sends_digest_when_due(monkeypatch):
    calls = {"n": 0}

    async def fake_run_due(resolver, concurrency=5, force_js=False):
        return {}

    monkeypatch.setattr(monitor, "run_due_async", fake_run_due)
    monkeypatch.setattr(
        digest_module, "send",
        lambda hours: calls.__setitem__("n", calls["n"] + 1) or {"total": 0},
    )
    monkeypatch.setattr(scheduler, "_digest_due", lambda last, every, now: True)

    asyncio.run(scheduler.run_forever(poll_seconds=0, digest_every_hours=1, max_iterations=1))
    assert calls["n"] == 1


def test_scheduler_skips_digest_when_disabled(monkeypatch):
    calls = {"n": 0}

    async def fake_run_due(resolver, concurrency=5, force_js=False):
        return {}

    monkeypatch.setattr(monitor, "run_due_async", fake_run_due)
    monkeypatch.setattr(
        digest_module, "send",
        lambda hours: calls.__setitem__("n", calls["n"] + 1) or {"total": 0},
    )
    asyncio.run(scheduler.run_forever(poll_seconds=0, digest_every_hours=0, max_iterations=1))
    assert calls["n"] == 0
