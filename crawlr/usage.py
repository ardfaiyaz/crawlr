"""LLM usage accounting + per-run budget guardrails (roadmap item 3).

Crawlr only calls the LLM to (re)generate selectors, but we still guard against
runaway cost:

  * a hard cap on the number of LLM calls within a single scrape/run, and
  * token + estimated-spend accounting that can be logged or surfaced.

State is thread-local so concurrent site scrapes (async runner) keep separate
budgets and counters.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .config import LLM

_state = threading.local()


@dataclass
class RunUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def estimated_cost(self) -> float:
        return round((self.total_tokens / 1000.0) * LLM.price_per_1k_tokens, 6)

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost": self.estimated_cost,
        }


def _current() -> RunUsage:
    usage = getattr(_state, "usage", None)
    if usage is None:
        usage = RunUsage()
        _state.usage = usage
    return usage


def begin_run() -> None:
    """Reset the per-run counters (call at the start of a scrape)."""
    _state.usage = RunUsage()


def can_call() -> bool:
    """True while the per-run LLM call budget has not been exhausted."""
    return _current().calls < LLM.max_calls_per_run


def record_call(prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    usage = _current()
    usage.calls += 1
    usage.prompt_tokens += max(0, prompt_tokens)
    usage.completion_tokens += max(0, completion_tokens)


def snapshot() -> RunUsage:
    return _current()
