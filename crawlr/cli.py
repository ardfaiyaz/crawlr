"""Command-line interface for Crawlr.

Commands:
  scrape    One-off scrape of a URL against a built-in schema.
  add       Register a site for continuous monitoring.
  sites     List monitored sites.
  run       Run a single monitored site now and show detected changes.
  monitor   Run all due sites (drive this from cron or a loop).
  changes   Show recent detected changes.
  serve     Launch the FastAPI dashboard.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from . import storage
from .config import LLM
from .models import MonitoredSite
from .monitor import run_once
from .verticals import ecommerce

app = typer.Typer(help="Crawlr: AI-powered, self-healing web scraper for price intelligence.")
console = Console()


def _schema(name: str):
    schema = ecommerce.resolve(name)
    if schema is None:
        available = "product, product_list"
        console.print(f"[red]Unknown schema '{name}'. Available: {available}[/red]")
        raise typer.Exit(code=1)
    return schema


def _mode_banner() -> None:
    mode = f"LLM: {LLM.provider}" if LLM.enabled else "LLM: heuristic (offline)"
    console.print(f"[dim]{mode}[/dim]")


@app.command()
def scrape(
    url: str = typer.Argument(..., help="URL to scrape"),
    schema: str = typer.Option("product", help="Schema: product | product_list"),
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
    tags = []
    if result.healed:
        tags.append("[cyan]self-healed[/cyan]")
    tags.append("LLM" if result.used_llm else "heuristic")
    console.print("  ".join(tags))


@app.command()
def add(
    url: str = typer.Argument(..., help="URL to monitor"),
    schema: str = typer.Option("product", help="Schema: product | product_list"),
    interval: int = typer.Option(60, help="Monitoring interval in minutes"),
) -> None:
    """Register a site for continuous monitoring."""
    storage.init_db()
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
    table = Table("ID", "URL", "Schema", "Interval", "Active")
    for r in rows:
        table.add_row(
            str(r["id"]), r["url"], r["schema_name"], f"{r['interval_minutes']}m",
            "yes" if r["active"] else "no",
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
    _print_changes(changes)


@app.command()
def monitor(js: bool = typer.Option(False, help="Force JS rendering")) -> None:
    """Run all active sites whose interval has elapsed (drive from cron)."""
    from .monitor import run_due

    storage.init_db()
    _mode_banner()
    results = run_due(ecommerce.resolve, force_js=js)
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
