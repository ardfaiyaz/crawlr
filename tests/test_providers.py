"""Tests for the pluggable remote fetch-provider backend."""

from __future__ import annotations

import httpx
import pytest

from crawlr import fetcher, providers


class _FakeResp:
    def __init__(self, text="<html>ok</html>", status_code=200, json_data=None):
        self.text = text
        self.status_code = status_code
        self._json = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, captured, resp):
        self._captured = captured
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None, headers=None, auth=None):
        self._captured.update(method="GET", url=url, params=params, headers=headers, auth=auth)
        return self._resp

    def post(self, url, json=None, headers=None, auth=None):
        self._captured.update(method="POST", url=url, json=json, headers=headers, auth=auth)
        return self._resp


def _install(monkeypatch, resp):
    captured: dict = {}
    monkeypatch.setattr(providers.httpx, "Client", lambda **kw: _FakeClient(captured, resp))
    return captured


def test_enabled_flag(monkeypatch):
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER", "direct")
    assert providers.enabled() is False
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER", "scraperapi")
    assert providers.enabled() is True


def test_scraperapi_get_builds_params(monkeypatch):
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER", "scraperapi")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_KEY", "KEY")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_RENDER", True)
    cap = _install(monkeypatch, _FakeResp(text="<html>hi</html>"))

    html, status = providers.fetch_html("https://target.test/p")

    assert html == "<html>hi</html>" and status == 200
    assert cap["method"] == "GET"
    assert cap["params"]["url"] == "https://target.test/p"
    assert cap["params"]["api_key"] == "KEY"
    assert cap["params"]["render"] == "true"


def test_render_flag_off_drops_render_param(monkeypatch):
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER", "scraperapi")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_KEY", "KEY")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_RENDER", False)
    cap = _install(monkeypatch, _FakeResp())

    providers.fetch_html("https://target.test/p")
    assert "render" not in cap["params"]


def test_zyte_post_json(monkeypatch):
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER", "zyte")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_KEY", "ZKEY")
    cap = _install(monkeypatch, _FakeResp(json_data={"browserHtml": "<html>z</html>"}))

    html, _ = providers.fetch_html("https://t.test/p")

    assert html == "<html>z</html>"
    assert cap["method"] == "POST"
    assert cap["json"]["url"] == "https://t.test/p"
    assert cap["json"]["browserHtml"] is True
    assert cap["auth"] == ("ZKEY", "")


def test_custom_provider_from_config(monkeypatch):
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER", "custom")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_ENDPOINT", "https://api.x/get")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_METHOD", "GET")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_URL_PARAM", "target")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_KEY_PARAM", "token")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_KEY", "T")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_EXTRA", "geo=us&wait=1")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_RESPONSE", "html")
    cap = _install(monkeypatch, _FakeResp(text="<html>c</html>"))

    html, _ = providers.fetch_html("https://z.test/p")
    assert html == "<html>c</html>"
    assert cap["params"]["target"] == "https://z.test/p"
    assert cap["params"]["token"] == "T"
    assert cap["params"]["geo"] == "us"


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER", "bogus")
    with pytest.raises(RuntimeError):
        providers.fetch_html("https://x.test/p")


def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER", "scraperapi")
    monkeypatch.setattr(providers.config, "FETCH_PROVIDER_KEY", None)
    with pytest.raises(RuntimeError):
        providers.fetch_html("https://x.test/p")


def test_fetch_routes_through_provider(monkeypatch):
    monkeypatch.setattr(fetcher.providers, "enabled", lambda: True)
    monkeypatch.setattr(fetcher.providers, "fetch_html", lambda url: ("<html>provided</html>", 200))
    monkeypatch.setattr(fetcher, "_robots_allows", lambda url: True)
    monkeypatch.setattr(fetcher, "_respect_rate_limit", lambda url: None)

    res = fetcher.fetch("https://hard.test/p")
    assert res.html == "<html>provided</html>"
    assert res.rendered_with_js is True
    assert res.blocked is False


def test_fetch_provider_error_becomes_blocked(monkeypatch):
    monkeypatch.setattr(fetcher.providers, "enabled", lambda: True)

    def boom(url):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(fetcher.providers, "fetch_html", boom)
    monkeypatch.setattr(fetcher, "_robots_allows", lambda url: True)
    monkeypatch.setattr(fetcher, "_respect_rate_limit", lambda url: None)

    res = fetcher.fetch("https://hard.test/p")
    assert res.blocked is True
    assert "provider" in (res.blocked_reason or "")
