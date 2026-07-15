"""Shared pytest fixtures: isolate each test in a fresh temp data dir.

Reloading the config-dependent modules ensures the SQLite DB, selector cache,
and schema directory all point inside the per-test temp directory, so tests are
fully isolated and run offline (no network, no LLM key).
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWLR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CRAWLR_RULES_FILE", str(tmp_path / "crawlr.rules.yaml"))
    monkeypatch.delenv("CRAWLR_DATABASE_URL", raising=False)
    monkeypatch.setenv("CRAWLR_LLM_PROVIDER", "none")
    monkeypatch.setenv("CRAWLR_RESPECT_ROBOTS", "false")
    monkeypatch.setenv("CRAWLR_JITTER", "0")
    monkeypatch.setenv("CRAWLR_MIN_DELAY", "0")

    import crawlr.config as config

    importlib.reload(config)
    for name in ("crawlr.db", "crawlr.selector_cache", "crawlr.usage", "crawlr.storage"):
        importlib.reload(importlib.import_module(name))

    from crawlr import storage

    storage.init_db()
    yield
