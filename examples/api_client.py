"""Call the hosted Crawlr API from Python.

Start the server first:
    CRAWLR_API_KEY=secret crawlr serve --host 0.0.0.0 --port 8000

Then run:
    python examples/api_client.py
"""

from __future__ import annotations

import os

import httpx

BASE = os.getenv("CRAWLR_API_BASE", "http://127.0.0.1:8000")
API_KEY = os.getenv("CRAWLR_API_KEY", "secret")
HEADERS = {"X-API-Key": API_KEY}


def main() -> None:
    with httpx.Client(base_url=BASE, headers=HEADERS, timeout=60) as client:
        # Start watching a product.
        watch = client.post(
            "/api/watch",
            json={
                "url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
                "schema_name": "product",
                "trigger": "price_below",
                "target_price": 60,
            },
        )
        watch.raise_for_status()
        print("watching:", watch.json())

        # One-off scrape.
        scrape = client.post(
            "/api/scrape",
            json={"url": "https://books.toscrape.com/", "schema_name": "product_list"},
        )
        scrape.raise_for_status()
        result = scrape.json()
        print(f"scraped {len(result['records'])} record(s); confidence {result['confidence']}")

        # Current watchlist.
        print("watchlist:", client.get("/api/watchlist").json())


if __name__ == "__main__":
    main()
