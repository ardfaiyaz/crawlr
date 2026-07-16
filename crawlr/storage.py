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

from . import db, triggers
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
    trigger_value = getattr(site.trigger, "value", site.trigger)
    with db.connect() as conn:
        site_id = db.insert_returning_id(
            conn,
            """INSERT INTO sites
               (url, schema_name, interval_minutes, active, alert_trigger, target_price, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url, schema_name) DO UPDATE SET
                 interval_minutes=excluded.interval_minutes, active=excluded.active,
                 alert_trigger=excluded.alert_trigger, target_price=excluded.target_price""",
            (
                str(site.url),
                site.schema_name,
                site.interval_minutes,
                int(site.active),
                trigger_value,
                site.target_price,
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


def delete_site(site_id: int) -> bool:
    """Remove a site and all of its runs, records, and change history."""
    with db.connect() as conn:
        exists = conn.execute(
            db.q("SELECT 1 FROM sites WHERE id=?"), (site_id,)
        ).fetchone()
        if not exists:
            return False
        conn.execute(db.q("DELETE FROM records WHERE site_id=?"), (site_id,))
        conn.execute(db.q("DELETE FROM runs WHERE site_id=?"), (site_id,))
        conn.execute(db.q("DELETE FROM changes WHERE site_id=?"), (site_id,))
        conn.execute(db.q("DELETE FROM alert_events WHERE site_id=?"), (site_id,))
        conn.execute(db.q("DELETE FROM sites WHERE id=?"), (site_id,))
        return True


def record_alert_event(
    site_id: int | None,
    item_key: str | None,
    field: str | None,
    message: str,
    sinks: list[str] | None,
    dedup_key: str | None,
) -> None:
    """Persist a dispatched alert so it appears in history and throttling works."""
    with db.connect() as conn:
        conn.execute(
            db.q(
                "INSERT INTO alert_events "
                "(site_id, item_key, field, message, sinks, dedup_key, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)"
            ),
            (site_id, item_key, field, message, ",".join(sinks or []), dedup_key, _now_iso()),
        )


def was_recently_alerted(dedup_key: str | None, within_minutes: int) -> bool:
    """True if an alert with the same dedup key fired inside the throttle window."""
    if within_minutes <= 0 or not dedup_key:
        return False
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=within_minutes)).isoformat()
    with db.connect() as conn:
        row = conn.execute(
            db.q("SELECT 1 FROM alert_events WHERE dedup_key=? AND created_at>=? LIMIT 1"),
            (dedup_key, cutoff),
        ).fetchone()
    return row is not None


