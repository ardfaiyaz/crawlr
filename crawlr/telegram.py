"""Telegram bot front-end for canvas — the distribution layer.

Most shoppers will never ``pip install`` anything, but everyone has a messaging
app. This turns crawlr into a chat bot: send a product name, get a live
cross-store price comparison; ``/watch`` it to be alerted when the price drops.

It talks to the Telegram Bot API directly over httpx (no extra dependency) using
long polling, so ``crawlr telegram-bot`` runs anywhere with just a bot token
(``CRAWLR_TELEGRAM_BOT_TOKEN`` from @BotFather).

The message-building and command handling are pure functions so they can be
tested offline; only :func:`run` touches the network.
"""

from __future__ import annotations

import html
import logging
import re

import httpx

from . import canvas, config
from .models import MonitoredSite, TriggerType

logger = logging.getLogger("crawlr.telegram")

_API = "https://api.telegram.org/bot{token}/{method}"
_MAX_LEN = 3800  # Telegram hard-limits messages at 4096 chars; leave headroom.

HELP = (
    "🛒 <b>Crawlr price bot</b>\n\n"
    "Send me a product name and I'll compare prices across shops.\n\n"
    "<b>Commands</b>\n"
    "• <code>&lt;product&gt;</code> — compare prices (e.g. <i>logitech g pro x superlight</i>)\n"
    "• <code>/watch &lt;product&gt; [target]</code> — track it and get alerted on a drop\n"
    "• <code>/help</code> — this message"
)


def _esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


def _money(value: float | None, currency: str) -> str:
    if value is None:
        return "?"
    return f"{currency} {value:,.0f}" if value >= 100 else f"{currency} {value:,.2f}"


def _deal_note(hit: object, currency: str) -> str:
    """A short human note about how good a listing's price is."""
    if getattr(hit, "all_time_low", False) and getattr(hit, "hist_count", 0) >= 3:
        return " 🔥 <b>all-time low</b>"
    avg = getattr(hit, "hist_avg", None)
    conv = getattr(hit, "converted", None)
    if avg and conv is not None and conv < avg:
        off = round((avg - conv) / avg * 100)
        if off >= 1:
            return f" ✅ {off}% below its usual {_money(avg, currency)}"
    dp = getattr(hit, "deal_pct", None)
    if dp and dp > 0:
        return f" ({dp:g}% below median)"
    return ""


def format_results(query: str, report: dict, limit: int = 8) -> str:
    """Render a canvas report as an HTML Telegram message."""
    hits = report.get("hits") or []
    base = report.get("base", "")
    if not hits:
        blocked = report.get("blocked") or []
        extra = (
            f"\n\n{len(blocked)} shop(s) blocked automated access."
            if blocked else ""
        )
        return f"😕 No results found for <b>{_esc(query)}</b>.{extra}"

    shops = report.get("shops", 0)
    lines = [f"🔎 <b>{_esc(query)}</b> — {len(hits)} listing(s) across {shops} shop(s)"]

    best = next((h for h in hits if h.converted is not None), None)
    if best is not None:
        lines.append(
            f"\n💰 <b>Best:</b> {_esc(best.retailer)} — "
            f"{_money(best.converted, base)}{_deal_note(best, base)}\n"
            f'<a href="{_esc(best.url)}">open</a>'
        )

    lines.append("")
    for i, h in enumerate(hits[:limit], 1):
        price = _money(h.converted, base)
        disc = f" (-{h.discount_pct}%)" if getattr(h, "discount_pct", None) else ""
        rating = f" ⭐{h.rating:.1f}" if getattr(h, "rating", None) else ""
        lines.append(
            f"{i}. <b>{price}</b>{disc} · {_esc(h.retailer)}{rating}\n"
            f'   <a href="{_esc(h.url)}">{_esc(h.title[:70])}</a>'
        )

    stats = report.get("stats") or {}
    if stats:
        lines.append(
            f"\n📊 {base} {stats['min']:g}–{stats['max']:g} · "
            f"median {stats['median']:g} · save up to {stats['savings']:g}"
        )
    msg = "\n".join(lines)
    return msg[:_MAX_LEN]


