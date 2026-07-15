#!/usr/bin/env bash
# Watch a few competitor products, run them once, and print the watchlist.
# Usage: bash examples/watch_competitors.sh
set -euo pipefail

# Alert only when a price drops to/below the target (change per product).
crawlr watch "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html" --target 60
crawlr watch "https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html" --trigger price_drop
crawlr watch "https://books.toscrape.com/catalogue/soumission_998/index.html" --restock

echo "--- monitored sites ---"
crawlr sites

echo "--- running all due sites now ---"
crawlr monitor

echo "--- watchlist ---"
crawlr watchlist

# To keep it running in the background with a daily digest:
#   crawlr monitor --daemon --poll 60 --digest 24
