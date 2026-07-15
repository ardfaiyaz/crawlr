"""Built-in scheduler daemon.

A lightweight polling loop that runs every monitored site whose interval has
elapsed (via the concurrent async runner) and, optionally, dispatches a change
digest on a cadence. Removes the need for external cron: `crawlr monitor --daemon`.
"""

from __future__ import annotations

import asyncio
import logging
import time

from . import digest, monitor, schemas

logger = logging.getLogger("crawlr.scheduler")


def _digest_due(last_ts: float, every_hours: float, now: float) -> bool:
    """Whether a digest should be sent given the last-send time and cadence."""
    if every_hours <= 0:
        return False
    return (now - last_ts) >= every_hours * 3600


async def run_forever(
    poll_seconds: int = 60,
    concurrency: int = 5,
    force_js: bool = False,
    digest_every_hours: float = 0,
    max_iterations: int | None = None,
) -> int:
    """Poll for due sites (and optionally send digests) until stopped.

    `max_iterations` bounds the loop (used by tests); None means run forever.
    Returns the number of poll iterations completed.
    """
    iterations = 0
    last_digest = time.monotonic()
    while max_iterations is None or iterations < max_iterations:
        try:
            results = await monitor.run_due_async(
                schemas.resolve, concurrency=concurrency, force_js=force_js
            )
            ran = len(results)
            total_changes = sum(len(c) for c in results.values())
            if ran:
                logger.info("scheduler: ran %d site(s), %d change(s)", ran, total_changes)
        except Exception as exc:  # pragma: no cover - defensive; keep the loop alive
            logger.warning("scheduler iteration failed: %s", exc)

        now = time.monotonic()
        if _digest_due(last_digest, digest_every_hours, now):
            try:
                report = digest.send(int(digest_every_hours))
                logger.info("scheduler: sent digest (%d change(s))", report.get("total", 0))
            except Exception as exc:  # pragma: no cover
                logger.warning("digest dispatch failed: %s", exc)
            last_digest = now

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        await asyncio.sleep(poll_seconds)
    return iterations


def start(
    poll_seconds: int = 60,
    concurrency: int = 5,
    force_js: bool = False,
    digest_every_hours: float = 0,
) -> None:
    """Blocking entrypoint for the daemon."""
    asyncio.run(
        run_forever(
            poll_seconds=poll_seconds,
            concurrency=concurrency,
            force_js=force_js,
            digest_every_hours=digest_every_hours,
        )
    )
