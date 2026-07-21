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


def _version_callback(value: bool) -> None:
    if value:
        from . import __version__

        console.print(f"crawlr {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the installed Crawlr version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Crawlr: AI-powered, self-healing web scraper for price intelligence."""


def _schema(name: str):
    schema = schema_registry.resolve(name)
    if schema is None:
        names = ", ".join(s["name"] for s in schema_registry.available())
        console.print(f"[red]Unknown schema '{name}'. Available: {names}[/red]")
        raise typer.Exit(code=1)
    return schema


def _resolve_or_detect(name: str | None, url: str, force_js: bool = False):
    """Return a schema, auto-detecting from the URL when the user omits --schema."""
    if name:
        return _schema(name)
    from . import detect

    detected = detect.detect_schema(url, force_js=force_js)
    console.print(f"[dim]Auto-detected schema:[/dim] [green]{detected}[/green]")
    return _schema(detected)


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
    q_color = {"verified": "green", "high": "green", "inferred": "yellow", "low": "red"}.get(
        result.quality, "dim"
    )
    tags.append(f"quality [{q_color}]{result.quality}[/{q_color}]")
    tags.append("valid" if result.valid else "[red]invalid[/red]")
    u = usage.snapshot()
    if u.calls:
        tags.append(f"LLM spend ~${u.estimated_cost:.4f} ({u.total_tokens} tok)")
    console.print("  ".join(tags))


@app.command()
def scrape(
    url: str = typer.Argument(..., help="URL to scrape"),
    schema: str = typer.Option(None, help="Schema name (omit to auto-detect; see `crawlr schemas`)"),
    js: bool = typer.Option(False, help="Force JS rendering (needs the 'js' extra)"),
    output: str = typer.Option("table", help="Output format: table | json"),
) -> None:
    """One-off scrape of a URL."""
    from .extractor import scrape as do_scrape

    _mode_banner()
    result = do_scrape(url, _resolve_or_detect(schema, url, js), force_js=js)

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
    schema: str = typer.Option(None, help="Schema name (omit to auto-detect; see `crawlr schemas`)"),
    interval: int = typer.Option(60, help="Monitoring interval in minutes"),
) -> None:
    """Register a site for continuous monitoring."""
    storage.init_db()
    resolved = _resolve_or_detect(schema, url)
    site_id = storage.add_site(
        MonitoredSite(url=url, schema_name=resolved.name, interval_minutes=interval)
    )
    console.print(
        f"[green]Added site #{site_id}[/green] {url} (schema={resolved.name}, every {interval}m)"
    )


@app.command()
def watch(
    url: str = typer.Argument(..., help="Product URL to watch"),
    target: float = typer.Option(None, help="Alert when price drops to/below this"),
    restock: bool = typer.Option(False, help="Alert when the item is back in stock"),
    trigger: str = typer.Option(
        None, help="Explicit trigger: any_change|price_drop|price_below|price_above|back_in_stock|out_of_stock"
    ),
    interval: int = typer.Option(60, help="Check interval in minutes"),
    schema: str = typer.Option(None, help="Schema (omit to auto-detect; defaults toward product)"),
    anomaly_zscore: float = typer.Option(
        None, help="Per-site anomaly z-score threshold (0 disables; omit = global default)"
    ),
    anomaly_min_samples: int = typer.Option(
        None, help="Per-site min history samples before the anomaly guard applies"
    ),
    retention_runs: int = typer.Option(
        None, help="Per-site retention: keep at most N recent runs (0 = keep all)"
    ),
) -> None:
    """Watch a product's price and stock (the easy way)."""
    storage.init_db()
    resolved = _resolve_or_detect(schema, url)

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
            schema_name=resolved.name,
            interval_minutes=interval,
            trigger=chosen,
            target_price=target,
            anomaly_zscore=anomaly_zscore,
            anomaly_min_samples=anomaly_min_samples,
            retention_runs=retention_runs,
        )
    )
    extra = f", target ${target}" if target is not None else ""
    console.print(
        f"[green]Watching site #{site_id}[/green] {url} "
        f"(trigger={chosen.value}{extra}, every {interval}m)"
    )
    console.print("[dim]Run `crawlr monitor` (or `--daemon`) to start checking.[/dim]")


