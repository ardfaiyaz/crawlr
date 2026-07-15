# Crawlr examples

Ready-to-run recipes. Install Crawlr first: `pipx install crawlr` (or `pip install crawlr`).

| File | What it shows |
|------|---------------|
| [`watch_competitors.sh`](./watch_competitors.sh) | Watch several product URLs, run them, and print the watchlist |
| [`quotes.yaml`](./quotes.yaml) | A custom schema (no code) for a non-shop site |
| [`api_client.py`](./api_client.py) | Call the hosted Crawlr API from Python |

## Quick tour

```bash
# Watch a product's price & stock
crawlr watch "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html" --target 60
crawlr watchlist

# Use a built-in vertical preset (jobs / real_estate / news)
crawlr scrape "https://example.com/jobs" --schema jobs

# Use a custom schema (see quotes.yaml)
mkdir -p .crawlr/schemas && cp examples/quotes.yaml .crawlr/schemas/
crawlr scrape "https://quotes.toscrape.com/" --schema quotes

# Health check + verify your alert setup
crawlr doctor
crawlr test-alert
```

## Monitoring in the background

```bash
# Run every due site every 60s, and send a change digest once a day
crawlr monitor --daemon --poll 60 --digest 24
```
