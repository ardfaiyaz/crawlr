"""LLM abstraction for selector generation, with an offline heuristic fallback.

Design principle: the LLM is used *sparingly* to produce reusable CSS selectors
for a schema, not to extract every page. Two provider paths:

  * "openai" / "anthropic": call the provider's chat API over HTTP.
  * "none" (default): a deterministic heuristic that infers selectors from the
    simplified DOM outline using common structural patterns. This keeps the
    whole tool runnable offline and with zero cost, while an API key upgrades
    accuracy on unusual layouts.
"""

from __future__ import annotations

import hashlib
import json
import re

import httpx

from . import selector_cache, usage
from .config import LLM
from .models import ExtractionSchema, FieldSpec, FieldType
from .simplifier import strip_noise, to_outline

_SYSTEM_PROMPT = (
    "You are an expert web-scraping engineer. Given a simplified HTML outline "
    "and a list of fields to extract, return ONLY valid JSON mapping each field "
    "name to a robust CSS selector (and optional attribute). Prefer stable "
    "selectors (ids, itemprop, data-* attributes, semantic tags) over brittle "
    "auto-generated class names. If items repeat, also return an 'item_selector'."
)


def generate_selectors(schema: ExtractionSchema, html: str) -> tuple[ExtractionSchema, bool]:
    """Fill in `selector`/`attribute` on the schema's fields.

    Returns (updated_schema, used_llm). Cost guardrails: results of prior LLM
    calls are cached by page-content hash (so identical structures never pay
    twice), and a per-run call budget prevents runaway spend. Any failure falls
    back to the free offline heuristic.
    """
    if LLM.enabled:
        outline = to_outline(html)
        outline_hash = hashlib.sha256(outline.encode("utf-8")).hexdigest()
        cached = selector_cache.get_by_outline(outline_hash, schema.name)
        if cached is not None:
            return cached, False  # reused a prior LLM result: zero new cost
        if usage.can_call():
            try:
                updated = _generate_with_llm(schema, html, outline)
                selector_cache.put_by_outline(outline_hash, updated)
                return updated, True
            except Exception:
                # Never let an LLM failure break scraping; fall back to heuristics.
                pass
    return _generate_heuristic(schema, html), False


# ---------------------------------------------------------------------------
# LLM-backed generation
# ---------------------------------------------------------------------------


def _generate_with_llm(
    schema: ExtractionSchema, html: str, outline: str | None = None
) -> ExtractionSchema:
    if outline is None:
        outline = to_outline(html)
    field_desc = "\n".join(
        f"- {f.name} ({f.type.value}): {f.description}" for f in schema.fields
    )
    user_prompt = (
        f"Fields to extract:\n{field_desc}\n\n"
        f"Simplified HTML outline:\n{outline}\n\n"
        'Return JSON like: {"item_selector": "...", "fields": '
        '{"name": {"selector": "...", "attribute": null}}}'
    )
    raw = _chat(user_prompt)
    data = _parse_json(raw)
    return _apply_selector_map(schema, data)


