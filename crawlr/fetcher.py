"""Fetch layer with anti-bot resilience (roadmap item 4).

Defaults to static HTTP and auto-escalates to Playwright for JS-heavy pages.
Resilience features:

  * proxy rotation across a configured pool,
  * robots.txt compliance (opt-out via config),
  * randomized delay jitter on top of per-host rate limiting, and
  * optional rotation of realistic User-Agent strings.
"""

from __future__ import annotations

import itertools
import random
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import ANTIBOT, FETCH


@dataclass
class FetchResult:
    url: str
    html: str
    status_code: int
    rendered_with_js: bool = False
    blocked: bool = False  # True when robots.txt disallowed or the site blocked us
    blocked_reason: str | None = None


# Markers that indicate an anti-bot challenge / block page.
_BLOCK_MARKERS = (
    "captcha",
    "cloudflare",
    "attention required",
    "access denied",
    "verify you are human",
    "cf-browser-verification",
    "just a moment",
)


def detect_block(status_code: int, html: str) -> str | None:
    """Return a reason string if the response looks blocked, else None."""
    if status_code in (401, 403, 429, 503):
        return f"http {status_code}"
    low = (html or "")[:5000].lower()
    if any(marker in low for marker in _BLOCK_MARKERS):
        return "anti-bot challenge"
    return None


# A small pool of realistic desktop User-Agents for optional rotation.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

# Track last-request time per host for polite rate limiting.
_last_request: dict[str, float] = {}
# Cache of parsed robots.txt per host.
_robots: dict[str, RobotFileParser | None] = {}
# Round-robin iterator over configured proxies (or None when none configured).
_proxy_cycle = itertools.cycle(ANTIBOT.proxies) if ANTIBOT.proxies else None


def _next_proxy() -> str | None:
    return next(_proxy_cycle) if _proxy_cycle is not None else None


def _pick_user_agent() -> str:
    if ANTIBOT.rotate_user_agents:
        return random.choice(_USER_AGENTS)
    return FETCH.user_agent


def _respect_rate_limit(url: str) -> None:
    host = urlparse(url).netloc
    last = _last_request.get(host)
    if last is not None:
        elapsed = time.monotonic() - last
        wait = FETCH.min_delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
    # Add randomized jitter to look less robotic.
    if ANTIBOT.jitter_seconds > 0:
        time.sleep(random.uniform(0, ANTIBOT.jitter_seconds))
    _last_request[host] = time.monotonic()


def _robots_allows(url: str) -> bool:
    """Return True if robots.txt permits fetching `url` (fails open on error)."""
    if not ANTIBOT.respect_robots:
        return True
    parsed = urlparse(url)
    host = f"{parsed.scheme}://{parsed.netloc}"
    if host not in _robots:
        rp = RobotFileParser()
        rp.set_url(f"{host}/robots.txt")
        try:
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                resp = client.get(f"{host}/robots.txt")
            if resp.status_code >= 400:
                _robots[host] = None  # no usable robots.txt -> allow
            else:
                rp.parse(resp.text.splitlines())
                _robots[host] = rp
        except Exception:
            _robots[host] = None
    rp = _robots[host]
    if rp is None:
        return True
    return rp.can_fetch(FETCH.user_agent, url)


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
    headers = {"User-Agent": _pick_user_agent(), "Accept": "text/html,application/xhtml+xml"}
    proxy = _next_proxy()
    with httpx.Client(
        headers=headers, timeout=FETCH.timeout_seconds, follow_redirects=True, proxy=proxy
    ) as client:
        resp = client.get(url)
        # Don't retry-storm on auth/rate-limit/forbidden — surface as a block.
        if resp.status_code in (401, 403, 429):
            return FetchResult(
                url=str(resp.url), html=resp.text, status_code=resp.status_code,
                blocked=True, blocked_reason=f"http {resp.status_code}",
            )
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

    proxy = _next_proxy()
    launch_kwargs: dict = {"headless": True}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        try:
            page = browser.new_page(user_agent=_pick_user_agent())
            page.goto(url, timeout=int(FETCH.timeout_seconds * 1000), wait_until="networkidle")
            html = page.content()
            return FetchResult(url=page.url, html=html, status_code=200, rendered_with_js=True)
        finally:
            browser.close()


def fetch(url: str, force_js: bool = False) -> FetchResult:
    """Fetch a URL: honor robots.txt, detect blocks, escalate to JS when needed."""
    if not _robots_allows(url):
        return FetchResult(
            url=url, html="", status_code=0, blocked=True, blocked_reason="robots.txt"
        )

    _respect_rate_limit(url)

    if force_js:
        return _fetch_js(url)

    result = _fetch_static(url)

    # Block detection: a real browser sometimes clears anti-bot challenges.
    reason = result.blocked_reason or detect_block(result.status_code, result.html)
    if reason:
        result.blocked = True
        result.blocked_reason = reason
        try:
            rendered = _fetch_js(url)
            if not detect_block(rendered.status_code, rendered.html):
                return rendered
        except RuntimeError:
            pass
        return result

    if _looks_like_js_shell(result.html):
        try:
            return _fetch_js(url)
        except RuntimeError:
            # Playwright not available; return static result with a note upstream.
            return result
    return result
