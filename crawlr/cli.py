"""Command-line interface for Crawlr.

Commands:
  scrape           One-off scrape of a URL against a schema.
  add              Register a site for continuous monitoring.
  sites            List monitored sites.
  run              Run a single monitored site now and show detected changes.
  monitor          Run all due sites once, or as a daemon (--daemon).
  changes          Show recent detected changes.
  schemas          List available extraction schemas (built-in + user).
  validate-schema  Validate a user-defined YAML/JSON schema file.
  serve            Launch the FastAPI dashboard.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import schemas as schema_registry
from . import storage, triggers, usage
from .config import LLM
from .models import MonitoredSite, TriggerType
from .monitor import run_once

app = typer.Typer(help="Crawlr: AI-powered, self-healing web scraper for price intelligence.")
console = Console()


def _schema(name: str):
    schema = schema_registry.resolve(name)
    if schema is None:
        names = ", ".join(s["name"] for s in schema_registry.available())
        console.print(f"[red]Unknown schema '{name}'. Available: {names}[/red]")
        raise typer.Exit(code=1)
    return schema


def _mode_banner() -> None:
    mode = f"LLM: {LLM.provider} ({LLM.model or 'default'})" if LLM.enabled else "LLM: heuristic (offline)"
    console.print(f"[dim]{mode}[/dim]")


def _print_quality(result) -> None:
    tags = []
    if result.healed:
        tags.append("[cyan]self-healed[/cyan]")
    tags.append("LLM" if result.used_llm else "heuristic")
    conf_color = "green" if result.confidence >= 0.8 else "yellow" if result.confidence >= 0.4 else "red"
    tags.append(f"confidence [{conf_color}]{result.confidence:.0%}[/{conf_color}]")
    tags.append("valid" if result.valid else "[red]invalid[/red]")
    u = usage.snapshot()
    if u.calls:
        tags.append(f"LLM spend ~${u.estimated_cost:.4f} ({u.total_tokens} tok)")
    console.print("  ".join(tags))


@app.command()
def scrape(
    url: str = typer.Argument(..., help="URL to scrape"),
    schema: str = typer.Option("product", help="Schema name (see `crawlr schemas`)"),
    js: bool = typer.Option(False, help="Force JS rendering (needs the 'js' extra)"),
    output: str = typer.Option("table", help="Output format: table | json"),
) -> None:
    """One-off scrape of a URL."""
    from .extractor import scrape as do_scrape

    _mode_banner()
    result = do_scrape(url, _schema(schema), force_js=js)

    for w in result.warnings:
        console.print(f"[yellow]! {w}[/yellow]")

    if output == "json":
        console.print_json(json.dumps(result.model_dump(mode="json")))
        return

    _print_records(result.records, title=f"{result.count} record(s) from {url}")
    _print_quality(result)


@app.command()
def add(
    url: str = typer.Argument(..., help="URL to monitor"),
    schema: str = typer.Option("product", help="Schema name (see `crawlr schemas`)"),
    interval: int = typer.Option(60, help="Monitoring interval in minutes"),
) -> None:
    """Register a site for continuous monitoring."""
    storage.init_db()
    _schema(schema)  # validate the schema name up front
    site_id = storage.add_site(
        MonitoredSite(url=url, schema_name=schema, interval_minutes=interval)
    )
    console.print(f"[green]Added site #{site_id}[/green] {url} (schema={schema}, every {interval}m)")


@app.command()
def watch(
    url: str = typer.Argument(..., help="Product URL to watch"),
    target: float = typer.Option(None, help="Alert when price drops to/below this"),
    restock: bool = typer.Option(False, help="Alert when the item is back in stock"),
    trigger: str = typer.Option(
        None, help="Explicit trigger: any_change|price_drop|price_below|price_above|back_in_stock|out_of_stock"
    ),
    interval: int = typer.Option(60, help="Check interval in minutes"),
    schema: str = typer.Option("product", help="Schema (defaults to product: price + stock)"),
) -> None:
    """Watch a product's price and stock (the easy way)."""
    storage.init_db()
    _schema(schema)

    # Resolve the trigger from the friendly flags.
    if trigger:
        chosen = TriggerType(trigger)
    elif restock:
        chosen = TriggerType.BACK_IN_STOCK
    elif target is not None:
        chosen = TriggerType.PRICE_BELOW
    else:
        chosen = TriggerType.ANY_CHANGE

    site_id = storage.add_site(
        MonitoredSite(
            url=url,
            schema_name=schema,
            interval_minutes=interval,
            trigger=chosen,
            target_price=target,
        )
    )
    extra = f", target ${target}" if target is not None else ""
    console.print(
        f"[green]Watching site #{site_id}[/green] {url} "
        f"(trigger={chosen.value}{extra}, every {interval}m)"
    )
    console.print("[dim]Run `crawlr monitor` (or `--daemon`) to start checking.[/dim]")


