"""Monitoring layer: run scrapes, persist snapshots, and detect changes.

`run_once` scrapes a single site, stores the run, diffs it against the previous
run, and logs any changes (e.g. price drops, stock changes). `run_due` iterates
all active sites whose interval has elapsed. Scheduling is intentionally simple
and stateless so it can be driven by cron, a loop, or an external scheduler.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import storage
from .extractor import scrape
from .models import ExtractionResult, ExtractionSchema, PriceChange


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
) -> tuple[ExtractionResult, list[PriceChange]]:
    """Scrape a site once, store the run, and return detected changes."""
    site = storage.get_site(site_id)
    if site is None:
        raise ValueError(f"No site with id {site_id}")

    key_field = _key_field(schema)
    watch = watch_fields or [
        f.name for f in schema.fields if f.name not in (key_field,)
    ]

    result = scrape(site["url"], schema, force_js=force_js)

    previous = storage.latest_records(site_id)  # becomes "old" before we write new
    storage.record_run(
        site_id,
        result.records,
        healed=result.healed,
        used_llm=result.used_llm,
        fetched_at=result.fetched_at.isoformat(),
        key_field=key_field,
    )

    changes: list[PriceChange] = []
    if previous:
        prev_clean = [{k: v for k, v in r.items() if k != "item_key"} for r in previous]
        changes = diff_records(prev_clean, result.records, key_field, watch)
        storage.record_changes(site_id, changes)

    return result, changes


def _minutes_since_last_run(site_id: int, now: datetime) -> float:
    with storage._connect() as conn:  # noqa: SLF001 - internal helper reuse
        row = conn.execute(
            "SELECT fetched_at FROM runs WHERE site_id=? ORDER BY fetched_at DESC LIMIT 1",
            (site_id,),
        ).fetchone()
    if not row:
        return float("inf")
    last = datetime.fromisoformat(row["fetched_at"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last).total_seconds() / 60.0


def run_due(
    schema_resolver,
    watch_fields: list[str] | None = None,
    force_js: bool = False,
) -> dict[int, list[PriceChange]]:
    """Run all active sites whose interval has elapsed.

    `schema_resolver(schema_name) -> ExtractionSchema` supplies the schema for a
    given site (verticals register their schemas here).
    """
    now = datetime.now(timezone.utc)
    results: dict[int, list[PriceChange]] = {}
    for site in storage.list_sites(active_only=True):
        if _minutes_since_last_run(site["id"], now) < site["interval_minutes"]:
            continue
        schema = schema_resolver(site["schema_name"])
        if schema is None:
            continue
        _, changes = run_once(site["id"], schema, watch_fields, force_js)
        results[site["id"]] = changes
    return results
