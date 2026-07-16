"""Monitoring layer: run scrapes, persist snapshots, detect changes, alert.

`run_once` scrapes a single site, stores the run, diffs it against the previous
run, logs changes, and dispatches alerts. `run_due` / `run_due_async` iterate
all active sites whose interval has elapsed (sync, or concurrently for scale).
Scheduling is stateless so it can be driven by cron, the built-in daemon, or an
external scheduler.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable

from . import alerts, config, db, normalize, storage, triggers
from .config import MAX_PRICE_CHANGE_FACTOR, MIN_FIELD_CONFIDENCE
from .extractor import scrape
from .models import ExtractionResult, ExtractionSchema, PriceChange

SchemaResolver = Callable[[str], "ExtractionSchema | None"]


def _dedup_key(site_id: int, change: PriceChange) -> str:
    """Stable key for alert throttling/dedup per (site, item, field)."""
    return f"{site_id}|{change.field}|{change.product_url or ''}"


def _key_field(schema: ExtractionSchema) -> str | None:
    """Pick a stable per-item identity field for diffing (prefer url, then title)."""
    names = [f.name for f in schema.fields]
    for candidate in ("url", "link", "product_url", "title", "name"):
        if candidate in names:
            return candidate
    return names[0] if names else None


def _index_by_key(records: list[dict], key_field: str | None) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for rec in records:
        key = str(rec.get(key_field)) if key_field and rec.get(key_field) else None
        if key:
            indexed[key] = rec
    return indexed


def diff_records(
    old: list[dict],
    new: list[dict],
    key_field: str | None,
    watch_fields: list[str],
) -> list[PriceChange]:
    """Compare two runs and emit a change per (item, watched field) that moved."""
    old_idx = _index_by_key(old, key_field)
    new_idx = _index_by_key(new, key_field)
    changes: list[PriceChange] = []

    for key, new_rec in new_idx.items():
        old_rec = old_idx.get(key)
        if old_rec is None:
            changes.append(
                PriceChange(product_url=key, field="_new_item", old_value=None, new_value=key)
            )
            continue
        for field in watch_fields:
            ov, nv = old_rec.get(field), new_rec.get(field)
            if ov != nv:
                changes.append(
                    PriceChange(
                        product_url=key,
                        field=field,
                        old_value=None if ov is None else str(ov),
                        new_value=None if nv is None else str(nv),
                    )
                )

    for key in old_idx.keys() - new_idx.keys():
        changes.append(
            PriceChange(product_url=key, field="_removed_item", old_value=key, new_value=None)
        )
    return changes


def run_once(
    site_id: int,
    schema: ExtractionSchema,
    watch_fields: list[str] | None = None,
    force_js: bool = False,
    send_alerts: bool = True,
) -> tuple[ExtractionResult, list[PriceChange]]:
    """Scrape a site once, store the run, detect changes, and dispatch alerts."""
    site = storage.get_site(site_id)
    if site is None:
        raise ValueError(f"No site with id {site_id}")

    key_field = _key_field(schema)
    watch = watch_fields or [f.name for f in schema.fields if f.name != key_field]

    result = scrape(site["url"], schema, force_js=force_js)

    previous = storage.latest_records(site_id)  # becomes "old" before we write new
    storage.record_run(
        site_id,
        result.records,
        healed=result.healed,
        used_llm=result.used_llm,
        confidence=result.confidence,
        fetched_at=result.fetched_at.isoformat(),
        key_field=key_field,
    )

    changes: list[PriceChange] = []
    if previous:
        prev_clean = [{k: v for k, v in r.items() if k != "item_key"} for r in previous]
        changes = diff_records(prev_clean, result.records, key_field, watch)
        # Plausibility guard: drop absurd price moves (likely extraction errors).
        changes = [c for c in changes if _plausible_change(c)]
        # Field-confidence gate: skip changes on low-confidence fields.
        if result.field_confidence and MIN_FIELD_CONFIDENCE > 0:
            changes = [
                c for c in changes
                if result.field_confidence.get(c.field, 1.0) >= MIN_FIELD_CONFIDENCE
            ]
        storage.record_changes(site_id, changes)
        if send_alerts and changes:
            # Only alert on changes matching the site's trigger / rules template.
            to_alert = triggers.filter_changes(site, changes)
            # Throttle: skip changes we already alerted on within the window.
            if config.ALERTS.throttle_minutes > 0:
                to_alert = [
                    c for c in to_alert
                    if not storage.was_recently_alerted(
                        _dedup_key(site_id, c), config.ALERTS.throttle_minutes
                    )
                ]
            if to_alert:
                sent = alerts.notify(site["url"], to_alert)
                sinks = [s for s in alerts.configured_sinks() if s != "console"]
                for c in sent:
                    storage.record_alert_event(
                        site_id, c.product_url, c.field, alerts.describe(c),
                        sinks, _dedup_key(site_id, c),
                    )

    # Cap stored history per site when a retention window is configured. Runs
    # after diffing/recording so change detection always sees the prior run.
    if config.RETENTION_RUNS > 0:
        storage.prune_site_runs(site_id, config.RETENTION_RUNS)

    return result, changes


def _plausible_change(change: PriceChange) -> bool:
    """Reject implausible price moves (0/negative, or beyond the max factor)."""
    if change.field != "price":
        return True
    new = normalize.normalize_number(change.new_value)
    if new is None or new <= 0:
        return False
    old = normalize.normalize_number(change.old_value)
    if old is None or old <= 0:
        return True
    ratio = new / old
    return (1.0 / MAX_PRICE_CHANGE_FACTOR) <= ratio <= MAX_PRICE_CHANGE_FACTOR


def _minutes_since_last_run(site_id: int, now: datetime) -> float:
    with db.connect() as conn:
        row = conn.execute(
            db.q("SELECT fetched_at FROM runs WHERE site_id=? ORDER BY fetched_at DESC LIMIT 1"),
            (site_id,),
        ).fetchone()
    if not row:
        return float("inf")
    last = datetime.fromisoformat(row["fetched_at"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last).total_seconds() / 60.0


def _due_sites() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        site
        for site in storage.list_sites(active_only=True)
        if _minutes_since_last_run(site["id"], now) >= site["interval_minutes"]
    ]


def run_due(
    schema_resolver: SchemaResolver,
    watch_fields: list[str] | None = None,
    force_js: bool = False,
) -> dict[int, list[PriceChange]]:
    """Run all active sites whose interval has elapsed (sequentially)."""
    results: dict[int, list[PriceChange]] = {}
    for site in _due_sites():
        schema = schema_resolver(site["schema_name"])
        if schema is None:
            continue
        _, changes = run_once(site["id"], schema, watch_fields, force_js)
        results[site["id"]] = changes
    return results


async def run_due_async(
    schema_resolver: SchemaResolver,
    watch_fields: list[str] | None = None,
    force_js: bool = False,
    concurrency: int = 5,
) -> dict[int, list[PriceChange]]:
    """Run all due sites concurrently with a bounded worker pool (roadmap item 5).

    Each site's (synchronous) scrape runs in a worker thread, so many sites are
    fetched in parallel without a full async rewrite of the fetch stack.
    """
    due = _due_sites()
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: dict[int, list[PriceChange]] = {}

    async def _worker(site: dict) -> None:
        schema = schema_resolver(site["schema_name"])
        if schema is None:
            return
        async with semaphore:
            _, changes = await asyncio.to_thread(
                run_once, site["id"], schema, watch_fields, force_js
            )
        results[site["id"]] = changes

    await asyncio.gather(*(_worker(site) for site in due))
    return results
