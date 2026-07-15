"""Raw HTML snapshot archival (Reliability v2).

Every successful fetch can be saved (gzip-compressed) so you can re-extract
offline, audit what a page looked like, and debug selectors without hitting the
network again. One latest snapshot is kept per (url, schema).
"""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

from . import config


def _snapshot_dir() -> Path:
    config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return config.SNAPSHOT_DIR


def _path(url: str, schema_name: str) -> Path:
    key = hashlib.sha1(f"{url}::{schema_name}".encode("utf-8")).hexdigest()[:16]
    return _snapshot_dir() / f"{key}.html.gz"


def save(url: str, schema_name: str, html: str) -> Path | None:
    """Persist the page HTML (compressed). Returns the path, or None if empty."""
    if not html:
        return None
    path = _path(url, schema_name)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(html)
    return path


def load_latest(url: str, schema_name: str) -> str | None:
    """Return the most recently archived HTML for (url, schema), if any."""
    path = _path(url, schema_name)
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return fh.read()
