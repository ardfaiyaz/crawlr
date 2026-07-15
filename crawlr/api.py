"""Crawlr FastAPI dashboard + JSON API (roadmap item 8).

Beyond the read-only views it now supports adding sites and triggering runs from
the UI, shows per-site health (confidence from the latest run), and renders
inline price-history sparklines.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from . import schemas as schema_registry
from . import storage
from .models import MonitoredSite
from .monitor import run_once


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    storage.init_db()
    yield


app = FastAPI(title="Crawlr dashboard", version="0.1.0", lifespan=_lifespan)


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------


@app.get("/api/sites")
def api_sites() -> list[dict]:
    return storage.list_sites()


@app.get("/api/sites/{site_id}/records")
def api_records(site_id: int) -> list[dict]:
    return storage.latest_records(site_id)


@app.get("/api/sites/{site_id}/history")
def api_history(site_id: int, item_key: str, field: str = "price") -> list[dict]:
    return storage.price_history(site_id, item_key, field)


@app.get("/api/changes")
def api_changes(site_id: int | None = None, limit: int = 50) -> list[dict]:
    return storage.recent_changes(site_id, limit)


@app.get("/api/schemas")
def api_schemas() -> list[dict]:
    return schema_registry.available()


# ---------------------------------------------------------------------------
# Actions (add site, run now)
# ---------------------------------------------------------------------------


@app.post("/sites")
def add_site_action(
    url: str = Form(...),
    schema_name: str = Form("product"),
    interval: int = Form(60),
) -> RedirectResponse:
    if schema_registry.resolve(schema_name) is not None:
        storage.add_site(
            MonitoredSite(url=url, schema_name=schema_name, interval_minutes=interval)
        )
    return RedirectResponse("/", status_code=303)


@app.post("/sites/{site_id}/run")
def run_site_action(site_id: int) -> RedirectResponse:
    site = storage.get_site(site_id)
    if site is not None:
        schema = schema_registry.resolve(site["schema_name"])
        if schema is not None:
            run_once(site_id, schema)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    sites = storage.list_sites()
    changes = storage.recent_changes(limit=25)
    schema_options = "".join(
        f"<option value='{s['name']}'>{s['name']}</option>" for s in schema_registry.available()
    )

    site_rows = "".join(_site_row(s) for s in sites) or (
        "<tr><td colspan='7' class='muted'>No sites yet — add one below.</td></tr>"
    )

    change_rows = "".join(
        f"<tr><td>{c['changed_at'][:19]}</td><td>{_short(c['site_url'])}</td>"
        f"<td>{_short(c['item_key'])}</td><td>{c['field']}</td>"
        f"<td>{c['old_value']}</td><td class='new'>{c['new_value']}</td></tr>"
        for c in changes
    ) or "<tr><td colspan='6' class='muted'>No changes recorded yet.</td></tr>"

    return _PAGE.format(
        site_rows=site_rows,
        change_rows=change_rows,
        count=len(sites),
        schema_options=schema_options,
    )


def _site_row(s: dict) -> str:
    run = storage.latest_run(s["id"])
    health = _health_badge(run)
    spark = _sparkline_for_site(s["id"])
    return (
        f"<tr><td>{s['id']}</td>"
        f"<td><a href='{s['url']}'>{_short(s['url'], 40)}</a></td>"
        f"<td>{s['schema_name']}</td><td>{s['interval_minutes']}m</td>"
        f"<td>{'active' if s['active'] else 'paused'}</td>"
        f"<td>{health}</td>"
        f"<td>{_latest_summary(s['id'])} {spark}</td>"
        f"<td><form method='post' action='/sites/{s['id']}/run' style='margin:0'>"
        f"<button class='btn'>Run now</button></form></td></tr>"
    )


def _health_badge(run: dict | None) -> str:
    if not run:
        return "<span class='muted'>no runs</span>"
    conf = float(run.get("confidence", 0))
    color = "#7ee787" if conf >= 0.8 else "#e3b341" if conf >= 0.4 else "#f85149"
    return f"<span class='dot' style='background:{color}'></span>{conf:.0%}"


def _latest_summary(site_id: int) -> str:
    records = storage.latest_records(site_id)
    if not records:
        return "<span class='muted'>-</span>"
    first = records[0]
    price = first.get("price")
    title = first.get("title") or first.get("item_key") or ""
    label = _short(str(title), 26)
    return f"{label} @ {price}" if price is not None else label


def _sparkline_for_site(site_id: int) -> str:
    """Inline SVG sparkline of the first item's price history, if any."""
    records = storage.latest_records(site_id)
    if not records or not records[0].get("item_key"):
        return ""
    series = storage.price_history(site_id, records[0]["item_key"], "price")
    values = [p["value"] for p in series if isinstance(p["value"], (int, float))]
    if len(values) < 2:
        return ""
    return _sparkline(values)


