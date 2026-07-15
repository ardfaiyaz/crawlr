"""Alerting: notify external sinks when monitored data changes (roadmap item 1).

Sinks (all optional, configured via env): console/log, generic webhook, Slack
incoming webhook, and email (SMTP). A simple rule layer decides which changes
are worth alerting on (e.g. only price drops above a threshold).

Design goals: never raise into the monitor loop (a broken sink must not stop
scraping), and stay dependency-light (httpx + stdlib smtplib).
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

import httpx

from .config import ALERTS
from .models import PriceChange

logger = logging.getLogger("crawlr.alerts")

_PRICE_FIELDS = {"price"}
_BACK_IN_STOCK = {"in stock", "instock", "available", "in_stock"}


def alertable(changes: list[PriceChange]) -> list[PriceChange]:
    """Filter changes down to those worth notifying about, per configured rules."""
    out: list[PriceChange] = []
    for c in changes:
        if c.field in _PRICE_FIELDS and ALERTS.min_price_drop_pct > 0:
            drop = _price_drop_fraction(c.old_value, c.new_value)
            if drop is None or drop < ALERTS.min_price_drop_pct:
                continue
        out.append(c)
    return out


def _price_drop_fraction(old: str | None, new: str | None) -> float | None:
    """Fractional price drop (0.1 == 10% cheaper); None if not computable."""
    try:
        o, n = float(old), float(new)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if o <= 0:
        return None
    return (o - n) / o


def _describe(change: PriceChange) -> str:
    if change.field == "_new_item":
        return f"NEW item: {change.new_value}"
    if change.field == "_removed_item":
        return f"REMOVED item: {change.old_value}"
    prefix = ""
    if change.field in _PRICE_FIELDS:
        drop = _price_drop_fraction(change.old_value, change.new_value)
        if drop is not None:
            direction = "dropped" if drop > 0 else "rose"
            prefix = f"price {direction} {abs(drop) * 100:.1f}% — "
    return f"{prefix}{change.item_key_display()} {change.field}: {change.old_value} -> {change.new_value}"


def notify(site_url: str, changes: list[PriceChange]) -> list[PriceChange]:
    """Send alerts for `changes` to all configured sinks. Returns those sent."""
    to_send = alertable(changes)
    if not to_send:
        return []

    lines = [_describe(c) for c in to_send]
    subject = f"Crawlr: {len(to_send)} change(s) on {site_url}"
    body = subject + "\n\n" + "\n".join(f"- {line}" for line in lines)

    if ALERTS.console:
        logger.info(body)

    payload = {
        "site": site_url,
        "count": len(to_send),
        "changes": [c.model_dump(mode="json") for c in to_send],
    }
    _safe(_send_webhook, payload)
    _safe(_send_slack, subject, lines)
    _safe(_send_email, subject, body)

    return to_send


def send_message(subject: str, lines: list[str], payload_extra: dict | None = None) -> None:
    """Dispatch an arbitrary message (e.g. a digest) to all configured sinks."""
    body = subject + "\n\n" + "\n".join(f"- {line}" for line in lines)
    if ALERTS.console:
        logger.info(body)
    payload = {"subject": subject, "lines": lines}
    if payload_extra:
        payload.update(payload_extra)
    _safe(_send_webhook, payload)
    _safe(_send_slack, subject, lines)
    _safe(_send_email, subject, body)


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------


def _send_webhook(payload: dict) -> None:
    if not ALERTS.webhook_url:
        return
    with httpx.Client(timeout=15) as client:
        client.post(ALERTS.webhook_url, json=payload).raise_for_status()


def _send_slack(subject: str, lines: list[str]) -> None:
    if not ALERTS.slack_webhook_url:
        return
    text = f"*{subject}*\n" + "\n".join(f"• {line}" for line in lines)
    with httpx.Client(timeout=15) as client:
        client.post(ALERTS.slack_webhook_url, json={"text": text}).raise_for_status()


def _send_email(subject: str, body: str) -> None:
    if not (ALERTS.email_to and ALERTS.smtp_host):
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = ALERTS.smtp_from or (ALERTS.smtp_user or "crawlr@localhost")
    msg["To"] = ", ".join(ALERTS.email_to)

    with smtplib.SMTP(ALERTS.smtp_host, ALERTS.smtp_port, timeout=20) as server:
        server.starttls()
        if ALERTS.smtp_user and ALERTS.smtp_password:
            server.login(ALERTS.smtp_user, ALERTS.smtp_password)
        server.sendmail(msg["From"], ALERTS.email_to, msg.as_string())


def _safe(fn, *args) -> None:
    """Run a sink, swallowing errors so one bad sink can't stop monitoring."""
    try:
        fn(*args)
    except Exception as exc:  # pragma: no cover - network/SMTP failure paths
        logger.warning("alert sink %s failed: %s", getattr(fn, "__name__", fn), exc)
