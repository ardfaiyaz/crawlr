# Contributing to Crawlr

Thanks for your interest! Contributions of all kinds are welcome — bug reports,
docs, new schema presets, and code.

## Development setup

```bash
git clone https://github.com/ardfaiyaz/crawlr.git
cd crawlr
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e '.[dev]'
```

## Before you open a PR

```bash
pytest          # all tests must pass (offline, no keys needed)
ruff check .    # zero lint errors
crawlr eval     # extraction accuracy gate must stay green
```

## Good first contributions

- **New vertical presets** — add a YAML file under `crawlr/presets/` (see `jobs.yaml`).
- **Golden eval cases** — hit a site that extracts wrong? Add a fixture under
  `crawlr/golden/` and an entry in `crawlr/golden/cases.yaml`. This is the best
  way to improve accuracy over time.
- **Docs & examples** — improve the README, `examples/`, or the website in `web/`.

## Guidelines

- Keep changes focused; one concern per PR.
- Add or update tests for behavior changes.
- Match the existing style (ruff enforces it; line length 100).
- Be mindful of the mission: respect `robots.txt` and site terms of service.

## Reporting bugs

Open an issue with steps to reproduce, the command you ran, and the output of
`crawlr doctor`. For extraction problems, a sample URL (or the archived snapshot
from `crawlr replay`) helps a lot.
