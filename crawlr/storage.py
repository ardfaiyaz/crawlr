"""Persistence for monitored sites, scrape runs, records, and the change log.

Records are stored as time-series snapshots so runs can be diffed and price
history reconstructed. The SQL is dialect-portable and routed through `db`, so
the same code runs on SQLite (default) or Postgres (`CRAWLR_DATABASE_URL`).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from . import db
from .models import MonitoredSite, PriceChange


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect() -> Iterator:
    """Backward-compatible connection helper (delegates to the db layer)."""
    with db.connect() as conn:
        yield conn


def init_db() -> None:
    with db.connect() as conn:
        db.init_schema(conn)


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


def add_site(site: MonitoredSite) -> int:
    with db.connect() as conn:
        site_id = db.insert_returning_id(
            conn,
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
        if site_id:
            return site_id
        row = conn.execute(
            db.q("SELECT id FROM sites WHERE url=? AND schema_name=?"),
            (str(site.url), site.schema_name),
        ).fetchone()
        return int(row["id"])


def list_sites(active_only: bool = False) -> list[dict]:
    query = "SELECT * FROM sites"
    if active_only:
        query += " WHERE active=1"
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(query).fetchall()]


def get_site(site_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(db.q("SELECT * FROM sites WHERE id=?"), (site_id,)).fetchone()
        return dict(row) if row else None


def set_active(site_id: int, active: bool) -> None:
    with db.connect() as conn:
        conn.execute(db.q("UPDATE sites SET active=? WHERE id=?"), (int(active), site_id))


# ---------------------------------------------------------------------------
# Runs + records
# ---------------------------------------------------------------------------


def record_run(
    site_id: int,
    records: list[dict],
    *,
    healed: bool,
    used_llm: bool,
    confidence: float = 1.0,
    fetched_at: str | None = None,
    key_field: str | None = None,
) -> int:
    ts = fetched_at or _now_iso()
    with db.connect() as conn:
        run_id = db.insert_returning_id(
            conn,
            """INSERT INTO runs (site_id, fetched_at, record_count, healed, used_llm, confidence)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (site_id, ts, len(records), int(healed), int(used_llm), float(confidence)),
        )
        for rec in records:
            item_key = str(rec.get(key_field)) if key_field and rec.get(key_field) else None
            conn.execute(
                db.q(
                    """INSERT INTO records (run_id, site_id, item_key, data_json, fetched_at)
                       VALUES (?, ?, ?, ?, ?)"""
                ),
                (run_id, site_id, item_key, json.dumps(rec), ts),
            )
        return int(run_id)


def latest_run(site_id: int) -> dict | None:
    """Most recent run's metadata (for dashboard health indicators)."""
    with db.connect() as conn:
        row = conn.execute(
            db.q("SELECT * FROM runs WHERE site_id=? ORDER BY fetched_at DESC LIMIT 1"),
            (site_id,),
        ).fetchone()
        return dict(row) if row else None


def latest_records(site_id: int) -> list[dict]:
    """Return records from the most recent run for a site."""
    with db.connect() as conn:
        run = conn.execute(
            db.q("SELECT id FROM runs WHERE site_id=? ORDER BY fetched_at DESC LIMIT 1"),
            (site_id,),
        ).fetchone()
        if not run:
            return []
        rows = conn.execute(
            db.q("SELECT data_json, item_key FROM records WHERE run_id=?"), (run["id"],)
        ).fetchall()
        return [{"item_key": r["item_key"], **json.loads(r["data_json"])} for r in rows]


def previous_records(site_id: int) -> list[dict]:
    """Records from the run just before the most recent one (for diffing)."""
    with db.connect() as conn:
        runs = conn.execute(
            db.q("SELECT id FROM runs WHERE site_id=? ORDER BY fetched_at DESC LIMIT 2"),
            (site_id,),
        ).fetchall()
        if len(runs) < 2:
            return []
        prev_run_id = runs[1]["id"]
        rows = conn.execute(
            db.q("SELECT data_json, item_key FROM records WHERE run_id=?"), (prev_run_id,)
        ).fetchall()
        return [{"item_key": r["item_key"], **json.loads(r["data_json"])} for r in rows]


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------


def record_changes(site_id: int, changes: list[PriceChange]) -> None:
    if not changes:
        return
    with db.connect() as conn:
        for c in changes:
            conn.execute(
                db.q(
                    """INSERT INTO changes
                       (site_id, item_key, field, old_value, new_value, changed_at)
                       VALUES (?, ?, ?, ?, ?, ?)"""
                ),
                (
                    site_id,
                    c.product_url,
                    c.field,
                    c.old_value,
                    c.new_value,
                    c.changed_at.isoformat(),
                ),
            )


def recent_changes(site_id: int | None = None, limit: int = 50) -> list[dict]:
    query = "SELECT c.*, s.url AS site_url FROM changes c JOIN sites s ON s.id=c.site_id"
    params: tuple = ()
    if site_id is not None:
        query += " WHERE c.site_id=?"
        params = (site_id,)
    query += " ORDER BY c.changed_at DESC LIMIT ?"
    params = params + (limit,)
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(db.q(query), params).fetchall()]


def price_history(site_id: int, item_key: str, field: str = "price") -> list[dict]:
    """Time series of a field for one item, useful for charts."""
    with db.connect() as conn:
        rows = conn.execute(
            db.q(
                "SELECT data_json, fetched_at FROM records WHERE site_id=? AND item_key=? "
                "ORDER BY fetched_at ASC"
            ),
            (site_id, item_key),
        ).fetchall()
    series = []
    for r in rows:
        data = json.loads(r["data_json"])
        if field in data:
            series.append({"at": r["fetched_at"], "value": data[field]})
    return series
