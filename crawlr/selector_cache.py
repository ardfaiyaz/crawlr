"""Persistent cache of generated selectors, keyed by (host, schema name).

Caching selectors is what makes the engine cheap and fast: the LLM/heuristic
runs once per site+schema, then deterministic selectors are reused on every
subsequent scrape until they break.

The cache is stored in the shared database (the ``selectors`` table) rather than
a JSON file. This makes reads/writes concurrency-safe under the async monitor
runner and scales to the Postgres backend without a separate storage path.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from . import db
from .models import ExtractionSchema

# Standalone DDL so the cache works even if full schema init hasn't run yet.
_DDL = "CREATE TABLE IF NOT EXISTS selectors (cache_key TEXT PRIMARY KEY, schema_json TEXT NOT NULL)"


def _key(url: str, schema_name: str) -> str:
    return f"{urlparse(url).netloc}::{schema_name}"


def _outline_key(outline_hash: str, schema_name: str) -> str:
    return f"outline::{outline_hash}::{schema_name}"


def _get(cache_key: str) -> ExtractionSchema | None:
    with db.connect() as conn:
        conn.execute(_DDL)
        row = conn.execute(
            db.q("SELECT schema_json FROM selectors WHERE cache_key=?"), (cache_key,)
        ).fetchone()
    if row is None:
        return None
    return ExtractionSchema.model_validate(json.loads(row["schema_json"]))


def _put(cache_key: str, schema: ExtractionSchema) -> None:
    payload = json.dumps(schema.model_dump(mode="json"))
    with db.connect() as conn:
        conn.execute(_DDL)
        conn.execute(
            db.q(
                "INSERT INTO selectors (cache_key, schema_json) VALUES (?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET schema_json=excluded.schema_json"
            ),
            (cache_key, payload),
        )


def get(url: str, schema_name: str) -> ExtractionSchema | None:
    return _get(_key(url, schema_name))


def put(url: str, schema: ExtractionSchema) -> None:
    _put(_key(url, schema.name), schema)


def invalidate(url: str, schema_name: str) -> None:
    with db.connect() as conn:
        conn.execute(_DDL)
        conn.execute(
            db.q("DELETE FROM selectors WHERE cache_key=?"), (_key(url, schema_name),)
        )


def get_by_outline(outline_hash: str, schema_name: str) -> ExtractionSchema | None:
    """Second-layer cache keyed by the *content* of the simplified page.

    If two pages (even on different hosts) share the same structure, we can
    reuse selectors without paying for another LLM call.
    """
    return _get(_outline_key(outline_hash, schema_name))


def put_by_outline(outline_hash: str, schema: ExtractionSchema) -> None:
    _put(_outline_key(outline_hash, schema.name), schema)
