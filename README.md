<p align="center">
  <img src="https://raw.githubusercontent.com/ardfaiyaz/crawlr/main/crawlr-icon-logo.png" alt="crawlr" width="120" />
</p>

<h1 align="center">crawlr</h1>

<p align="center">
  An AI-powered, <strong>self-healing</strong> web scraper for e-commerce price &amp; stock monitoring.
</p>

<p align="center">
  <a href="https://pypi.org/project/crawlr/"><img src="https://img.shields.io/pypi/v/crawlr?color=2a6833" alt="PyPI version" /></a>
  <a href="https://pypi.org/project/crawlr/"><img src="https://img.shields.io/pypi/pyversions/crawlr?color=2a6833" alt="Python versions" /></a>
  <a href="https://github.com/ardfaiyaz/crawlr/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-2a6833" alt="License: MIT" /></a>
  <a href="https://01crawlr.vercel.app/"><img src="https://img.shields.io/badge/website-live-2a6833" alt="Website" /></a>
</p>

<p align="center">
  <a href="https://01crawlr.vercel.app/"><strong>Website</strong></a> &middot;
  <a href="https://pypi.org/project/crawlr/"><strong>PyPI</strong></a> &middot;
  <code>pip install crawlr</code>
</p>

---

Crawlr uses an LLM (or a free offline heuristic) **only to generate and repair CSS selectors**,
then extracts pages deterministically with those cached selectors. When a site changes its layout
and the selectors break, Crawlr detects it and **regenerates them automatically** — so your
monitoring never silently dies.

- **Runs free & offline** — no API key required; add an OpenAI/Anthropic key for higher accuracy.
- **Self-healing** — survives redesigns that break traditional scrapers.
- **Price & stock alerts** — via webhook, Slack, or email, on the trigger you choose.
- **General-purpose** — e-commerce ships in; add new verticals as simple YAML.

## Install

```bash
pipx install crawlr        # or: pip install crawlr
```

## Quickstart

```bash
crawlr watch "https://store.com/product/123" --target 25   # track price + stock
crawlr watchlist                                           # current price, movement, stock
crawlr monitor --daemon                                    # keep checking in the background
crawlr serve                                               # optional local dashboard
```

## Alert triggers

Pick one per watch with `--trigger` (or in the dashboard):

| Trigger | Alerts when |
|---------|-------------|
| `any_change` | any watched field changes |
| `price_drop` | the price goes down |
| `price_below` | price is at/below your target |
| `price_above` | price is at/above your target |
| `back_in_stock` | the item becomes available |
| `out_of_stock` | the item sells out |

For richer logic, run `crawlr init` to create an editable `crawlr.rules.yaml` that maps
circumstances to actions (and overrides per-watch triggers):

```yaml
default_action: ignore
rules:
  - when: price_drops_below
    amount: 25
    action: alert
  - when: back_in_stock
    action: alert
```

## Custom schemas (no code)

Add new verticals by dropping a YAML file into your schema directory:

```yaml
name: jobs
item_selector: ".job-card"
fields:
  - name: title
    description: the job title
    type: text
    required: true
  - name: salary
    description: annual salary
    type: number
```

Then `crawlr scrape <url> --schema jobs`. List schemas with `crawlr schemas`.

## Configuration

Set via environment variables or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `CRAWLR_LLM_PROVIDER` | `none` | `openai`, `anthropic`, or `none` (offline heuristic) |
| `CRAWLR_LLM_API_KEY` | — | API key for the chosen provider |
| `CRAWLR_DATABASE_URL` | — | `postgresql://...` to use Postgres instead of SQLite |
| `CRAWLR_ALERT_WEBHOOK` | — | Webhook URL for change alerts |
| `CRAWLR_ALERT_SLACK` | — | Slack incoming-webhook URL |
| `CRAWLR_PROXIES` | — | Comma-separated proxy URLs to rotate |
| `CRAWLR_RESPECT_ROBOTS` | `true` | Honor robots.txt |

## Examples

Ready-to-run recipes live in [`examples/`](./examples) — watch competitors, use a
custom schema, and call the hosted API from Python.

## Development

```bash
pip install -e '.[dev]'
pytest          # offline test suite
ruff check .    # lint
crawlr eval     # extraction accuracy gate
```

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md). Great first
contributions: new vertical presets, golden eval cases for sites that extract
wrong, and docs/examples.

## Demo

A short GIF is the best intro. Generate one with [VHS](https://github.com/charmbracelet/vhs):
`vhs docs/demo.tape` → `docs/demo.gif` (see [docs/DEMO.md](./docs/DEMO.md)).

## License

MIT