@app.command()
def watchlist() -> None:
    """Show the price/stock watchlist."""
    storage.init_db()
    rows = storage.watchlist()
    if not rows:
        console.print("[dim]Nothing watched yet. Add one with: crawlr watch <url>[/dim]")
        return
    table = Table("ID", "Product", "Current", "Was", "Change", "Stock", "Target", "Status")
    for r in rows:
        table.add_row(
            str(r["id"]),
            _fmt(r["title"]),
            _price(r["price"]),
            _price(r["prev_price"]),
            _change(r["change_pct"]),
            _stock(r["in_stock"]),
            _price(r["target_price"]),
            r["status"],
        )
    console.print(table)


@app.command()
def init(force: bool = typer.Option(False, help="Overwrite an existing rules file")) -> None:
    """Create a starter rules template (crawlr.rules.yaml)."""
    written, message = triggers.write_template(overwrite=force)
    if written:
        console.print(f"[green]Created rules template:[/green] {message}")
        console.print("[dim]Edit it to control what happens in different circumstances.[/dim]")
    else:
        console.print(f"[yellow]{message}[/yellow]")


@app.command()
def sites() -> None:
    """List monitored sites."""
    storage.init_db()
    rows = storage.list_sites()
    if not rows:
        console.print("[dim]No sites yet. Add one with: crawlr add <url>[/dim]")
        return
    table = Table("ID", "URL", "Schema", "Interval", "Active", "Last confidence")
    for r in rows:
        run = storage.latest_run(r["id"])
        conf = f"{run['confidence']:.0%}" if run else "-"
        table.add_row(
            str(r["id"]), r["url"], r["schema_name"], f"{r['interval_minutes']}m",
            "yes" if r["active"] else "no", conf,
        )
    console.print(table)


@app.command()
def run(
    site_id: int = typer.Argument(..., help="Site ID (see `crawlr sites`)"),
    js: bool = typer.Option(False, help="Force JS rendering"),
) -> None:
    """Run a single monitored site now and show detected changes."""
    storage.init_db()
    site = storage.get_site(site_id)
    if site is None:
        console.print(f"[red]No site with id {site_id}[/red]")
        raise typer.Exit(code=1)

    _mode_banner()
    result, changes = run_once(site_id, _schema(site["schema_name"]), force_js=js)
    _print_records(result.records, title=f"{result.count} record(s) from {site['url']}")
    _print_quality(result)
    _print_changes(changes)


@app.command()
def monitor(
    js: bool = typer.Option(False, help="Force JS rendering"),
    daemon: bool = typer.Option(False, help="Run continuously as a scheduler daemon"),
    poll: int = typer.Option(60, help="Daemon poll interval in seconds"),
    concurrency: int = typer.Option(5, help="Max sites scraped in parallel"),
    digest: float = typer.Option(0, help="Daemon: send a change digest every N hours (0=off)"),
) -> None:
    """Run all due sites once, or continuously with --daemon."""
    import asyncio

    from .monitor import run_due_async
    from .scheduler import start as start_daemon

    storage.init_db()
    _mode_banner()

    if daemon:
        digest_note = f", digest every {digest}h" if digest else ""
        console.print(
            f"[green]Starting scheduler daemon[/green] (poll={poll}s, "
            f"concurrency={concurrency}{digest_note}). Press Ctrl+C to stop."
        )
        try:
            start_daemon(
                poll_seconds=poll, concurrency=concurrency, force_js=js, digest_every_hours=digest
            )
        except KeyboardInterrupt:
            console.print("\n[dim]Daemon stopped.[/dim]")
        return

    results = asyncio.run(
        run_due_async(schema_registry.resolve, force_js=js, concurrency=concurrency)
    )
    if not results:
        console.print("[dim]No sites due for a run.[/dim]")
        return
    total = sum(len(c) for c in results.values())
    console.print(f"[green]Ran {len(results)} site(s), {total} change(s) detected.[/green]")
    for site_id, changes in results.items():
        if changes:
            console.print(f"\n[bold]Site #{site_id}[/bold]")
            _print_changes(changes)


