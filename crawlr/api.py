"""Crawlr dashboard + JSON API.

A black-and-white, iOS-styled watchlist: paste a product URL, pick when to be
alerted (the trigger filter), and track price movement + stock at a glance.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from . import config
from . import digest as digest_mod
from . import schemas as schema_registry
from . import storage
from .extractor import scrape as scrape_url
from .models import MonitoredSite, TriggerType
from .monitor import run_once


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    storage.init_db()
    yield


app = FastAPI(title="Crawlr", version="0.2.0", lifespan=_lifespan)


def require_api_key(
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
) -> None:
    """Gate the JSON API behind CRAWLR_API_KEY when it is configured."""
    key = config.API_KEY
    if not key:
        return  # open when no key is set (local use)
    supplied = x_api_key
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization.split(" ", 1)[1]
    if supplied != key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


_AUTH = [Depends(require_api_key)]


class ScrapeRequest(BaseModel):
    url: str
    schema_name: str = "product"


class WatchRequest(BaseModel):
    url: str
    schema_name: str = "product"
    trigger: str = "any_change"
    target_price: float | None = None
    interval: int = 60

# Friendly labels for the trigger filter dropdown.
_TRIGGER_LABELS = {
    "any_change": "Any change",
    "price_drop": "Price drops",
    "price_below": "Price at/below target",
    "price_above": "Price at/above target",
    "back_in_stock": "Back in stock",
    "out_of_stock": "Out of stock",
}


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------


@app.get("/api/sites", dependencies=_AUTH)
def api_sites() -> list[dict]:
    return storage.list_sites()


@app.get("/api/watchlist", dependencies=_AUTH)
def api_watchlist() -> list[dict]:
    return storage.watchlist()


@app.get("/api/sites/{site_id}/records", dependencies=_AUTH)
def api_records(site_id: int) -> list[dict]:
    return storage.latest_records(site_id)


@app.get("/api/sites/{site_id}/history", dependencies=_AUTH)
def api_history(site_id: int, item_key: str, field: str = "price") -> list[dict]:
    return storage.price_history(site_id, item_key, field)


@app.get("/api/changes", dependencies=_AUTH)
def api_changes(site_id: int | None = None, limit: int = 50) -> list[dict]:
    return storage.recent_changes(site_id, limit)


@app.get("/api/schemas", dependencies=_AUTH)
def api_schemas() -> list[dict]:
    return schema_registry.available()


@app.get("/api/stats", dependencies=_AUTH)
def api_stats() -> list[dict]:
    return storage.site_stats()


@app.get("/api/digest", dependencies=_AUTH)
def api_digest(hours: int = 24) -> dict:
    return digest_mod.build(hours)


@app.post("/api/scrape", dependencies=_AUTH)
def api_scrape(req: ScrapeRequest) -> dict:
    schema = schema_registry.resolve(req.schema_name)
    if schema is None:
        raise HTTPException(status_code=400, detail=f"unknown schema '{req.schema_name}'")
    return scrape_url(req.url, schema).model_dump(mode="json")


@app.post("/api/watch", dependencies=_AUTH)
def api_watch(req: WatchRequest) -> dict:
    schema = schema_registry.resolve(req.schema_name)
    if schema is None:
        raise HTTPException(status_code=400, detail=f"unknown schema '{req.schema_name}'")
    try:
        trigger = TriggerType(req.trigger)
    except ValueError:
        trigger = TriggerType.ANY_CHANGE
    site_id = storage.add_site(
        MonitoredSite(
            url=req.url,
            schema_name=req.schema_name,
            interval_minutes=req.interval,
            trigger=trigger,
            target_price=req.target_price,
        )
    )
    return {"id": site_id, "url": req.url, "schema": req.schema_name, "trigger": trigger.value}


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@app.post("/sites")
def add_watch_action(
    url: str = Form(...),
    schema_name: str = Form("product"),
    alert_trigger: str = Form("any_change"),
    target_price: str = Form(""),
    interval: int = Form(60),
) -> RedirectResponse:
    if schema_registry.resolve(schema_name) is not None:
        try:
            trigger = TriggerType(alert_trigger)
        except ValueError:
            trigger = TriggerType.ANY_CHANGE
        target = None
        try:
            target = float(target_price) if target_price.strip() else None
        except ValueError:
            target = None
        storage.add_site(
            MonitoredSite(
                url=url,
                schema_name=schema_name,
                interval_minutes=interval,
                trigger=trigger,
                target_price=target,
            )
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
    rows = storage.watchlist()
    changes = storage.recent_changes(limit=20)

    schema_options = "".join(
        f"<option value='{s['name']}'>{s['name']}</option>" for s in schema_registry.available()
    )
    trigger_options = "".join(
        f"<option value='{value}'>{label}</option>" for value, label in _TRIGGER_LABELS.items()
    )

    watch_rows = "".join(_watch_row(r) for r in rows) or (
        "<tr><td colspan='8' class='empty'>Nothing watched yet — add a product below.</td></tr>"
    )
    change_rows = "".join(
        f"<tr><td class='mono'>{c['changed_at'][:19].replace('T', ' ')}</td>"
        f"<td>{_short(c['item_key'])}</td><td>{c['field']}</td>"
        f"<td class='mono'>{c['old_value']}</td><td class='mono strong'>{c['new_value']}</td></tr>"
        for c in changes
    ) or "<tr><td colspan='5' class='empty'>No changes recorded yet.</td></tr>"

    watching = sum(1 for r in rows if r["active"])
    return _PAGE.format(
        watch_rows=watch_rows,
        change_rows=change_rows,
        count=len(rows),
        watching=watching,
        schema_options=schema_options,
        trigger_options=trigger_options,
    )


def _watch_row(r: dict) -> str:
    spark = _sparkline_for_site(r["id"])
    return (
        "<tr>"
        f"<td class='title'>{_short(r['title'] or r['url'], 46)}"
        f"<div class='sub'>{_short(r['url'], 52)}</div></td>"
        f"<td class='num strong'>{_price(r['price'])}</td>"
        f"<td class='num was'>{_price(r['prev_price'])}</td>"
        f"<td class='num'>{_change(r['change_pct'])}</td>"
        f"<td>{_stock(r['in_stock'])}</td>"
        f"<td class='num'>{_price(r['target_price'])}</td>"
        f"<td><span class='pill'>{r['status']}</span>{spark}</td>"
        f"<td class='right'><form method='post' action='/sites/{r['id']}/run'>"
        f"<button class='btn'>Check</button></form></td>"
        "</tr>"
    )


def _price(v) -> str:
    if v is None:
        return "<span class='dim'>—</span>"
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _change(pct) -> str:
    if pct is None:
        return "<span class='dim'>—</span>"
    if pct < 0:
        return f"<span class='down'>&#9660; {abs(pct)}%</span>"
    if pct > 0:
        return f"<span class='up'>&#9650; {pct}%</span>"
    return "<span class='dim'>0%</span>"


def _stock(in_stock) -> str:
    if in_stock is True:
        return "<span class='dot filled'></span>In stock"
    if in_stock is False:
        return "<span class='dot'></span>Out"
    return "<span class='dim'>—</span>"


def _sparkline_for_site(site_id: int) -> str:
    records = storage.latest_records(site_id)
    if not records or not records[0].get("item_key"):
        return ""
    series = storage.price_history(site_id, records[0]["item_key"], "price")
    values = [p["value"] for p in series if isinstance(p["value"], (int, float))]
    if len(values) < 2:
        return ""
    return _sparkline(values)


def _sparkline(values: list[float], width: int = 80, height: int = 20) -> str:
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    points = " ".join(
        f"{(i / (n - 1)) * width:.1f},{height - ((v - lo) / span) * height:.1f}"
        for i, v in enumerate(values)
    )
    return (
        f"<svg class='spark' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>"
        f"<polyline fill='none' stroke='currentColor' stroke-width='1.5' points='{points}'/></svg>"
    )


def _short(text, n: int = 45) -> str:
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "\u2026"


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crawlr</title>
<style>
  :root {{
    --ink: #0a0a0a; --paper: #ffffff; --line: #e5e5e5; --muted: #8a8a8a;
    --chip: #f2f2f2; --radius: 14px;
    --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
            "Helvetica Neue", "Segoe UI", Roboto, sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: var(--font); margin: 0; background: var(--paper); color: var(--ink);
         -webkit-font-smoothing: antialiased; letter-spacing: -0.01em; }}
  .wrap {{ max-width: 1000px; margin: 0 auto; padding: 3rem 1.5rem 5rem; }}
  header {{ display: flex; align-items: baseline; gap: .75rem; margin-bottom: .25rem; }}
  h1 {{ font-size: 2rem; font-weight: 700; margin: 0; letter-spacing: -0.03em; }}
  .count {{ color: var(--muted); font-size: .95rem; }}
  .tagline {{ color: var(--muted); margin: 0 0 2.5rem; font-size: 1rem; }}
  h2 {{ font-size: .8rem; font-weight: 600; text-transform: uppercase; letter-spacing: .08em;
        color: var(--muted); margin: 2.5rem 0 .75rem; }}
  .card {{ border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden;
           background: var(--paper); }}
  table {{ width: 100%; border-collapse: collapse; font-size: .95rem; }}
  th {{ text-align: left; font-weight: 600; color: var(--muted); font-size: .75rem;
        text-transform: uppercase; letter-spacing: .05em; padding: .85rem 1rem; }}
  td {{ padding: .85rem 1rem; border-top: 1px solid var(--line); vertical-align: middle; }}
  tbody tr:hover {{ background: #fafafa; }}
  .title {{ font-weight: 600; max-width: 320px; }}
  .sub {{ color: var(--muted); font-weight: 400; font-size: .78rem; margin-top: .15rem; }}
  .num {{ font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }}
  .right {{ text-align: right; }}
  .strong {{ font-weight: 700; }}
  .was {{ color: var(--muted); text-decoration: line-through; }}
  .up {{ font-weight: 600; }} .down {{ font-weight: 600; }}
  .dim, .empty {{ color: var(--muted); }}
  .empty {{ text-align: center; padding: 2rem; }}
  .mono {{ font-variant-numeric: tabular-nums; }}
  .pill {{ display: inline-block; background: var(--chip); border-radius: 999px;
           padding: .15rem .6rem; font-size: .78rem; font-weight: 500; }}
  .dot {{ display: inline-block; width: .55rem; height: .55rem; border-radius: 50%;
          border: 1.5px solid var(--ink); margin-right: .4rem; vertical-align: middle; }}
  .dot.filled {{ background: var(--ink); }}
  .spark {{ display: block; margin-top: .4rem; color: var(--ink); }}
  .btn {{ font-family: var(--font); background: var(--ink); color: var(--paper); border: 0;
          border-radius: 999px; padding: .4rem .9rem; font-size: .82rem; font-weight: 600;
          cursor: pointer; }}
  .btn:hover {{ opacity: .85; }}
  form.add {{ display: flex; gap: .6rem; flex-wrap: wrap; align-items: center;
              margin-top: 1rem; padding: 1rem; border: 1px solid var(--line);
              border-radius: var(--radius); }}
  input, select {{ font-family: var(--font); background: var(--paper); color: var(--ink);
          border: 1px solid var(--line); border-radius: 10px; padding: .55rem .7rem;
          font-size: .92rem; }}
  input:focus, select:focus {{ outline: 2px solid var(--ink); outline-offset: -1px; }}
  input[type=url] {{ flex: 1; min-width: 240px; }}
  input[type=number] {{ width: 6.5rem; }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>Crawlr</h1>
      <span class="count">{watching} active / {count} watched</span>
    </header>
    <p class="tagline">Competitor price &amp; stock monitoring — self-healing.</p>

    <h2>Watchlist</h2>
    <div class="card">
      <table>
        <thead><tr>
          <th>Product</th><th class="num">Current</th><th class="num">Was</th>
          <th class="num">Change</th><th>Stock</th><th class="num">Target</th>
          <th>Status</th><th></th>
        </tr></thead>
        <tbody>{watch_rows}</tbody>
      </table>
    </div>

    <form class="add" method="post" action="/sites">
      <input type="url" name="url" placeholder="https://store.example/product/123" required>
      <select name="schema_name" title="Schema">{schema_options}</select>
      <select name="alert_trigger" title="Alert me when">{trigger_options}</select>
      <input type="number" name="target_price" placeholder="Target $" step="0.01" min="0">
      <input type="number" name="interval" value="60" min="1" title="Every N minutes">
      <button class="btn" type="submit">Watch</button>
    </form>

    <h2>Recent changes</h2>
    <div class="card">
      <table>
        <thead><tr><th>When</th><th>Item</th><th>Field</th><th>Old</th><th>New</th></tr></thead>
        <tbody>{change_rows}</tbody>
      </table>
    </div>
  </div>
</body>
</html>"""
