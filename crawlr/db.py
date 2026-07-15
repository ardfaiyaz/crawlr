"""Database abstraction supporting SQLite (default) and Postgres (roadmap item 9).

Storage code is written once with `?` placeholders and portable SQL; this layer
adapts placeholders, DDL, and last-insert-id semantics to the active backend.
The backend is chosen by `CRAWLR_DATABASE_URL`:

  * unset / sqlite      -> local SQLite file (zero-config, fully tested path)
  * postgres[ql]://...  -> Postgres via the optional `psycopg` dependency

Keeping one SQL codebase means the SQLite test suite also exercises the exact
queries the Postgres backend runs.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from . import config

BACKEND = (
    "postgres"
    if config.DATABASE_URL
    and config.DATABASE_URL.startswith(("postgres://", "postgresql://"))
    else "sqlite"
)

# Placeholder token for parametrized queries in the active dialect.
PH = "%s" if BACKEND == "postgres" else "?"

_PK = "SERIAL PRIMARY KEY" if BACKEND == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS sites (
    id {_PK},
    url TEXT NOT NULL,
    schema_name TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL DEFAULT 60,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(url, schema_name)
);
CREATE TABLE IF NOT EXISTS runs (
    id {_PK},
    site_id INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    healed INTEGER NOT NULL DEFAULT 0,
    used_llm INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 1.0
);
CREATE TABLE IF NOT EXISTS records (
    id {_PK},
    run_id INTEGER NOT NULL,
    site_id INTEGER NOT NULL,
    item_key TEXT,
    data_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS changes (
    id {_PK},
    site_id INTEGER NOT NULL,
    item_key TEXT,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_site ON records(site_id, item_key, fetched_at);
CREATE INDEX IF NOT EXISTS idx_changes_site ON changes(site_id, changed_at);
"""


def q(sql: str) -> str:
    """Adapt `?` placeholders to the active backend's paramstyle."""
    return sql.replace("?", PH) if BACKEND == "postgres" else sql


@contextmanager
def connect() -> Iterator:
    """Yield a connection with dict-style row access, committing on success."""
    if BACKEND == "postgres":
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    else:
        import sqlite3

        conn = sqlite3.connect(config.DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        # Tolerate brief write contention from the concurrent async runner.
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_schema(conn) -> None:
    for statement in SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)


def insert_returning_id(conn, sql: str, params: tuple) -> int | None:
    """Run an INSERT and return the new row id across both backends."""
    if BACKEND == "postgres":
        cur = conn.execute(q(sql) + " RETURNING id", params)
        row = cur.fetchone()
        return int(row["id"]) if row else None
    cur = conn.execute(sql, params)
    return int(cur.lastrowid) if cur.lastrowid is not None else None
