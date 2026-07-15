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

import json

import typer
from rich.console import Console
from rich.table import Table

from . import schemas as schema_registry
from . import storage, usage
from .config import LLM
from .models import MonitoredSite
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
) -> None:
    """Run all due sites once, or continuously with --daemon."""
    import asyncio

    from .monitor import run_due_async
    from .scheduler import start as start_daemon

    storage.init_db()
    _mode_banner()

    if daemon:
        console.print(
            f"[green]Starting scheduler daemon[/green] (poll={poll}s, concurrency={concurrency}). "
            "Press Ctrl+C to stop."
        )
        try:
            start_daemon(poll_seconds=poll, concurrency=concurrency, force_js=js)
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


if __name__ == "__main__":
    app()
