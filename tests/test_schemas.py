"""Tests for user-defined YAML/JSON schemas + unified resolver (roadmap item 7)."""

from __future__ import annotations

from crawlr import config, schemas

JOBS_YAML = """
name: jobs
item_selector: ".job"
fields:
  - name: title
    description: job title
    type: text
    required: true
  - name: salary
    description: annual salary
    type: number
"""


def _write(text: str, name: str = "jobs.yaml"):
    config.SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    path = config.SCHEMA_DIR / name
    path.write_text(text)
    return path


def test_load_user_schema():
    _write(JOBS_YAML)
    loaded = schemas.load_user_schemas()
    assert "jobs" in loaded
    assert loaded["jobs"].item_selector == ".job"


def test_resolve_user_and_builtin():
    _write(JOBS_YAML)
    assert schemas.resolve("jobs") is not None
    assert schemas.resolve("product") is not None  # built-in vertical
    assert schemas.resolve("does-not-exist") is None


def test_available_includes_both_sources():
    _write(JOBS_YAML)
    names = {i["name"] for i in schemas.available()}
    assert {"product", "product_list", "jobs"} <= names


def test_validate_file_reports_ok_and_errors():
    good = _write(JOBS_YAML)
    ok, _ = schemas.validate_file(good)
    assert ok

    bad = config.SCHEMA_DIR / "bad.yaml"
    bad.write_text("name: broken\nfields: not-a-list\n")
    ok2, msg2 = schemas.validate_file(bad)
    assert not ok2 and "invalid" in msg2