@app.command()
def watchlist(as_json: bool = typer.Option(False, "--json", help="Output raw JSON")) -> None:
    """Show the price/stock watchlist."""
    storage.init_db()
    rows = storage.watchlist()
    if as_json:
        print(json.dumps(rows, indent=2, default=str))
        return
    if not rows:
        console.print("[dim]Nothing watched yet. Add one with: crawlr watch <url>[/dim]")
        return
    table = Table("ID", "Product", "Current", "Low", "Change", "Stock", "Target", "Status")
    for r in rows:
        low = _price(r.get("low"))
        if r.get("is_all_time_low") and r.get("low") is not None:
            low = f"[green]{low} \u2605[/green]"
        table.add_row(
            str(r["id"]),
            _fmt(r["title"]),
            _price(r["price"]),
            low,
            _change(r["change_pct"]),
            _stock(r["in_stock"]),
            _price(r["target_price"]),
            r["status"],
        )
    console.print(table)


@app.command()
def unwatch(site_id: int = typer.Argument(..., help="Site ID to remove (see `crawlr sites`)")) -> None:
    """Delete a watch and all of its history."""
    storage.init_db()
    if storage.delete_site(site_id):
        console.print(f"[green]Removed site #{site_id}.[/green]")
    else:
        console.print(f"[red]No site with id {site_id}.[/red]")
        raise typer.Exit(code=1)


@app.command()
def pause(site_id: int = typer.Argument(..., help="Site ID to pause")) -> None:
    """Pause monitoring for a site (keeps its history)."""
    storage.init_db()
    if storage.get_site(site_id) is None:
        console.print(f"[red]No site with id {site_id}.[/red]")
        raise typer.Exit(code=1)
    storage.set_active(site_id, False)
    console.print(f"[yellow]Paused site #{site_id}.[/yellow]")


@app.command()
def resume(site_id: int = typer.Argument(..., help="Site ID to resume")) -> None:
    """Resume monitoring for a paused site."""
    storage.init_db()
    if storage.get_site(site_id) is None:
        console.print(f"[red]No site with id {site_id}.[/red]")
        raise typer.Exit(code=1)
    storage.set_active(site_id, True)
    console.print(f"[green]Resumed site #{site_id}.[/green]")


@app.command()
def compare(
    urls: list[str] = typer.Argument(..., help="Two or more URLs to compare"),
    schema: str = typer.Option(None, help="Schema (omit to auto-detect each URL)"),
    js: bool = typer.Option(False, help="Force JS rendering"),
    to: str = typer.Option(
        None, "--to", help="Convert all prices to this currency (default: CRAWLR_FX_BASE)"
    ),
) -> None:
    """One-shot price comparison across several URLs for the same product.

    Prices in different currencies are converted to a common currency (``--to``,
    or ``CRAWLR_FX_BASE``) so the cheapest option is picked across currencies.
    Conversion uses a pinned offline rate table by default; set
    ``CRAWLR_FX_LIVE=true`` for live rates.
    """
    from . import config, currency
    from .extractor import scrape as do_scrape

    _mode_banner()
    base = (to or config.FX_BASE).upper()
    rates, source = currency.get_rates()
    console.print(f"[dim]Converting to {base} · FX source: {source}[/dim]")

    table = Table(
        "URL", "Title", "Price", "Currency", f"In {base}", "Stock", "Confidence",
        title="Price comparison",
    )
    # (url, native_price, native_ccy, converted_price_or_None)
    priced: list[tuple[str, float, str | None, float | None]] = []
    for url in urls:
        result = do_scrape(url, _resolve_or_detect(schema, url, js), force_js=js)
        rec = result.records[0] if result.records else {}
        price = rec.get("price")
        native_ccy = rec.get("currency")
        converted = None
        if isinstance(price, (int, float)):
            # Assume the base currency when a page omits an explicit currency.
            src_ccy = native_ccy or base
            converted = currency.convert(float(price), src_ccy, base, rates)
            priced.append((url, float(price), native_ccy, converted))
        table.add_row(
            _fmt(url), _fmt(rec.get("title")), _price(price), native_ccy or "-",
            _price(converted), _stock(triggers.is_in_stock(rec.get("availability"))),
            f"{result.confidence:.0%}",
        )
    console.print(table)
    if len(priced) < 2:
        return

    convertible = [(u, p, c, conv) for (u, p, c, conv) in priced if conv is not None]
    unconvertible = [c or "?" for (_, _, c, conv) in priced if conv is None]
    if len(convertible) >= 2:
        best_url, best_native, best_ccy, best_conv = min(convertible, key=lambda x: x[3])
        console.print(
            f"[green]Cheapest:[/green] {best_url} at {best_native:g} "
            f"{best_ccy or base} (= {best_conv:g} {base})"
        )
        if unconvertible:
            console.print(
                f"[yellow]No FX rate for: {', '.join(sorted(set(unconvertible)))} "
                f"— excluded from the cross-currency ranking.[/yellow]"
            )
    else:
        # Not enough convertible prices — fall back to per-currency cheapest.
        console.print("[yellow]Not enough convertible prices — comparing within each currency.[/yellow]")
        by_currency: dict[str, list[tuple[str, float]]] = {}
        for u, p, c, _ in priced:
            by_currency.setdefault(c or "?", []).append((u, p))
        for cur, items in by_currency.items():
            u, p = min(items, key=lambda x: x[1])
            console.print(f"[green]Cheapest ({cur}):[/green] {u} at {p:g}")