def recent_alert_events(site_id: int | None = None, limit: int = 25) -> list[dict]:
    """Most recent dispatched alerts, newest first (optionally per site)."""
    limit = min(max(limit, 1), 500)
    with db.connect() as conn:
        if site_id is None:
            rows = conn.execute(
                db.q("SELECT * FROM alert_events ORDER BY created_at DESC LIMIT ?"), (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                db.q(
                    "SELECT * FROM alert_events WHERE site_id=? ORDER BY created_at DESC LIMIT ?"
                ),
                (site_id, limit),
            ).fetchall()
    return [dict(r) for r in rows]


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
        if run_id is None:
            raise RuntimeError("failed to record run (no insert id returned)")
        for rec in records:
            item_key = str(rec.get(key_field)) if key_field and rec.get(key_field) else None
            conn.execute(
                db.q(
                    """INSERT INTO records (run_id, site_id, item_key, data_json, fetched_at)
                       VALUES (?, ?, ?, ?, ?)"""
                ),
                (run_id, site_id, item_key, json.dumps(rec), ts),
            )
        return run_id


def prune_site_runs(site_id: int, keep_runs: int) -> int:
    """Delete all but the ``keep_runs`` most recent runs (and their records) for a site.

    Time-series records accumulate unbounded under continuous monitoring; this
    caps per-site history so long-running deployments don't grow without limit.
    Returns the number of runs deleted; ``keep_runs <= 0`` is a no-op (keep all).
    """
    if keep_runs <= 0:
        return 0
    with db.connect() as conn:
        rows = conn.execute(
            db.q("SELECT id FROM runs WHERE site_id=? ORDER BY fetched_at DESC, id DESC"),
            (site_id,),
        ).fetchall()
        old_ids = [r["id"] for r in rows[keep_runs:]]
        if not old_ids:
            return 0
        placeholders = ",".join(db.PH for _ in old_ids)
        conn.execute(
            f"DELETE FROM records WHERE run_id IN ({placeholders})", tuple(old_ids)
        )
        conn.execute(f"DELETE FROM runs WHERE id IN ({placeholders})", tuple(old_ids))
        return len(old_ids)


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


def price_history(site_id: int, item_key: str | None = None, field: str = "price") -> list[dict]:
    """Time series of a field for one item, useful for charts.

    ``item_key`` is ``None`` for single-product pages (one record per run); in
    that case we return the field across every run for the site.
    """
    with db.connect() as conn:
        if item_key is None:
            rows = conn.execute(
                db.q(
                    "SELECT data_json, fetched_at FROM records WHERE site_id=? "
                    "AND item_key IS NULL ORDER BY fetched_at ASC"
                ),
                (site_id,),
            ).fetchall()
        else:
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


def all_price_points(field: str = "price") -> dict[tuple[int, str | None], list[float]]:
    """Numeric time-series for every (site, item), built in a single query.

    Used by the dashboard to render sparklines for all watched rows without
    issuing a query per row (avoids an N+1 pattern as the watchlist grows).
    """
    with db.connect() as conn:
        rows = conn.execute(
            db.q("SELECT site_id, item_key, data_json FROM records ORDER BY fetched_at ASC")
        ).fetchall()
    out: dict[tuple[int, str | None], list[float]] = {}
    for r in rows:
        value = json.loads(r["data_json"]).get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.setdefault((r["site_id"], r["item_key"]), []).append(float(value))
    return out


# ---------------------------------------------------------------------------
# Watchlist (the simple, price/stock-focused view)
# ---------------------------------------------------------------------------


def watchlist() -> list[dict]:
    """Assemble one enriched row per site: current price, movement, stock, status."""
    rows: list[dict] = []
    for site in list_sites():
        sid = site["id"]
        latest = latest_records(sid)
        previous = previous_records(sid)
        run = latest_run(sid)
        current = latest[0] if latest else {}
        prev_rec = previous[0] if previous else {}

        price = current.get("price")
        prev_price = prev_rec.get("price")
        in_stock = triggers.is_in_stock(current.get("availability"))
        trigger = site.get("alert_trigger", "any_change")
        target = site.get("target_price")

        change_pct = None
        if isinstance(price, (int, float)) and isinstance(prev_price, (int, float)) and prev_price:
            change_pct = round((price - prev_price) / prev_price * 100, 1)

        rows.append(
            {
                "id": sid,
                "url": site["url"],
                "schema_name": site["schema_name"],
                "interval_minutes": site["interval_minutes"],
                "active": site["active"],
                "alert_trigger": trigger,
                "target_price": target,
                "item_key": current.get("item_key"),
                "title": current.get("title") or current.get("item_key"),
                "price": price,
                "prev_price": prev_price,
                "change_pct": change_pct,
                "availability": current.get("availability"),
                "in_stock": in_stock,
                "confidence": run["confidence"] if run else None,
                "last_checked": run["fetched_at"] if run else None,
                "status": triggers.watch_status(price, in_stock, prev_price, trigger, target),
            }
        )
    return rows



def site_stats() -> list[dict]:
    """Per-site health metrics: run count, average confidence, heal count."""
    with db.connect() as conn:
        rows = conn.execute(
            db.q(
                "SELECT s.id AS id, s.url AS url, COUNT(r.id) AS runs, "
                "AVG(r.confidence) AS avg_confidence, "
                "SUM(r.healed) AS heals, SUM(r.used_llm) AS llm_runs "
                "FROM sites s LEFT JOIN runs r ON r.site_id=s.id "
                "GROUP BY s.id, s.url ORDER BY s.id"
            )
        ).fetchall()
    return [dict(r) for r in rows]
