"""Tests for bundled vertical presets (jobs, real_estate, news)."""

from __future__ import annotations

from crawlr import schemas


def test_presets_are_bundled():
    presets = schemas.load_presets()
    assert {"jobs", "real_estate", "news"} <= set(presets)


def test_resolve_preset_by_name():
    jobs = schemas.resolve("jobs")
    assert jobs is not None
    assert any(f.name == "title" for f in jobs.fields)


def test_available_lists_sources():
    pairs = {(i["name"], i["source"]) for i in schemas.available()}
    assert ("product", "built-in") in pairs
    assert ("jobs", "preset") in pairs