def _chat(user_prompt: str) -> str:
    if LLM.provider == "openai":
        url = (LLM.base_url or "https://api.openai.com/v1") + "/chat/completions"
        headers = {"Authorization": f"Bearer {LLM.api_key}"}
        payload = {
            "model": LLM.model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        with httpx.Client(timeout=LLM.timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            body = resp.json()
            u = body.get("usage", {})
            usage.record_call(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
            return body["choices"][0]["message"]["content"]

    if LLM.provider == "anthropic":
        url = (LLM.base_url or "https://api.anthropic.com/v1") + "/messages"
        headers = {
            "x-api-key": LLM.api_key or "",
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": LLM.model or "claude-3-5-sonnet-latest",
            "max_tokens": 1024,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        with httpx.Client(timeout=LLM.timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            body = resp.json()
            u = body.get("usage", {})
            usage.record_call(u.get("input_tokens", 0), u.get("output_tokens", 0))
            return body["content"][0]["text"]

    raise RuntimeError(f"Unsupported LLM provider: {LLM.provider}")


def _parse_json(raw: str) -> dict:
    # Strip markdown fences if present.
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(match.group(0))


def _apply_selector_map(schema: ExtractionSchema, data: dict) -> ExtractionSchema:
    updated = schema.model_copy(deep=True)
    if data.get("item_selector"):
        updated.item_selector = data["item_selector"]
    field_map = data.get("fields", {})
    for field in updated.fields:
        info = field_map.get(field.name)
        if isinstance(info, dict):
            field.selector = info.get("selector") or field.selector
            field.attribute = info.get("attribute") or field.attribute
        elif isinstance(info, str):
            field.selector = info
    return updated


# ---------------------------------------------------------------------------
# Heuristic (offline) generation
# ---------------------------------------------------------------------------

# Common patterns keyed by intent keywords found in a field name/description.
_HEURISTIC_PATTERNS: dict[str, list[tuple[str, str | None]]] = {
    "title": [
        ('[itemprop="name"]', None),
        (".product-title", None),
        (".product-name", None),
        ("h1", None),
        ("h2", None),
        ("h3", None),
        (".name", None),
        (".title", None),
        ("h2 a", None),
    ],
    "price": [
        ('[itemprop="price"]', "content"),
        (".price", None),
        (".price_color", None),
        (".product-price", None),
        (".a-price .a-offscreen", None),
        (".cost", None),
        (".amount", None),
        ("[data-price]", "data-price"),
    ],
    "availability": [
        ('[itemprop="availability"]', "href"),
        (".availability", None),
        (".stock", None),
        (".in-stock", None),
    ],
    "rating": [
        ('[itemprop="ratingValue"]', None),
        (".rating", None),
        (".stars", None),
    ],
    "image": [
        ('[itemprop="image"]', "src"),
        (".product-image img", "src"),
        ("img.product-image", "src"),
        ("img.product", "src"),
        ("img", "src"),
    ],
    "url": [
        ("a.product-link", "href"),
        ("h2 a", "href"),
        ("h3 a", "href"),
        ("a", "href"),
    ],
}

# Common containers for repeating product items.
_ITEM_CONTAINER_CANDIDATES = [
    "[itemtype*='Product']",
    ".product",
    ".product-item",
    ".product-card",
    "li.product",
    "article.product",
    ".s-result-item",
    ".card",
    "article",
]


def _match_intent(field: FieldSpec) -> list[tuple[str, str | None]]:
    hay = f"{field.name} {field.description}".lower()
    for key, patterns in _HEURISTIC_PATTERNS.items():
        if key in hay:
            return patterns
    # Fall back to intent inferred from the declared field type.
    type_map = {
        FieldType.PRICE: "price",
        FieldType.IMAGE: "image",
        FieldType.URL: "url",
    }
    key = type_map.get(field.type)
    return _HEURISTIC_PATTERNS.get(key, []) if key else []


def _generate_heuristic(schema: ExtractionSchema, html: str) -> ExtractionSchema:
    tree = strip_noise(html)
    updated = schema.model_copy(deep=True)

    # Detect a repeating item container if the schema expects a list.
    if updated.item_selector is None:
        for candidate in _ITEM_CONTAINER_CANDIDATES:
            if len(tree.css(candidate)) >= 2:
                updated.item_selector = candidate
                break

    scope = updated.item_selector or "body"
    scope_nodes = tree.css(scope)

    for field in updated.fields:
        if field.selector:
            continue  # user supplied one explicitly
        for selector, attr in _match_intent(field):
            # Verify the candidate actually matches within the chosen scope.
            if _selector_matches(scope_nodes, selector):
                field.selector = selector
                if attr and field.attribute is None:
                    field.attribute = attr
                break
    return updated


def _selector_matches(scope_nodes, selector: str) -> bool:
    if not scope_nodes:
        return False
    for node in scope_nodes:
        try:
            if node.css_first(selector) is not None:
                return True
        except Exception:
            continue
    return False