@app.command()
def changes(
    site_id: int = typer.Option(None, help="Filter by site ID"),
    limit: int = typer.Option(20, help="Max rows"),
) -> None:
    """Show recent detected changes."""
    storage.init_db()
    rows = storage.recent_changes(site_id, limit)
    if not rows:
        console.print("[dim]No changes recorded yet.[/dim]")
        return
    table = Table("When", "Site", "Item", "Field", "Old", "New")
    for r in rows:
        table.add_row(
            r["changed_at"][:19], r["site_url"], (r["item_key"] or "")[:40],
            r["field"], str(r["old_value"]), str(r["new_value"]),
        )
    console.print(table)


@app.command()
def schemas() -> None:
    """List available extraction schemas (built-in + user-defined)."""
    table = Table("Schema", "Source")
    for s in schema_registry.available():
        table.add_row(s["name"], s["source"])
    console.print(table)


@app.command(name="validate-schema")
def validate_schema(path: str = typer.Argument(..., help="Path to a YAML/JSON schema file")) -> None:
    """Validate a user-defined schema file."""
    ok, message = schema_registry.validate_file(path)
    color = "green" if ok else "red"
    console.print(f"[{color}]{message}[/{color}]")
    if not ok:
        raise typer.Exit(code=1)


@app.command()
def digest(
    hours: int = typer.Option(24, help="Look-back window in hours"),
    send: bool = typer.Option(False, help="Also dispatch to configured alert sinks"),
) -> None:
    """Summarize everything that changed across all watches over a window."""
    storage.init_db()
    from . import digest as digest_mod

    report = digest_mod.build(hours)
    if report["total"] == 0:
        console.print(f"[dim]No changes in the last {hours}h.[/dim]")
        return
    console.print(f"[bold]{digest_mod.subject_for(report)}[/bold]\n")
    for line in digest_mod.summarize_lines(report):
        console.print(line if line.startswith("    ") else f"[green]{line}[/green]")
    if send:
        digest_mod.send(hours)
        console.print("\n[green]Digest dispatched to configured alert sinks.[/green]")


@app.command()
def stats() -> None:
    """Show per-site health: runs, average confidence, self-heals."""
    storage.init_db()
    rows = storage.site_stats()
    if not rows:
        console.print("[dim]No sites yet.[/dim]")
        return
    table = Table("ID", "URL", "Runs", "Avg confidence", "Self-heals", "LLM runs")
    for r in rows:
        avg = f"{r['avg_confidence']:.0%}" if r.get("avg_confidence") is not None else "-"
        table.add_row(
            str(r["id"]), _fmt(r["url"]), str(r["runs"] or 0), avg,
            str(r["heals"] or 0), str(r["llm_runs"] or 0),
        )
    console.print(table)


@app.command()
def export(
    fmt: str = typer.Option("json", "--format", help="json | csv"),
    out: str = typer.Option(None, help="Write to this file instead of stdout"),
    site_id: int = typer.Option(None, "--site", help="Only export this site id"),
) -> None:
    """Export watchlist data (price/stock) as JSON or CSV."""
    storage.init_db()
    rows = storage.watchlist()
    if site_id is not None:
        rows = [r for r in rows if r["id"] == site_id]
    if fmt == "csv":
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        text = buf.getvalue()
    else:
        text = json.dumps(rows, indent=2, default=str)
    if out:
        Path(out).write_text(text)
        console.print(f"[green]Wrote {len(rows)} row(s) to {out}[/green]")
    else:
        print(text)


