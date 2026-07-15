"""Fetch layer: static HTTP by default, optional JS rendering via Playwright.

The engine auto-detects whether a page needs a real browser: if the static
HTML looks like an empty JS shell (little text, heavy script), it escalates to
Playwright when available. This keeps the common case (static HTML) fast and
cheap while still handling JS-heavy sites.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import FETCH


@dataclass
class FetchResult:
    url: str
    html: str
    status_code: int
    rendered_with_js: bool = False


# Track last-request time per host for polite rate limiting.
_last_request: dict[str, float] = {}


def _respect_rate_limit(url: str) -> None:
    host = urlparse(url).netloc
    last = _last_request.get(host)
    if last is not None:
        elapsed = time.monotonic() - last
        wait = FETCH.min_delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
    _last_request[host] = time.monotonic()


def _looks_like_js_shell(html: str) -> bool:
    """Heuristic: is this a client-rendered shell with little real content?"""
    tree = HTMLParser(html)
    body = tree.body
    if body is None:
        return True
    text = (body.text() or "").strip()
    script_count = len(tree.css("script"))
    # Very little visible text but lots of scripts -> likely JS-rendered.
    return len(text) < 200 and script_count >= 3


@retry(
    stop=stop_after_attempt(FETCH.max_retries),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def _fetch_static(url: str) -> FetchResult:
    headers = {"User-Agent": FETCH.user_agent, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(
        headers=headers, timeout=FETCH.timeout_seconds, follow_redirects=True
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return FetchResult(url=str(resp.url), html=resp.text, status_code=resp.status_code)


def _fetch_js(url: str) -> FetchResult:
    """Render with Playwright. Requires the optional `js` extra."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "JS rendering requested but Playwright is not installed. "
            "Install with: pip install 'crawlr[js]' && playwright install chromium"
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=FETCH.user_agent)
            page.goto(url, timeout=int(FETCH.timeout_seconds * 1000), wait_until="networkidle")
            html = page.content()
            return FetchResult(url=page.url, html=html, status_code=200, rendered_with_js=True)
        finally:
            browser.close()


def fetch(url: str, force_js: bool = False) -> FetchResult:
    """Fetch a URL, escalating to JS rendering only when needed."""
    _respect_rate_limit(url)

    if force_js:
        return _fetch_js(url)

    result = _fetch_static(url)
    if _looks_like_js_shell(result.html):
        try:
            return _fetch_js(url)
        except RuntimeError:
            # Playwright not available; return static result with a note upstream.
            return result
    return result
