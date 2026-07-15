"""SQLite persistence: monitored sites, scrape runs, records, and change log.

Records are stored as time-series snapshots so we can diff runs and build price
history. Everything is plain SQLite (zero-config); swap for Postgres later by
replacing this module.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import DB_PATH
from .models import MonitoredSite, PriceChange

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    schema_name TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL DEFAULT 60,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(url, schema_name)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    healed INTEGER NOT NULL DEFAULT 0,
    used_llm INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (site_id) REFERENCES sites(id)
);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    site_id INTEGER NOT NULL,
    item_key TEXT,
    data_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id),
    FOREIGN KEY (site_id) REFERENCES sites(id)
);

CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    item_key TEXT,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TEXT NOT NULL,
    FOREIGN KEY (site_id) REFERENCES sites(id)
);

CREATE INDEX IF NOT EXISTS idx_records_site ON records(site_id, item_key, fetched_at);
CREATE INDEX IF NOT EXISTS idx_changes_site ON changes(site_id, changed_at);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


def add_site(site: MonitoredSite) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO sites (url, schema_name, interval_minutes, active, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(url, schema_name) DO UPDATE SET
                 interval_minutes=excluded.interval_minutes, active=excluded.active""",
            (
                str(site.url),
                site.schema_name,
                site.interval_minutes,
                int(site.active),
                _now_iso(),
            ),
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM sites WHERE url=? AND schema_name=?",
            (str(site.url), site.schema_name),
        ).fetchone()
        return int(row["id"])


def list_sites(active_only: bool = False) -> list[dict]:
    query = "SELECT * FROM sites"
    if active_only:
        query += " WHERE active=1"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(query).fetchall()]


def get_site(site_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()
        return dict(row) if row else None


def set_active(site_id: int, active: bool) -> None:
    with _connect() as conn:
        conn.execute("UPDATE sites SET active=? WHERE id=?", (int(active), site_id))


# ---------------------------------------------------------------------------
# Runs + records
# ---------------------------------------------------------------------------


def record_run(
    site_id: int,
    records: list[dict],
    *,
    healed: bool,
    used_llm: bool,
    fetched_at: str | None = None,
    key_field: str | None = None,
) -> int:
    ts = fetched_at or _now_iso()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO runs (site_id, fetched_at, record_count, healed, used_llm)
               VALUES (?, ?, ?, ?, ?)""",
            (site_id, ts, len(records), int(healed), int(used_llm)),
        )
        run_id = int(cur.lastrowid)
        for rec in records:
            item_key = str(rec.get(key_field)) if key_field and rec.get(key_field) else None
            conn.execute(
                """INSERT INTO records (run_id, site_id, item_key, data_json, fetched_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (run_id, site_id, item_key, json.dumps(rec), ts),
            )
        return run_id


def latest_records(site_id: int) -> list[dict]:
    """Return records from the most recent run for a site."""
    with _connect() as conn:
        run = conn.execute(
            "SELECT id FROM runs WHERE site_id=? ORDER BY fetched_at DESC LIMIT 1",
            (site_id,),
        ).fetchone()
        if not run:
            return []
        rows = conn.execute(
            "SELECT data_json, item_key FROM records WHERE run_id=?", (run["id"],)
        ).fetchall()
        return [{"item_key": r["item_key"], **json.loads(r["data_json"])} for r in rows]


def previous_records(site_id: int) -> list[dict]:
    """Records from the run just before the most recent one (for diffing)."""
    with _connect() as conn:
        runs = conn.execute(
            "SELECT id FROM runs WHERE site_id=? ORDER BY fetched_at DESC LIMIT 2",
            (site_id,),
        ).fetchall()
        if len(runs) < 2:
            return []
        prev_run_id = runs[1]["id"]
        rows = conn.execute(
            "SELECT data_json, item_key FROM records WHERE run_id=?", (prev_run_id,)
        ).fetchall()
        return [{"item_key": r["item_key"], **json.loads(r["data_json"])} for r in rows]


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------


def record_changes(site_id: int, changes: list[PriceChange]) -> None:
    if not changes:
        return
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO changes (site_id, item_key, field, old_value, new_value, changed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    site_id,
                    c.product_url,
                    c.field,
                    c.old_value,
                    c.new_value,
                    c.changed_at.isoformat(),
                )
                for c in changes
            ],
        )


def recent_changes(site_id: int | None = None, limit: int = 50) -> list[dict]:
    query = "SELECT c.*, s.url AS site_url FROM changes c JOIN sites s ON s.id=c.site_id"
    params: tuple = ()
    if site_id is not None:
        query += " WHERE c.site_id=?"
        params = (site_id,)
    query += " ORDER BY c.changed_at DESC LIMIT ?"
    params = params + (limit,)
    with _connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def price_history(site_id: int, item_key: str, field: str = "price") -> list[dict]:
    """Time series of a field for one item, useful for charts."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT data_json, fetched_at FROM records WHERE site_id=? AND item_key=? "
            "ORDER BY fetched_at ASC",
            (site_id, item_key),
        ).fetchall()
    series = []
    for r in rows:
        data = json.loads(r["data_json"])
        if field in data:
            series.append({"at": r["fetched_at"], "value": data[field]})
    return series
