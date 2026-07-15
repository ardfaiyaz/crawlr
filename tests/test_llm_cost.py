"""Tests for LLM cost guardrails: budget + outline cache (roadmap item 3)."""

from __future__ import annotations

from crawlr import llm, usage
from crawlr.config import LLMConfig
from crawlr.models import ExtractionSchema, FieldSpec


def _schema() -> ExtractionSchema:
    return ExtractionSchema(name="x", fields=[FieldSpec(name="title", description="t")])


def test_call_budget_enforced(monkeypatch):
    monkeypatch.setattr(usage, "LLM", LLMConfig(max_calls_per_run=2))
    usage.begin_run()
    assert usage.can_call()
    usage.record_call(10, 5)
    usage.record_call(10, 5)
    assert not usage.can_call()
    snap = usage.snapshot()
    assert snap.calls == 2
    assert snap.total_tokens == 30
    assert snap.estimated_cost >= 0


def test_outline_cache_avoids_second_llm_call(monkeypatch):
    fake = LLMConfig(provider="openai", api_key="k", model="m", max_calls_per_run=5)
    monkeypatch.setattr(llm, "LLM", fake)
    monkeypatch.setattr(usage, "LLM", fake)

    calls = {"n": 0}

    def fake_generate(schema, html, outline=None):
        calls["n"] += 1
        updated = schema.model_copy(deep=True)
        updated.fields[0].selector = "h1"
        return updated

    monkeypatch.setattr(llm, "_generate_with_llm", fake_generate)
    usage.begin_run()

    html = "<html><body><h1>This is a sufficiently long product title</h1></body></html>"
    schema = _schema()

    result1, used1 = llm.generate_selectors(schema, html)
    result2, used2 = llm.generate_selectors(schema, html)

    assert calls["n"] == 1  # second call served from the outline cache
    assert used1 is True
    assert used2 is False
    assert result1.fields[0].selector == "h1"
    assert result2.fields[0].selector == "h1"
