"""Pluggable remote fetch backends (unblocking / JS-render APIs).

Big marketplaces block direct requests. Rather than fighting anti-bot ourselves,
we can route a fetch through a third-party rendering/unblocking service that
returns clean HTML (it runs a real browser, rotates residential proxies, and
solves challenges for us). Crawlr keeps doing what it's good at — extraction,
change detection, history, alerts — on the HTML that comes back.

Configure with environment variables:

    CRAWLR_FETCH_PROVIDER=scraperapi        # or scrapingbee | zyte | custom | direct
    CRAWLR_FETCH_PROVIDER_KEY=your-api-key

Built-in presets cover the common "URL in, HTML out" shape. Set ``custom`` to
point at any other service via CRAWLR_FETCH_PROVIDER_ENDPOINT/_METHOD/_URL_PARAM/
_KEY_PARAM/_KEY_HEADER/_EXTRA/_RESPONSE/_HTML_PATH (see config.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl

import httpx

from . import config


@dataclass
class Provider:
    """How to call one remote fetch service."""

    endpoint: str
    method: str = "GET"
    url_param: str = "url"          # query param carrying the target URL (GET)
    key_param: str | None = None    # query param carrying the API key (GET)
    key_header: str | None = None   # header carrying the API key
    key_header_prefix: str = ""     # e.g. "Bearer " for Authorization headers
    basic_auth_key: bool = False    # send the key as HTTP Basic username (Zyte)
    extra: dict = field(default_factory=dict)   # extra static query params
    body: dict = field(default_factory=dict)    # base JSON body (POST providers)
    url_in_body: str | None = None  # key for the target URL in a JSON body (POST)
    response: str = "html"          # "html" (raw body) | "json"
    html_path: str = ""             # dotted path to HTML when response == "json"
    render_keys: tuple[str, ...] = ()  # extra keys that toggle JS rendering


_PRESETS: dict[str, Provider] = {
    # ScraperAPI / ScrapingBee: GET ?api_key=..&url=..(&render*), body is HTML.
    "scraperapi": Provider(
        endpoint="https://api.scraperapi.com/",
        key_param="api_key",
        url_param="url",
        extra={"render": "true"},
        render_keys=("render",),
    ),
    "scrapingbee": Provider(
        endpoint="https://app.scrapingbee.com/api/v1/",
        key_param="api_key",
        url_param="url",
        extra={"render_js": "true"},
        render_keys=("render_js",),
    ),
    # Zyte API: POST JSON with Basic auth (key as username); HTML in "browserHtml".
    "zyte": Provider(
        endpoint="https://api.zyte.com/v1/extract",
        method="POST",
        basic_auth_key=True,
        url_in_body="url",
        body={"browserHtml": True},
        response="json",
        html_path="browserHtml",
    ),
}


def enabled() -> bool:
    """True when a non-direct fetch provider is configured."""
    name = config.FETCH_PROVIDER
    return bool(name) and name != "direct"


def active_name() -> str:
    return config.FETCH_PROVIDER


def _custom_provider() -> Provider:
    if not config.FETCH_PROVIDER_ENDPOINT:
        raise RuntimeError(
            "CRAWLR_FETCH_PROVIDER=custom requires CRAWLR_FETCH_PROVIDER_ENDPOINT"
        )
    extra = dict(parse_qsl(config.FETCH_PROVIDER_EXTRA))
    return Provider(
        endpoint=config.FETCH_PROVIDER_ENDPOINT,
        method=config.FETCH_PROVIDER_METHOD,
        url_param=config.FETCH_PROVIDER_URL_PARAM,
        key_param=config.FETCH_PROVIDER_KEY_PARAM,
        key_header=config.FETCH_PROVIDER_KEY_HEADER,
        extra=extra,
        response=config.FETCH_PROVIDER_RESPONSE,
        html_path=config.FETCH_PROVIDER_HTML_PATH,
    )


def _active_provider() -> Provider:
    name = config.FETCH_PROVIDER
    if name == "custom":
        return _custom_provider()
    preset = _PRESETS.get(name)
    if preset is None:
        raise RuntimeError(
            f"Unknown CRAWLR_FETCH_PROVIDER '{name}'. "
            f"Use one of: direct, custom, {', '.join(sorted(_PRESETS))}"
        )
    return preset


def _dig(data, path: str):
    """Walk a dotted path (e.g. 'a.b') through nested dicts; None if missing."""
    if not path:
        return data
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def fetch_html(url: str) -> tuple[str, int]:
    """Fetch ``url`` through the configured provider. Returns (html, status_code).

    Raises RuntimeError for configuration problems and httpx.HTTPError for
    network/HTTP failures (the caller converts those into a "blocked" result).
    """
    provider = _active_provider()
    key = config.FETCH_PROVIDER_KEY
    if key is None and (provider.key_param or provider.key_header or provider.basic_auth_key):
        raise RuntimeError(
            "CRAWLR_FETCH_PROVIDER is set but CRAWLR_FETCH_PROVIDER_KEY is missing"
        )

    headers: dict[str, str] = {}
    if provider.key_header and key:
        headers[provider.key_header] = f"{provider.key_header_prefix}{key}"
    # httpx's `auth` param type doesn't include None in its stubs; use Any so a
    # "no auth" default type-checks cleanly.
    auth: Any = None
    if provider.basic_auth_key and key:
        auth = (key, "")

    with httpx.Client(timeout=config.FETCH.timeout_seconds, follow_redirects=True) as client:
        if provider.method == "POST":
            body = dict(provider.body)
            if provider.url_in_body:
                body[provider.url_in_body] = url
            resp = client.post(provider.endpoint, json=body, headers=headers, auth=auth)
        else:
            params = {
                k: v
                for k, v in provider.extra.items()
                if config.FETCH_PROVIDER_RENDER or k not in provider.render_keys
            }
            params[provider.url_param] = url
            if provider.key_param and key:
                params[provider.key_param] = key
            resp = client.get(provider.endpoint, params=params, headers=headers, auth=auth)
        resp.raise_for_status()

        if provider.response == "json":
            html = _dig(resp.json(), provider.html_path)
            return (html or ""), resp.status_code
        return resp.text, resp.status_code
