"""Crawlr FastAPI dashboard + JSON API for monitored sites and detected changes."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from . import storage


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


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    sites = storage.list_sites()
    changes = storage.recent_changes(limit=25)

    site_rows = "".join(
        f"<tr><td>{s['id']}</td><td><a href='{s['url']}'>{s['url']}</a></td>"
        f"<td>{s['schema_name']}</td><td>{s['interval_minutes']}m</td>"
        f"<td>{'active' if s['active'] else 'paused'}</td>"
        f"<td>{_latest_summary(s['id'])}</td></tr>"
        for s in sites
    ) or "<tr><td colspan='6' class='muted'>No sites yet.</td></tr>"

    change_rows = "".join(
        f"<tr><td>{c['changed_at'][:19]}</td><td>{_short(c['site_url'])}</td>"
        f"<td>{_short(c['item_key'])}</td><td>{c['field']}</td>"
        f"<td>{c['old_value']}</td><td class='new'>{c['new_value']}</td></tr>"
        for c in changes
    ) or "<tr><td colspan='6' class='muted'>No changes recorded yet.</td></tr>"

    return _PAGE.format(site_rows=site_rows, change_rows=change_rows, count=len(sites))


def _latest_summary(site_id: int) -> str:
    records = storage.latest_records(site_id)
    if not records:
        return "<span class='muted'>-</span>"
    first = records[0]
    price = first.get("price")
    title = first.get("title") or first.get("item_key") or ""
    return f"{_short(str(title), 30)} @ {price}" if price is not None else _short(str(title), 30)


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
</style>
</head>
<body>
  <h1>Crawlr <span class="badge">{count} sites</span></h1>
  <p class="sub">Self-healing price intelligence &mdash; monitored sites &amp; detected changes</p>

  <section>
    <h2>Monitored sites</h2>
    <table>
      <thead><tr><th>ID</th><th>URL</th><th>Schema</th><th>Interval</th>
        <th>Status</th><th>Latest</th></tr></thead>
      <tbody>{site_rows}</tbody>
    </table>
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
