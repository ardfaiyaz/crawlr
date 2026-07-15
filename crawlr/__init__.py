"""Crawlr: an AI-powered, self-healing web scraper.

Core idea: use an LLM to *generate and repair* deterministic CSS selectors
(the expensive, intelligent step) instead of extracting every page with the
LLM (the naive, slow, expensive approach). Deterministic selectors are cached
and reused; when they break, the extractor self-heals by regenerating them.
"""

__version__ = "0.1.0"