@app.command()
def fx(
    amount: float = typer.Option(None, help="Amount to convert (omit to just list rates)"),
    from_ccy: str = typer.Option(None, "--from", help="Source currency code"),
    to_ccy: str = typer.Option(None, "--to", help="Target currency code (default: CRAWLR_FX_BASE)"),
) -> None:
    """Show FX rates, or convert an amount between currencies."""
    from . import config, currency

    rates, source = currency.get_rates()
    target = (to_ccy or config.FX_BASE).upper()

    if amount is not None and from_ccy:
        converted = currency.convert(amount, from_ccy, target, rates)
        if converted is None:
            console.print(f"[red]No FX rate for {from_ccy.upper()} or {target}.[/red]")
            raise typer.Exit(code=1)
        console.print(
            f"[green]{amount:g} {from_ccy.upper()} = {converted:g} {target}[/green] "
            f"[dim](source: {source})[/dim]"
        )
        return

    table = Table("Currency", "Units per 1 USD", title=f"FX rates (source: {source})")
    for code in sorted(rates):
        table.add_row(code, f"{rates[code]:g}")
    console.print(table)


@app.command()
def canvas(
    query: str = typer.Argument(..., help='Product to search for, e.g. "Wooting 60HE"'),
    retailers: str = typer.Option(
        None, help="Comma list to limit search (e.g. amazon,ebay); omit = all known"
    ),
    to: str = typer.Option(
        None, "--to", help="Compare prices in this currency (default: CRAWLR_FX_BASE)"
    ),
    country: str = typer.Option(
        None,
        "--country",
        "--region",
        help="Country for local stores, e.g. ph, sg, us (default: from currency/CRAWLR_COUNTRY)",
    ),
    per_store: int = typer.Option(
        None,
        "--per-store",
        "--limit",
        help="Max listings to show per store (default: CRAWLR_CANVAS_PER_STORE, 6)",
    ),
    sort: str = typer.Option(
        "price",
        "--sort",
        help="Order by: price, price_high, rating, reviews, popular, discount, match",
    ),
    group: bool = typer.Option(
        False, "--group", help="Group the same product across shops to compare prices"
    ),
    watch: bool = typer.Option(
        False, "--watch", help="Track every result as a watch so you get alerted on price drops"
    ),
    target: float = typer.Option(
        None, "--target", help="With --watch: alert when any store's price drops to/below this"
    ),
    watch_trigger: str = typer.Option(
        None, "--trigger", help="With --watch: trigger (price_drop|price_below|any_change|…)"
    ),
    js: bool = typer.Option(False, help="Force JS rendering (auto-used when a page is blocked)"),
) -> None:
    """Find a product across many retailers and compare prices ("canvas").

    You give a product name (not a link); Crawlr searches each retailer, grabs the
    best-matching result + price, converts everything to one currency, and ranks
    them.

    Use --country to search local marketplaces (e.g. --country ph adds Lazada PH,
    Shopee PH, Zalora PH). If omitted, Crawlr auto-detects your country from your
    IP address (cached; disable with CRAWLR_GEO=false), or infers it from your
    currency (e.g. --to PHP). Marketplaces that block bots need a fetch provider —
    see CRAWLR_FETCH_PROVIDER.
    """
    from . import canvas as canvas_mod
    from . import config as cfg

    _mode_banner()
    names = [r for r in retailers.split(",") if r.strip()] if retailers else None
    report = canvas_mod.search(
        query, names, base=to, country=country, force_js=js, per_store=per_store, sort=sort
    )
    hits = report["hits"]
    base = report["base"]
    resolved_country = report.get("country")
    country_source = report.get("country_source")
    _source_note = {
        "flag": "from --country",
        "env": "from CRAWLR_COUNTRY",
        "currency": "from currency",
        "ip": "auto-detected from your IP",
        "currency-default": "default currency",
    }

    ccy_note = " · prices in {}".format(base)
    if report.get("currency_source") == "country":
        ccy_note = f" · prices in {base} (your region's currency)"
    if resolved_country:
        searched = ", ".join(report.get("retailers_searched", [])) or "—"
        note = _source_note.get(country_source or "", "")
        suffix = f" ({note})" if note else ""
        console.print(
            f"[dim]Region: {resolved_country.upper()}{suffix}{ccy_note} · "
            f"searching: {searched}[/dim]"
        )
    else:
        console.print(
            f"[dim]No region set — searching global stores{ccy_note}. Add --country ph "
            "(or --to PHP) to include local marketplaces like Lazada & Shopee.[/dim]"
        )

    blocked = report.get("blocked", [])
    if blocked and cfg.FETCH_PROVIDER == "direct":
        blocked_names = ", ".join(blocked)
        console.print(
            f"[dim]{len(blocked)} store(s) still blocked after automatic JS rendering "
            f"({blocked_names}). For the most reliable results on heavily-protected "
            "marketplaces, set CRAWLR_FETCH_PROVIDER (e.g. scraperapi).[/dim]"
        )
    if not hits:
        console.print(f"[yellow]No matches found for '{query}'.[/yellow]")
        return

    stats = report.get("stats") or {}
    region_label = f" [{resolved_country.upper()}]" if resolved_country else ""

    def _stats_line() -> None:
        if stats:
            console.print(
                f"[dim]{len(hits)} listing(s) across {report.get('shops', 0)} shop(s) · "
                f"{base} {stats['min']:g}–{stats['max']:g} · avg {stats['avg']:g} · "
                f"median {stats['median']:g} · save up to {stats['savings']:g}[/dim]"
            )
        else:
            console.print(
                f"[dim]{len(hits)} listing(s) across {report.get('shops', 0)} shop(s).[/dim]"
            )

    def _best_line() -> None:
        best = next((h for h in hits if h.converted is not None), None)
        if not best:
            return
        if best.all_time_low and best.hist_count >= 3:
            deal = f" [bold green](all-time low across {best.hist_count} checks!)[/bold green]"
        elif best.hist_avg and best.converted < best.hist_avg:
            off = round((best.hist_avg - best.converted) / best.hist_avg * 100)
            deal = f" [green]({off}% below its usual {base} {best.hist_avg:g})[/green]"
        elif best.deal_pct and best.deal_pct > 0:
            deal = f" [green]({best.deal_pct:g}% below median — good time to buy)[/green]"
        else:
            deal = ""
        console.print(
            f"[green]Best deal:[/green] {best.retailer} — {best.title} "
            f"at {base} {best.converted:g}{deal}\n[dim]{best.url}[/dim]"
        )

    # Close the loop: register every result as a tracked watch, so the existing
    # scheduler + alert sinks fire when any store drops. Reuses `crawlr monitor`.
    if watch:
        if target is not None:
            wtrigger = TriggerType.PRICE_BELOW
        elif watch_trigger:
            wtrigger = TriggerType(watch_trigger)
        else:
            wtrigger = TriggerType.PRICE_DROP
        storage.init_db()
        added, seen_urls = 0, set()
        for h in hits[:25]:  # cap so a broad search can't flood the watchlist
            canon = (h.url or "").split("?")[0]
            if not canon or canon in seen_urls:
                continue
            seen_urls.add(canon)
            try:
                storage.add_site(
                    MonitoredSite(
                        url=h.url, schema_name="product",
                        trigger=wtrigger, target_price=target,
                    )
                )
                added += 1
            except Exception:  # skip an unwatchable URL, keep going
                continue
        tgt = f" (alert at/below {base} {target:g})" if target is not None else ""
        console.print(
            f"[green]Now watching {added} listing(s)[/green]{tgt} — "
            "run `crawlr monitor --daemon` to start checking."
        )

    # Grouped view: one table, the same product across shops, cheapest-first.
    if group:
        groups = canvas_mod.group_hits(hits)
        gtable = Table(
            "Product", "Retailer", f"Price ({base})", "Rating", "Match",
            title=f"Canvas: {query}{region_label} — {len(groups)} product(s), {len(hits)} listing(s)",
        )
        for gi, grp in enumerate(groups):
            if gi:
                gtable.add_section()
            label = min(grp, key=lambda h: len(h.title)).title
            for row_i, h in enumerate(grp):
                price_cell = _price(h.converted)
                if h.discount_pct:
                    price_cell += f" [green]-{h.discount_pct}%[/green]"
                badge = " [cyan]✓[/cyan]" if h.official else ""
                gtable.add_row(
                    _fmt(label) if row_i == 0 else "",
                    h.retailer + badge,
                    price_cell,
                    f"{h.rating:.1f}★" if h.rating else "-",
                    f"{h.score:.0%}",
                )
        console.print(gtable)
        _stats_line()
        _best_line()
        return

    def _compact(n: int | None) -> str:
        if not n:
            return "-"
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}m"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)

    table = Table(
        "Retailer", "Product", f"Price ({base})", "Was", "Rating", "Sold", "Match",
        title=f"Canvas: {query}{region_label} (FX: {report['fx_source']})",
    )
    for h in hits:
        price_cell = _price(h.converted)
        if h.discount_pct:
            price_cell += f" [green]-{h.discount_pct}%[/green]"
        badge = " [cyan]✓[/cyan]" if h.official else ""
        rating_cell = f"{h.rating:.1f}★" if h.rating else "-"
        table.add_row(
            h.retailer + badge,
            _fmt(h.title),
            price_cell,
            _price(h.original_price) if h.original_price else "-",
            rating_cell,
            _compact(h.sold),
            f"{h.score:.0%}",
        )
    console.print(table)

    _stats_line()
    _best_line()


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
def sites(as_json: bool = typer.Option(False, "--json", help="Output raw JSON")) -> None:
    """List monitored sites."""
    storage.init_db()
    rows = storage.list_sites()
    if as_json:
        print(json.dumps(rows, indent=2, default=str))
        return
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
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Show recent detected changes."""
    storage.init_db()
    rows = storage.recent_changes(site_id, limit)
    if as_json:
        print(json.dumps(rows, indent=2, default=str))
        return
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
def stats(as_json: bool = typer.Option(False, "--json", help="Output raw JSON")) -> None:
    """Show per-site health: runs, average confidence, self-heals."""
    storage.init_db()
    rows = storage.site_stats()
    if as_json:
        print(json.dumps(rows, indent=2, default=str))
        return
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
def insights(
    site_id: int = typer.Argument(..., help="Site ID (see `crawlr sites`)"),
    field: str = typer.Option("price", help="Field to analyze"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Price-history analytics for a site: all-time low/high, average, deal."""
    storage.init_db()
    site = storage.get_site(site_id)
    if site is None:
        console.print(f"[red]No site with id {site_id}.[/red]")
        raise typer.Exit(code=1)
    records = storage.latest_records(site_id)
    item_key = records[0].get("item_key") if records else None
    ins = storage.price_insights(site_id, item_key, field)
    avail = storage.availability_stats(site_id, item_key)
    if as_json:
        print(json.dumps({**ins, "availability": avail}, indent=2, default=str))
        return
    if not ins["count"]:
        console.print("[dim]No price history yet — check this site a few times first.[/dim]")
        return
    table = Table("Metric", "Value", title=f"{field} insights for {site['url']}")
    table.add_row("Current", _price(ins["current"]))
    table.add_row("All-time low", _price(ins["low"]))
    table.add_row("All-time high", _price(ins["high"]))
    table.add_row("Average", _price(ins["avg"]))
    if ins["pct_vs_avg"] is not None:
        table.add_row("vs average", _change(ins["pct_vs_avg"]))
    table.add_row("Deal score", f"{ins['deal_score']}/100")
    table.add_row("Data points", str(ins["count"]))
    if avail["samples"]:
        table.add_row("In stock (history)", f"{avail['in_stock_pct']}%")
        table.add_row("Restocks seen", str(avail["restocks"]))
    console.print(table)
    if ins["is_all_time_low"]:
        console.print("[green]\u2605 Currently at its lowest recorded price![/green]")


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


@app.command(name="telegram-bot")
def telegram_bot(
    token: str = typer.Option(None, "--token", help="Bot token (default: CRAWLR_TELEGRAM_BOT_TOKEN)"),
) -> None:
    """Run the Telegram price bot: users chat a product name, get a comparison.

    Create a bot with @BotFather, then set CRAWLR_TELEGRAM_BOT_TOKEN (or pass
    --token). Users can also `/watch <product> [target]` to be alerted on drops.
    """
    from . import config, telegram

    tok = token or config.TELEGRAM_BOT_TOKEN
    if not tok:
        console.print(
            "[red]No bot token.[/red] Create one with @BotFather, then set "
            "CRAWLR_TELEGRAM_BOT_TOKEN or pass --token."
        )
        raise typer.Exit(1)
    storage.init_db()
    console.print("[green]Crawlr Telegram bot running.[/green] Press Ctrl+C to stop.")
    try:
        telegram.run(tok)
    except KeyboardInterrupt:
        console.print("\n[dim]Bot stopped.[/dim]")


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
