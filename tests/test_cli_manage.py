"""Tests for the watch-management CLI commands and --json output."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from crawlr.cli import app
from crawlr.models import MonitoredSite
from crawlr import storage

runner = CliRunner()


def _add() -> int:
    return storage.add_site(
        MonitoredSite(url="https://x.test/p", schema_name="product", interval_minutes=5)
    )


def test_pause_resume_unwatch():
    site_id = _add()

    assert runner.invoke(app, ["pause", str(site_id)]).exit_code == 0
    assert storage.get_site(site_id)["active"] == 0

    assert runner.invoke(app, ["resume", str(site_id)]).exit_code == 0
    assert storage.get_site(site_id)["active"] == 1

    assert runner.invoke(app, ["unwatch", str(site_id)]).exit_code == 0
    assert storage.get_site(site_id) is None


def test_unwatch_missing_site_errors():
    result = runner.invoke(app, ["unwatch", "999999"])
    assert result.exit_code == 1


def test_watchlist_json_output():
    _add()
    result = runner.invoke(app, ["watchlist", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list) and len(data) == 1
