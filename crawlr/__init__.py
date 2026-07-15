"""Crawlr: an AI-powered, self-healing web scraper.

Core idea: use an LLM to *generate and repair* deterministic CSS selectors
(the expensive, intelligent step) instead of extracting every page with the
LLM (the naive, slow, expensive approach). Deterministic selectors are cached
and reused; when they break, the extractor self-heals by regenerating them.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: the installed distribution's version (from the
    # git tag at publish time). Avoids drift between code and package metadata.
    __version__ = version("crawlr")
except PackageNotFoundError:  # pragma: no cover - only when running from a raw checkout
    __version__ = "0.0.0"
