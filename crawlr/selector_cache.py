"""Persistent cache of generated selectors, keyed by (host, schema name).

Caching selectors is what makes the engine cheap and fast: the LLM/heuristic
runs once per site+schema, then deterministic selectors are reused on every
subsequent scrape until they break.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from .config import SELECTOR_CACHE_PATH
from .models import ExtractionSchema


def _key(url: str, schema_name: str) -> str:
    return f"{urlparse(url).netloc}::{schema_name}"


def _load() -> dict:
    if SELECTOR_CACHE_PATH.exists():
        try:
            return json.loads(SELECTOR_CACHE_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save(data: dict) -> None:
    SELECTOR_CACHE_PATH.write_text(json.dumps(data, indent=2))


def get(url: str, schema_name: str) -> ExtractionSchema | None:
    data = _load()
    raw = data.get(_key(url, schema_name))
    if raw is None:
        return None
    return ExtractionSchema.model_validate(raw)


def put(url: str, schema: ExtractionSchema) -> None:
    data = _load()
    data[_key(url, schema.name)] = schema.model_dump(mode="json")
    _save(data)


def invalidate(url: str, schema_name: str) -> None:
    data = _load()
    data.pop(_key(url, schema_name), None)
    _save(data)
