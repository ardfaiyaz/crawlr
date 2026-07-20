"""Crawlr dashboard + JSON API.

A white & green, iOS-styled control panel for the self-healing scraper: paste a
URL (schema auto-detected), pick when to be alerted, and watch price movement,
stock, and history at a glance.

Hardening notes:
  * All dynamic values are rendered through autoescaping Jinja2 templates, so
    scraped text (titles, URLs) can never inject HTML/JS into the dashboard.
  * The dashboard version is sourced from the installed package metadata.
  * API-key checks are constant-time; `/healthz` and `/readyz` support probes.
  * Manual "Check now" runs happen in a background task so the request returns
    immediately instead of blocking on a live scrape.
"""

from __future__ import annotations

import json
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Form, Header, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import DictLoader, Environment, select_autoescape
from pydantic import BaseModel, Field

import crawlr

from . import config
from . import digest as digest_mod
from . import schemas as schema_registry
from . import storage
from .extractor import scrape as scrape_url
from .models import MonitoredSite, TriggerType
from .monitor import run_once

logger = logging.getLogger("crawlr.api")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    storage.init_db()
    yield


app = FastAPI(title="Crawlr", version=crawlr.__version__, lifespan=_lifespan)
app.add_middleware(GZipMiddleware, minimum_size=512)


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
    # Constant-time comparison avoids leaking the key via response timing.
    if not supplied or not secrets.compare_digest(supplied, key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


_AUTH = [Depends(require_api_key)]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ScrapeRequest(BaseModel):
    url: str
    schema_name: str | None = None  # None -> auto-detect


class WatchRequest(BaseModel):
    url: str
    schema_name: str | None = None  # None -> auto-detect
    trigger: str = "any_change"
    target_price: float | None = None
    interval: int = Field(60, ge=1, le=100_000)
    # Optional per-site overrides (None -> inherit the global config default).
    anomaly_zscore: float | None = Field(None, ge=0)
    anomaly_min_samples: int | None = Field(None, ge=1)
    retention_runs: int | None = Field(None, ge=0)


class HealthOut(BaseModel):
    status: str
    version: str
    backend: str


class DetectOut(BaseModel):
    url: str
    schema_name: str


# Friendly labels for the trigger filter dropdown.
_TRIGGER_LABELS = {
    "any_change": "Any change",
    "price_drop": "Price drops",
    "price_below": "Price at/below target",
    "price_above": "Price at/above target",
    "back_in_stock": "Back in stock",
    "out_of_stock": "Out of stock",
}


def _resolve_or_detect(url: str, schema_name: str | None) -> str:
    """Return an existing schema name, auto-detecting from the URL when blank."""
    if schema_name:
        if schema_registry.resolve(schema_name) is None:
            raise HTTPException(status_code=400, detail=f"unknown schema '{schema_name}'")
        return schema_name
    from . import detect

    return detect.detect_schema(url)


# ---------------------------------------------------------------------------
# Health probes
# ---------------------------------------------------------------------------


@app.get("/healthz", response_model=HealthOut)
def healthz() -> HealthOut:
    """Liveness: the process is up (no dependency checks)."""
    from .db import BACKEND

    return HealthOut(status="ok", version=crawlr.__version__, backend=BACKEND)


@app.get("/readyz")
def readyz() -> JSONResponse:
    """Readiness: verify the database is reachable."""
    from .db import BACKEND

    try:
        storage.list_sites()
    except Exception as exc:  # pragma: no cover - only on a broken DB
        return JSONResponse({"status": "unavailable", "detail": str(exc)}, status_code=503)
    return JSONResponse({"status": "ready", "backend": BACKEND})


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
    return storage.recent_changes(site_id, min(max(limit, 1), 500))


@app.get("/api/alerts", dependencies=_AUTH)
def api_alerts(site_id: int | None = None, limit: int = 50) -> list[dict]:
    return storage.recent_alert_events(site_id, limit)


@app.get("/api/insights", dependencies=_AUTH)
def api_insights(site_id: int, item_key: str | None = None, field: str = "price") -> dict:
    data = storage.price_insights(site_id, item_key, field)
    data["availability"] = storage.availability_stats(site_id, item_key)
    return data


@app.get("/api/schemas", dependencies=_AUTH)
def api_schemas() -> list[dict]:
    return schema_registry.available()


@app.get("/api/stats", dependencies=_AUTH)
def api_stats() -> list[dict]:
    return storage.site_stats()


@app.get("/api/digest", dependencies=_AUTH)
def api_digest(hours: int = 24) -> dict:
    return digest_mod.build(hours)


@app.get("/api/detect", response_model=DetectOut, dependencies=_AUTH)
def api_detect(url: str = Query(...)) -> DetectOut:
    from . import detect

    return DetectOut(url=url, schema_name=detect.detect_schema(url))


@app.post("/api/scrape", dependencies=_AUTH)
def api_scrape(req: ScrapeRequest) -> dict:
    name = _resolve_or_detect(req.url, req.schema_name)
    schema = schema_registry.resolve(name)
    if schema is None:
        raise HTTPException(status_code=400, detail=f"unknown schema '{name}'")
    return scrape_url(req.url, schema).model_dump(mode="json")


@app.post("/api/watch", dependencies=_AUTH)
def api_watch(req: WatchRequest) -> dict:
    name = _resolve_or_detect(req.url, req.schema_name)
    try:
        trigger = TriggerType(req.trigger)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown trigger '{req.trigger}'") from None
    site_id = storage.add_site(
        MonitoredSite(
            url=req.url,
            schema_name=name,
            interval_minutes=req.interval,
            trigger=trigger,
            target_price=req.target_price,
            anomaly_zscore=req.anomaly_zscore,
            anomaly_min_samples=req.anomaly_min_samples,
            retention_runs=req.retention_runs,
        )
    )
    return {"id": site_id, "url": req.url, "schema": name, "trigger": trigger.value}


# ---------------------------------------------------------------------------
# Dashboard actions (form posts -> redirect with a flash message)
# ---------------------------------------------------------------------------


def _flash(ok: str | None = None, err: str | None = None) -> RedirectResponse:
    params = []
    if ok:
        params.append(f"ok={ok}")
    if err:
        params.append(f"err={err}")
    target = "/" + ("?" + "&".join(params) if params else "")
    return RedirectResponse(target, status_code=303)


@app.post("/sites")
def add_watch_action(
    url: str = Form(...),
    schema_name: str = Form(""),
    alert_trigger: str = Form("any_change"),
    target_price: str = Form(""),
    interval: int = Form(60),
) -> RedirectResponse:
    try:
        name = _resolve_or_detect(url, schema_name or None)
        try:
            trigger = TriggerType(alert_trigger)
        except ValueError:
            trigger = TriggerType.ANY_CHANGE
        try:
            target = float(target_price) if target_price.strip() else None
        except ValueError:
            target = None
        storage.add_site(
            MonitoredSite(
                url=url,
                schema_name=name,
                interval_minutes=max(1, interval),
                trigger=trigger,
                target_price=target,
            )
        )
        return _flash(ok=f"Watching+({name})")
    except HTTPException as exc:
        return _flash(err=str(exc.detail).replace(" ", "+"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("add watch failed: %s", exc)
        return _flash(err="Could+not+add+watch")


def _run_site_bg(site_id: int) -> None:
    site = storage.get_site(site_id)
    if not site:
        return
    schema = schema_registry.resolve(site["schema_name"])
    if schema is None:
        return
    try:
        run_once(site_id, schema)
    except Exception as exc:  # pragma: no cover - live scrape failure
        logger.warning("background run for site %s failed: %s", site_id, exc)


@app.post("/sites/{site_id}/run")
def run_site_action(site_id: int, background_tasks: BackgroundTasks) -> RedirectResponse:
    if storage.get_site(site_id) is None:
        return _flash(err="No+such+site")
    background_tasks.add_task(_run_site_bg, site_id)
    return _flash(ok="Check+queued")


@app.post("/sites/{site_id}/pause")
def pause_site_action(site_id: int) -> RedirectResponse:
    storage.set_active(site_id, False)
    return _flash(ok="Paused")


@app.post("/sites/{site_id}/resume")
def resume_site_action(site_id: int) -> RedirectResponse:
    storage.set_active(site_id, True)
    return _flash(ok="Resumed")


@app.post("/sites/{site_id}/delete")
def delete_site_action(site_id: int) -> RedirectResponse:
    storage.delete_site(site_id)
    return _flash(ok="Deleted")


@app.post("/digest/send")
def send_digest_action(hours: int = Form(24)) -> RedirectResponse:
    report = digest_mod.send(hours)
    if report["total"] == 0:
        return _flash(ok="No+changes+to+digest")
    return _flash(ok=f"Digest+sent+({report['total']}+changes)")


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard(ok: str | None = None, err: str | None = None) -> str:
    rows = storage.watchlist()
    changes = storage.recent_changes(limit=25)
    alerts_sent = storage.recent_alert_events(limit=20)
    series_map = storage.all_price_points("price")

    for r in rows:
        vals = series_map.get((r["id"], r.get("item_key")), [])
        r["_spark"] = _sparkline(vals) if len(vals) >= 2 else ""

    digest_24h = digest_mod.build(24)
    confs = [r["confidence"] for r in rows if isinstance(r.get("confidence"), (int, float))]
    stats = {
        "watching": sum(1 for r in rows if r["active"]),
        "total": len(rows),
        "changes_24h": digest_24h["total"],
        "avg_conf": round(sum(confs) / len(confs) * 100) if confs else None,
        "sinks": _configured_sinks(),
    }
    return _render(
        "dashboard.html",
        rows=rows,
        changes=changes,
        alerts_sent=alerts_sent,
        stats=stats,
        schemas=schema_registry.available(),
        triggers=_TRIGGER_LABELS,
        flash=_flash_ctx(ok, err),
    )


@app.get("/sites/{site_id}", response_class=HTMLResponse)
def site_detail(site_id: int) -> HTMLResponse:
    site = storage.get_site(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    records = storage.latest_records(site_id)
    primary = records[0] if records else {}
    series = storage.price_history(site_id, primary.get("item_key"), "price") if records else []
    values = [p["value"] for p in series if isinstance(p["value"], (int, float))]
    changes = storage.recent_changes(site_id, limit=50)
    run = storage.latest_run(site_id)
    insights = storage.price_insights(site_id, primary.get("item_key")) if records else _empty_insights()
    avail = storage.availability_stats(site_id, primary.get("item_key")) if records else {}
    field_sources = _run_field_sources(run)
    return HTMLResponse(
        _render(
            "detail.html",
            site=site,
            records=records,
            changes=changes,
            run=run,
            insights=insights,
            avail=avail,
            field_sources=field_sources,
            chart=_chart(values) if len(values) >= 2 else "",
            points=len(values),
        )
    )


def _run_field_sources(run: dict | None) -> dict:
    """Decode the per-field provenance JSON persisted on a run (empty if absent)."""
    if not run or not run.get("field_sources"):
        return {}
    try:
        parsed = json.loads(run["field_sources"])
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _empty_insights() -> dict:
    return {"count": 0, "low": None, "high": None, "avg": None,
            "current": None, "pct_vs_avg": None, "is_all_time_low": False}


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _configured_sinks() -> list[str]:
    from . import alerts

    return [s for s in alerts.configured_sinks() if s != "console"]


def _flash_ctx(ok: str | None, err: str | None) -> dict | None:
    if ok:
        return {"kind": "ok", "msg": ok.replace("+", " ")}
    if err:
        return {"kind": "err", "msg": err.replace("+", " ")}
    return None


def _render(template: str, **ctx) -> str:
    return _env.get_template(template).render(version=crawlr.__version__, **ctx)


def _sparkline(values: list[float], width: int = 96, height: int = 26) -> str:
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    pts = " ".join(
        f"{(i / (n - 1)) * width:.1f},{height - ((v - lo) / span) * height:.1f}"
        for i, v in enumerate(values)
    )
    up = values[-1] >= values[0]
    color = "var(--green)" if not up else "#c0392b"  # cheaper = green (good)
    return (
        f"<svg class='spark' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>"
        f"<polyline fill='none' stroke='{color}' stroke-width='1.75' "
        f"stroke-linejoin='round' stroke-linecap='round' points='{pts}'/></svg>"
    )


def _chart(values: list[float], width: int = 720, height: int = 220) -> str:
    pad = 24
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    iw, ih = width - pad * 2, height - pad * 2

    def _xy(i: int, v: float) -> tuple[float, float]:
        x = pad + (i / (n - 1)) * iw
        y = pad + ih - ((v - lo) / span) * ih
        return x, y

    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in (_xy(i, v) for i, v in enumerate(values)))
    first_x, _ = _xy(0, values[0])
    last_x, _ = _xy(n - 1, values[-1])
    area = f"{first_x:.1f},{pad + ih:.1f} {line} {last_x:.1f},{pad + ih:.1f}"
    return (
        f"<svg class='chart' viewBox='0 0 {width} {height}' width='100%' height='{height}' "
        f"preserveAspectRatio='none' role='img' aria-label='Price history'>"
        f"<polygon fill='var(--green-050)' points='{area}'/>"
        f"<polyline fill='none' stroke='var(--green)' stroke-width='2.5' "
        f"stroke-linejoin='round' stroke-linecap='round' points='{line}'/>"
        f"<text x='{pad}' y='{pad - 8}' class='c-hi'>{hi:g}</text>"
        f"<text x='{pad}' y='{height - 6}' class='c-lo'>{lo:g}</text></svg>"
    )


# ---------------------------------------------------------------------------
# Templates (Jinja2, autoescaped)
# ---------------------------------------------------------------------------

_BASE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}Crawlr{% endblock %}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --green:#2a6833; --green-strong:#1f4f27; --green-050:#f0f6f1; --green-100:#dfeee3;
    --ink:#0e1a12; --body:#3d4a42; --muted:#6f7d73; --paper:#fff; --line:#e7ede9;
    --radius:18px; --radius-sm:12px; --shadow:0 10px 30px rgba(16,26,18,.08);
    --shadow-sm:0 1px 2px rgba(16,26,18,.06);
    --font:"Geist",-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,sans-serif;
    --mono:"Geist Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  }
  * { box-sizing:border-box; }
  html { background:var(--paper); scroll-behavior:smooth; }
  body { font-family:var(--font); color:var(--body); margin:0; line-height:1.6;
         letter-spacing:-.011em; -webkit-font-smoothing:antialiased; }
  h1,h2,h3 { color:var(--ink); letter-spacing:-.03em; }
  a { color:var(--green); text-decoration:none; } a:hover { color:var(--green-strong); }
  .wrap { max-width:1080px; margin:0 auto; padding:0 1.5rem; }
  nav { position:sticky; top:0; z-index:20; background:rgba(255,255,255,.78);
        backdrop-filter:saturate(180%) blur(18px); -webkit-backdrop-filter:saturate(180%) blur(18px);
        border-bottom:1px solid var(--line); }
  nav .wrap { display:flex; align-items:center; justify-content:space-between; height:62px; }
  .brand { display:inline-flex; align-items:center; gap:.55rem; color:var(--ink); font-weight:700; }
  .brand .mark { width:26px; height:26px; }
  .brand .word { font-size:1.2rem; letter-spacing:-.04em; }
  .nav-meta { color:var(--muted); font-size:.82rem; font-family:var(--mono); }
  .nav-meta .pill { background:var(--green-050); color:var(--green-strong); border-radius:999px;
        padding:.15rem .55rem; margin-left:.4rem; }
  main { padding:2.4rem 0 5rem; }
  .lead { color:var(--muted); margin:.2rem 0 2rem; }
  .btn { display:inline-flex; align-items:center; gap:.35rem; font-family:var(--font);
         font-size:.88rem; font-weight:600; padding:.5rem 1rem; border-radius:999px;
         cursor:pointer; border:1px solid transparent; transition:all .15s ease; white-space:nowrap; }
  .btn-solid { background:var(--green); color:#fff; box-shadow:var(--shadow-sm); }
  .btn-solid:hover { background:var(--green-strong); transform:translateY(-1px); }
  .btn-ghost { background:#fff; color:var(--green); border-color:var(--green-100); }
  .btn-ghost:hover { border-color:var(--green); }
  .btn-mini { padding:.32rem .7rem; font-size:.78rem; }
  .btn-danger { background:#fff; color:#c0392b; border-color:#f0d7d2; }
  .btn-danger:hover { background:#fdf3f1; }
  .grid { display:grid; gap:1rem; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); margin-bottom:2.2rem; }
  .stat { background:#fff; border:1px solid var(--line); border-radius:var(--radius); padding:1.1rem 1.2rem; box-shadow:var(--shadow-sm); }
  .stat .n { font-size:1.9rem; font-weight:700; color:var(--ink); letter-spacing:-.04em; }
  .stat .l { color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; }
  h2.sec { font-size:.82rem; font-weight:600; text-transform:uppercase; letter-spacing:.08em;
           color:var(--muted); margin:2.2rem 0 .8rem; }
  .card { border:1px solid var(--line); border-radius:var(--radius); overflow:hidden; background:#fff; box-shadow:var(--shadow-sm); }
  table { width:100%; border-collapse:collapse; font-size:.92rem; }
  th { text-align:left; font-weight:600; color:var(--muted); font-size:.72rem; text-transform:uppercase;
       letter-spacing:.05em; padding:.8rem 1rem; background:var(--green-050); }
  td { padding:.8rem 1rem; border-top:1px solid var(--line); vertical-align:middle; }
  tbody tr:hover { background:var(--green-050); }
  .title { font-weight:600; color:var(--ink); max-width:320px; }
  .title a { color:var(--ink); } .title a:hover { color:var(--green); }
  .sub { color:var(--muted); font-weight:400; font-size:.76rem; margin-top:.1rem; }
  .num { font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; font-family:var(--mono); }
  .right { text-align:right; } .strong { font-weight:700; color:var(--ink); }
  .was { color:var(--muted); text-decoration:line-through; }
  .up { color:#c0392b; font-weight:600; } .down { color:var(--green); font-weight:600; }
  .dim,.empty { color:var(--muted); } .empty { text-align:center; padding:2.2rem; }
  .pill { display:inline-block; background:var(--green-050); color:var(--green-strong);
          border-radius:999px; padding:.15rem .6rem; font-size:.76rem; font-weight:600; }
  .pill.off { background:#f4f4f4; color:var(--muted); }
  .dot { display:inline-block; width:.55rem; height:.55rem; border-radius:50%;
         border:1.5px solid var(--green); margin-right:.4rem; vertical-align:middle; }
  .dot.filled { background:var(--green); } .dot.out { border-color:#c0392b; }
  .spark { display:block; margin-top:.35rem; }
  .actions { display:flex; gap:.35rem; justify-content:flex-end; }
  form.inline { display:inline; }
  form.add { display:flex; gap:.6rem; flex-wrap:wrap; align-items:center; margin-top:1rem;
             padding:1.1rem; border:1px solid var(--line); border-radius:var(--radius); background:#fff; box-shadow:var(--shadow-sm); }
  input,select { font-family:var(--font); background:#fff; color:var(--ink); border:1px solid var(--line);
          border-radius:10px; padding:.55rem .7rem; font-size:.9rem; }
  input:focus,select:focus { outline:2px solid var(--green); outline-offset:-1px; }
  input[type=url] { flex:1; min-width:240px; } input[type=number] { width:6.5rem; }
  .flash { border-radius:var(--radius-sm); padding:.7rem 1rem; margin-bottom:1.4rem; font-size:.9rem; font-weight:500; }
  .flash.ok { background:var(--green-050); color:var(--green-strong); border:1px solid var(--green-100); }
  .flash.err { background:#fdf3f1; color:#c0392b; border:1px solid #f0d7d2; }
  .chart { display:block; }
  .c-hi,.c-lo { fill:var(--muted); font-family:var(--mono); font-size:12px; }
  .backlink { color:var(--muted); font-size:.86rem; }
</style>
</head>
<body>
  <nav><div class="wrap">
    <a class="brand" href="/">
      <svg class="mark" viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="15" fill="#2a6833"/>
      <path d="M22 12.5a7 7 0 1 0 0 7" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/></svg>
      <span class="word">crawlr</span>
    </a>
    <span class="nav-meta">v{{ version }}<span class="pill">dashboard</span></span>
  </div></nav>
  <main><div class="wrap">
  {% if flash %}<div class="flash {{ flash.kind }}">{{ flash.msg }}</div>{% endif %}
  {% block content %}{% endblock %}
  </div></main>
  <script>
    // Auto-refresh every 30s, but never while the user is typing in a field.
    setInterval(function () {
      var a = document.activeElement;
      if (a && (a.tagName === "INPUT" || a.tagName === "SELECT")) return;
      location.reload();
    }, 30000);
  </script>
</body>
</html>"""

_DASHBOARD = """{% extends "base.html" %}
{% block content %}
  <h1>Watchlist</h1>
  <p class="lead">Competitor price &amp; stock monitoring — self-healing, zero-config.</p>

  <div class="grid">
    <div class="stat"><div class="n">{{ stats.watching }}</div><div class="l">Active watches</div></div>
    <div class="stat"><div class="n">{{ stats.total }}</div><div class="l">Total watched</div></div>
    <div class="stat"><div class="n">{{ stats.changes_24h }}</div><div class="l">Changes · 24h</div></div>
    <div class="stat"><div class="n">{{ stats.avg_conf if stats.avg_conf is not none else "—" }}{% if stats.avg_conf is not none %}%{% endif %}</div><div class="l">Avg confidence</div></div>
  </div>

  <div class="card">
    <table>
      <thead><tr>
        <th>Product</th><th class="num">Current</th><th class="num">Was</th><th class="num">Change</th>
        <th>Stock</th><th class="num">Target</th><th>Status</th><th></th>
      </tr></thead>
      <tbody>
      {% for r in rows %}
        <tr>
          <td class="title"><a href="/sites/{{ r.id }}">{{ r.title or r.url }}</a>
            <div class="sub">{{ r.url }}</div>
            {% if r._spark %}{{ r._spark | safe }}{% endif %}</td>
          <td class="num strong">{{ "%g"|format(r.price) if r.price is number else "—" }}</td>
          <td class="num was">{{ "%g"|format(r.prev_price) if r.prev_price is number else "" }}</td>
          <td class="num">
            {% if r.change_pct is number and r.change_pct < 0 %}<span class="down">&#9660; {{ (r.change_pct)|abs }}%</span>
            {% elif r.change_pct is number and r.change_pct > 0 %}<span class="up">&#9650; {{ r.change_pct }}%</span>
            {% else %}<span class="dim">—</span>{% endif %}
          </td>
          <td>
            {% if r.in_stock is true %}<span class="dot filled"></span>In stock
            {% elif r.in_stock is false %}<span class="dot out"></span>Out
            {% else %}<span class="dim">—</span>{% endif %}
          </td>
          <td class="num">{{ "%g"|format(r.target_price) if r.target_price is number else "—" }}</td>
          <td><span class="pill {% if not r.active %}off{% endif %}">{{ r.status }}</span>{% if r.quality and r.quality != "unknown" %}<div class="sub">{{ r.quality }}</div>{% endif %}</td>
          <td>
            <div class="actions">
              <form class="inline" method="post" action="/sites/{{ r.id }}/run"><button class="btn btn-ghost btn-mini">Check</button></form>
              {% if r.active %}
              <form class="inline" method="post" action="/sites/{{ r.id }}/pause"><button class="btn btn-ghost btn-mini">Pause</button></form>
              {% else %}
              <form class="inline" method="post" action="/sites/{{ r.id }}/resume"><button class="btn btn-solid btn-mini">Resume</button></form>
              {% endif %}
              <form class="inline" method="post" action="/sites/{{ r.id }}/delete" onsubmit="return confirm('Delete this watch and its history?');"><button class="btn btn-danger btn-mini">Delete</button></form>
            </div>
          </td>
        </tr>
      {% else %}
        <tr><td colspan="8" class="empty">Nothing watched yet — add a URL below (schema is auto-detected).</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <form class="add" method="post" action="/sites">
    <input type="url" name="url" placeholder="https://store.example/product/123" required>
    <select name="schema_name" title="Schema">
      <option value="">Auto-detect</option>
      {% for s in schemas %}<option value="{{ s.name }}">{{ s.name }}</option>{% endfor %}
    </select>
    <select name="alert_trigger" title="Alert me when">
      {% for value, label in triggers.items() %}<option value="{{ value }}">{{ label }}</option>{% endfor %}
    </select>
    <input type="number" name="target_price" placeholder="Target" step="0.01" min="0">
    <input type="number" name="interval" value="60" min="1" title="Every N minutes">
    <button class="btn btn-solid" type="submit">Watch</button>
  </form>

  <div style="display:flex; align-items:center; justify-content:space-between;">
    <h2 class="sec">Recent changes &amp; alerts</h2>
    <form class="inline" method="post" action="/digest/send">
      <input type="hidden" name="hours" value="24">
      <button class="btn btn-ghost btn-mini">Send digest{% if stats.sinks %} · {{ stats.sinks|join(", ") }}{% endif %}</button>
    </form>
  </div>
  <div class="card">
    <table>
      <thead><tr><th>When</th><th>Item</th><th>Field</th><th>Old</th><th>New</th></tr></thead>
      <tbody>
      {% for c in changes %}
        <tr>
          <td class="num">{{ c.changed_at[:19]|replace("T"," ") }}</td>
          <td>{{ (c.item_key or "")[:44] }}</td>
          <td>{{ c.field }}</td>
          <td class="num dim">{{ c.old_value }}</td>
          <td class="num strong">{{ c.new_value }}</td>
        </tr>
      {% else %}
        <tr><td colspan="5" class="empty">No changes recorded yet.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <h2 class="sec">Sent alerts</h2>
  <div class="card">
    <table>
      <thead><tr><th>When</th><th>Item</th><th>Field</th><th>Alert</th><th>Channels</th></tr></thead>
      <tbody>
      {% for a in alerts_sent %}
        <tr>
          <td class="num">{{ a.created_at[:19]|replace("T"," ") }}</td>
          <td>{{ (a.item_key or "")[:40] }}</td>
          <td>{{ a.field }}</td>
          <td>{{ a.message }}</td>
          <td class="dim">{{ a.sinks or "—" }}</td>
        </tr>
      {% else %}
        <tr><td colspan="5" class="empty">No alerts dispatched yet.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
{% endblock %}"""

_DETAIL = """{% extends "base.html" %}
{% block title %}{{ site.url }} · Crawlr{% endblock %}
{% block content %}
  <p><a class="backlink" href="/">&larr; Back to watchlist</a></p>
  <h1>{{ (records[0].title if records else site.url) or site.url }}</h1>
  <p class="lead">{{ site.url }}</p>

  <div class="grid">
    <div class="stat"><div class="n">{{ site.schema_name }}</div><div class="l">Schema</div></div>
    <div class="stat"><div class="n">{{ site.interval_minutes }}m</div><div class="l">Interval</div></div>
    <div class="stat"><div class="n">{{ "%d"|format((run.confidence*100)|round) if run else "—" }}{% if run %}%{% endif %}</div><div class="l">Last confidence</div></div>
    <div class="stat"><div class="n">{{ points }}</div><div class="l">Price points</div></div>
  </div>

  {% if insights.count %}
  <div class="grid">
    <div class="stat"><div class="n">{{ "%g"|format(insights.current) if insights.current is not none else "—" }}</div><div class="l">Current</div></div>
    <div class="stat"><div class="n">{{ "%g"|format(insights.low) if insights.low is not none else "—" }}</div><div class="l">All-time low</div></div>
    <div class="stat"><div class="n">{{ "%g"|format(insights.avg) if insights.avg is not none else "—" }}</div><div class="l">Average</div></div>
    <div class="stat"><div class="n">{{ "%g"|format(insights.high) if insights.high is not none else "—" }}</div><div class="l">All-time high</div></div>
  </div>
  <div class="grid">
    <div class="stat"><div class="n">{{ insights.deal_score }}</div><div class="l">Deal score / 100</div></div>
    {% if avail and avail.samples %}
    <div class="stat"><div class="n">{{ avail.in_stock_pct }}%</div><div class="l">In stock (history)</div></div>
    <div class="stat"><div class="n">{{ avail.restocks }}</div><div class="l">Restocks seen</div></div>
    <div class="stat"><div class="n">{{ "Yes" if avail.currently_in_stock else "No" }}</div><div class="l">In stock now</div></div>
    {% endif %}
  </div>
  {% if insights.is_all_time_low %}<div class="flash ok">&#9733; Currently at its lowest recorded price.</div>{% endif %}
  {% endif %}

  <h2 class="sec">Price history</h2>
  <div class="card" style="padding:1rem;">
    {% if chart %}{{ chart | safe }}{% else %}<p class="empty">Not enough data yet — check a few times to build history.</p>{% endif %}
  </div>

  {% if field_sources %}
  <h2 class="sec">Field provenance</h2>
  <div class="card" style="padding:1rem;">
    {% for field, src in field_sources.items() %}
      <span class="pill {% if src in ('none',) %}off{% endif %}" title="Source of the {{ field }} value">{{ field }}: {{ src }}</span>
    {% endfor %}
    <div class="sub" style="margin-top:.6rem;">structured = schema.org data · selector = CSS selector · both = agreed · none = missing</div>
  </div>
  {% endif %}

  <h2 class="sec">Latest extracted records</h2>
  <div class="card">
    <table>
      <thead><tr><th>Item</th><th class="num">Price</th><th>Availability</th></tr></thead>
      <tbody>
      {% for rec in records %}
        <tr>
          <td class="title">{{ rec.title or rec.item_key or "—" }}</td>
          <td class="num strong">{{ "%g"|format(rec.price) if rec.price is number else "—" }}</td>
          <td>{{ rec.availability or "—" }}</td>
        </tr>
      {% else %}
        <tr><td colspan="3" class="empty">No records yet.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <h2 class="sec">Change history</h2>
  <div class="card">
    <table>
      <thead><tr><th>When</th><th>Field</th><th>Old</th><th>New</th></tr></thead>
      <tbody>
      {% for c in changes %}
        <tr><td class="num">{{ c.changed_at[:19]|replace("T"," ") }}</td><td>{{ c.field }}</td>
        <td class="num dim">{{ c.old_value }}</td><td class="num strong">{{ c.new_value }}</td></tr>
      {% else %}
        <tr><td colspan="4" class="empty">No changes recorded yet.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
{% endblock %}"""

_env = Environment(
    loader=DictLoader({"base.html": _BASE, "dashboard.html": _DASHBOARD, "detail.html": _DETAIL}),
    autoescape=select_autoescape(["html", "xml"]),
)