@app.command()
def replay(
    url: str = typer.Argument(..., help="URL whose archived snapshot to re-extract"),
    schema: str = typer.Option("product", help="Schema name"),
) -> None:
    """Re-extract from the last archived HTML snapshot (no network)."""
    from . import archive
    from .extractor import reextract

    html = archive.load_latest(url, schema)
    if not html:
        console.print(f"[red]No snapshot for {url} (schema={schema}). Scrape it first.[/red]")
        raise typer.Exit(code=1)
    result = reextract(url, _schema(schema), html)
    _print_records(result.records, title=f"{result.count} record(s) from snapshot")
    _print_quality(result)


@app.command(name="eval")
def eval_cmd(min: float = typer.Option(0.9, help="Minimum accuracy to pass")) -> None:
    """Run the golden-fixture accuracy evaluation (regression gate)."""
    from .eval import run_eval

    r = run_eval()
    color = "green" if r["accuracy"] >= min else "red"
    console.print(
        f"[{color}]Accuracy {r['accuracy']:.0%}[/{color}] "
        f"({r['passed']}/{r['checks']} checks across {r['cases']} case(s))"
    )
    for f in r["failures"]:
        console.print(
            f"  [red]x[/red] {f['case']} :: {f['field']}: "
            f"expected {f['expected']!r}, got {f['got']!r}"
        )
    if r["accuracy"] < min:
        raise typer.Exit(code=1)


@app.command()
def doctor() -> None:
    """Run environment health checks (config, DB, schemas, LLM, alerts)."""
    from . import doctor as doctor_mod

    checks = doctor_mod.run_checks()
    icons = {"ok": "[green]OK[/green]", "warn": "[yellow]WARN[/yellow]", "fail": "[red]FAIL[/red]"}
    table = Table("Status", "Check", "Detail")
    for c in checks:
        table.add_row(icons.get(c.status, c.status), c.name, c.detail)
    console.print(table)
    if doctor_mod.has_failures(checks):
        console.print("[red]Some checks failed.[/red]")
        raise typer.Exit(code=1)
    console.print("[green]All good.[/green]")


@app.command(name="test-alert")
def test_alert() -> None:
    """Send a test alert to all configured sinks (verify your setup)."""
    from . import alerts

    sinks = alerts.configured_sinks()
    console.print("Configured sinks: " + (", ".join(sinks) if sinks else "[yellow]none[/yellow]"))
    alerts.send_message("Crawlr test alert", ["If you can read this, your alert sinks work."])
    console.print("[green]Test alert dispatched.[/green]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
) -> None:
    """Launch the FastAPI dashboard."""
    import uvicorn

    storage.init_db()
    console.print(f"[green]Dashboard at http://{host}:{port}[/green]")
    uvicorn.run("crawlr.api:app", host=host, port=port, reload=False)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _print_records(records: list[dict], title: str) -> None:
    if not records:
        console.print("[yellow]No records extracted.[/yellow]")
        return
    columns = list(records[0].keys())
    table = Table(*columns, title=title)
    for rec in records[:50]:
        table.add_row(*[_fmt(rec.get(c)) for c in columns])
    console.print(table)


def _print_changes(changes) -> None:
    if not changes:
        console.print("[dim]No changes since last run.[/dim]")
        return
    table = Table("Item", "Field", "Old", "New", title="Detected changes")
    for c in changes:
        table.add_row(
            (c.product_url or "")[:40], c.field, str(c.old_value), str(c.new_value)
        )
    console.print(table)


def _fmt(value) -> str:
    if value is None:
        return "[dim]-[/dim]"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _price(value) -> str:
    if value is None:
        return "[dim]-[/dim]"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value)


def _change(pct) -> str:
    if pct is None:
        return "[dim]-[/dim]"
    if pct < 0:
        return f"[green]v {abs(pct)}%[/green]"
    if pct > 0:
        return f"[red]^ {pct}%[/red]"
    return "0%"


def _stock(in_stock) -> str:
    if in_stock is True:
        return "[green]yes[/green]"
    if in_stock is False:
        return "[red]no[/red]"
    return "[dim]?[/dim]"


if __name__ == "__main__":
    app()