def _sparkline(values: list[float], width: int = 90, height: int = 22) -> str:
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    points = " ".join(
        f"{(i / (n - 1)) * width:.1f},{height - ((v - lo) / span) * height:.1f}"
        for i, v in enumerate(values)
    )
    color = "#7ee787" if values[-1] <= values[0] else "#f85149"
    return (
        f"<svg width='{width}' height='{height}' viewBox='0 0 {width} {height}' "
        f"style='vertical-align:middle'><polyline fill='none' stroke='{color}' "
        f"stroke-width='1.5' points='{points}'/></svg>"
    )


def _short(text: str | None, n: int = 45) -> str:
    if not text:
        return ""
    return text if len(text) <= n else text[: n - 3] + "..."


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crawlr dashboard</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 2rem;
         background: #0f1116; color: #e6e6e6; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 .25rem; }}
  .sub {{ color: #8a93a6; margin-bottom: 2rem; font-size: .9rem; }}
  section {{ margin-bottom: 2.5rem; }}
  h2 {{ font-size: 1rem; text-transform: uppercase; letter-spacing: .05em;
        color: #8a93a6; border-bottom: 1px solid #262a33; padding-bottom: .5rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
  th, td {{ text-align: left; padding: .55rem .6rem; border-bottom: 1px solid #1c2029; }}
  th {{ color: #8a93a6; font-weight: 600; }}
  tr:hover td {{ background: #161a22; }}
  a {{ color: #6ea8fe; text-decoration: none; }}
  .muted {{ color: #5c6472; }}
  .new {{ color: #7ee787; font-weight: 600; }}
  .badge {{ display: inline-block; background: #1f6feb; color: #fff; padding: .1rem .5rem;
           border-radius: 999px; font-size: .75rem; }}
  .dot {{ display: inline-block; width: .6rem; height: .6rem; border-radius: 50%;
          margin-right: .4rem; }}
  .btn {{ background: #1f6feb; color: #fff; border: 0; border-radius: 6px;
          padding: .35rem .7rem; font-size: .8rem; cursor: pointer; }}
  .btn:hover {{ background: #388bfd; }}
  form.add {{ display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; margin-top: 1rem; }}
  input, select {{ background: #161a22; color: #e6e6e6; border: 1px solid #262a33;
          border-radius: 6px; padding: .4rem .6rem; font-size: .9rem; }}
  input[type=url] {{ flex: 1; min-width: 260px; }}
</style>
</head>
<body>
  <h1>Crawlr <span class="badge">{count} sites</span></h1>
  <p class="sub">Self-healing price intelligence &mdash; monitored sites &amp; detected changes</p>

  <section>
    <h2>Monitored sites</h2>
    <table>
      <thead><tr><th>ID</th><th>URL</th><th>Schema</th><th>Interval</th>
        <th>Status</th><th>Health</th><th>Latest</th><th></th></tr></thead>
      <tbody>{site_rows}</tbody>
    </table>
    <form class="add" method="post" action="/sites">
      <input type="url" name="url" placeholder="https://store.example/product/123" required>
      <select name="schema_name">{schema_options}</select>
      <input type="number" name="interval" value="60" min="1" title="Interval (minutes)"
             style="width:6rem">
      <button class="btn" type="submit">Add site</button>
    </form>
  </section>

  <section>
    <h2>Recent changes</h2>
    <table>
      <thead><tr><th>When</th><th>Site</th><th>Item</th><th>Field</th>
        <th>Old</th><th>New</th></tr></thead>
      <tbody>{change_rows}</tbody>
    </table>
  </section>
</body>
</html>"""