def _parse_watch(args: str) -> tuple[str, float | None]:
    """Split '<query> [target]' — a trailing number is treated as the target."""
    parts = args.rsplit(" ", 1)
    if len(parts) == 2:
        cleaned = parts[1].replace(",", "").replace("₱", "").replace("$", "")
        if re.fullmatch(r"\d+(\.\d+)?", cleaned):
            return parts[0].strip(), float(cleaned)
    return args.strip(), None


def _register_watches(hits: list, target: float | None) -> int:
    from . import storage

    trigger = TriggerType.PRICE_BELOW if target is not None else TriggerType.PRICE_DROP
    try:
        storage.init_db()
    except Exception:
        return 0
    added, seen = 0, set()
    for h in hits[:25]:
        canon = (h.url or "").split("?")[0]
        if not canon or canon in seen:
            continue
        seen.add(canon)
        try:
            storage.add_site(
                MonitoredSite(
                    url=h.url, schema_name="product", trigger=trigger, target_price=target
                )
            )
            added += 1
        except Exception:
            continue
    return added


def handle_text(text: str) -> str:
    """Turn an incoming message into a reply (pure aside from canvas/storage)."""
    text = (text or "").strip()
    if not text:
        return HELP
    lower = text.lower()
    if lower in ("/start", "/help", "start", "help"):
        return HELP

    if lower.startswith("/watch"):
        query, target = _parse_watch(text[len("/watch"):].strip())
        if not query:
            return "Usage: <code>/watch &lt;product&gt; [target price]</code>"
        report = canvas.search(query)
        hits = report.get("hits") or []
        if not hits:
            return f"😕 Couldn't find <b>{_esc(query)}</b> to watch."
        added = _register_watches(hits, target)
        tgt = f" and alert at/below {report.get('base','')} {target:g}" if target else ""
        return (
            f"👀 Now watching <b>{added}</b> listing(s) for <b>{_esc(query)}</b>{tgt}.\n"
            "You'll be alerted on a drop (run <code>crawlr monitor --daemon</code>)."
        )

    query = text[len("/search"):].strip() if lower.startswith("/search") else text
    if not query:
        return HELP
    report = canvas.search(query)
    return format_results(query, report)


# ---------------------------------------------------------------------------
# Network layer (Telegram Bot API over httpx long-polling)
# ---------------------------------------------------------------------------


def send_message(token: str, chat_id: int | str, text: str) -> None:
    try:
        httpx.post(
            _API.format(token=token, method="sendMessage"),
            json={
                "chat_id": chat_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20.0,
        )
    except httpx.HTTPError as exc:  # pragma: no cover - network
        logger.warning("Telegram sendMessage failed: %s", exc)


def get_updates(token: str, offset: int, timeout: int = 30) -> list[dict]:
    resp = httpx.get(
        _API.format(token=token, method="getUpdates"),
        params={"offset": offset, "timeout": timeout},
        timeout=timeout + 10,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def run(token: str | None = None) -> None:  # pragma: no cover - long-running loop
    """Long-poll Telegram and reply to messages until interrupted."""
    token = token or config.TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError(
            "No Telegram bot token. Create one with @BotFather and set "
            "CRAWLR_TELEGRAM_BOT_TOKEN (or pass --token)."
        )
    logger.info("Crawlr Telegram bot started; polling for messages…")
    offset = 0
    while True:
        try:
            updates = get_updates(token, offset)
        except httpx.HTTPError as exc:
            logger.warning("getUpdates failed: %s; retrying…", exc)
            continue
        for update in updates:
            offset = max(offset, update.get("update_id", 0) + 1)
            message = update.get("message") or update.get("edited_message") or {}
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            text = message.get("text")
            if chat_id is None or not text:
                continue
            try:
                reply = handle_text(text)
            except Exception as exc:
                logger.warning("handler error: %s", exc)
                reply = "⚠️ Something went wrong handling that. Try again."
            send_message(token, chat_id, reply)
