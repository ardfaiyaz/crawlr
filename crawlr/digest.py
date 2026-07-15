"""Change digest: a periodic summary of everything that changed (next wave).

Instead of one alert per change, a digest rolls up all changes across every
watched site over a window (e.g. the last 24h) into a single readable summary,
grouped by site and highlighting price drops and restocks. Dispatch it on a
cadence (cron / scheduler) via `crawlr digest --send`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import alerts, storage
from .triggers import is_in_stock


def build(hours: int = 24) -> dict:
    """Collect changes within the look-back window, grouped by site."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    recent = [c for c in storage.recent_changes(limit=2000) if c["changed_at"] >= since]

    by_site: dict[str, list[dict]] = {}
    for change in recent:
        by_site.setdefault(change["site_url"], []).append(change)

    return {"since_hours": hours, "total": len(recent), "sites": by_site}


def _highlight(change: dict) -> str:
    field, old, new = change["field"], change["old_value"], change["new_value"]
    item = (change.get("item_key") or "")[:44]
    if field == "price":
        try:
            o, n = float(old), float(new)
            pct = (o - n) / o * 100 if o else 0.0
            arrow = "down" if n < o else "up"
            return f"{item} price {arrow} {abs(pct):.1f}% ({old} -> {new})"
        except (TypeError, ValueError):
            pass
    if field == "availability":
        if is_in_stock(new) is True:
            return f"{item} back in stock"
        if is_in_stock(new) is False:
            return f"{item} out of stock"
    if field == "_new_item":
        return f"new item: {new}"
    if field == "_removed_item":
        return f"removed item: {old}"
    return f"{item} {field}: {old} -> {new}"


def summarize_lines(digest: dict, per_site: int = 15) -> list[str]:
    lines: list[str] = []
    for site, changes in digest["sites"].items():
        lines.append(f"{site} — {len(changes)} change(s)")
        for change in changes[:per_site]:
            lines.append(f"    {_highlight(change)}")
        if len(changes) > per_site:
            lines.append(f"    …and {len(changes) - per_site} more")
    return lines


def subject_for(digest: dict) -> str:
    return (
        f"Crawlr digest: {digest['total']} change(s) in the last "
        f"{digest['since_hours']}h across {len(digest['sites'])} site(s)"
    )


def send(hours: int = 24) -> dict:
    """Build and dispatch the digest to configured alert sinks (if any changes)."""
    digest = build(hours)
    if digest["total"] == 0:
        return digest
    alerts.send_message(subject_for(digest), summarize_lines(digest))
    return digest
