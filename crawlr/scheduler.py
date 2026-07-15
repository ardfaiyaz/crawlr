"""Built-in scheduler daemon (roadmap item 6).

A lightweight polling loop that periodically runs every monitored site whose
interval has elapsed, using the concurrent async runner. This removes the need
for an external cron for simple deployments: `crawlr monitor --daemon`.
"""

from __future__ import annotations

import asyncio
import logging

from . import monitor, schemas

logger = logging.getLogger("crawlr.scheduler")


async def run_forever(
    poll_seconds: int = 60,
    concurrency: int = 5,
    force_js: bool = False,
    max_iterations: int | None = None,
) -> int:
    """Poll for due sites and run them until stopped.

    `max_iterations` bounds the loop (used by tests); None means run forever.
    Returns the number of poll iterations completed.
    """
    iterations = 0
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
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        await asyncio.sleep(poll_seconds)
    return iterations


def start(poll_seconds: int = 60, concurrency: int = 5, force_js: bool = False) -> None:
    """Blocking entrypoint for the daemon."""
    asyncio.run(
        run_forever(poll_seconds=poll_seconds, concurrency=concurrency, force_js=force_js)
    )
