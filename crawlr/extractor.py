"""The self-healing extraction core.

Flow per scrape:
  1. Fetch HTML (static, auto-escalate to JS).
  2. Load cached selectors for (host, schema). If none, generate them.
  3. Extract deterministically using selectors (fast, free, stable).
  4. If extraction "looks broken" (required fields empty / zero items),
     regenerate selectors once and retry -> this is the self-healing step.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from . import llm, selector_cache
from .fetcher import fetch
from .models import ExtractionResult, ExtractionSchema, FieldSpec, FieldType


def scrape(url: str, schema: ExtractionSchema, force_js: bool = False) -> ExtractionResult:
    """Scrape a URL against a schema, self-healing selectors if they break."""
    fetched = fetch(url, force_js=force_js)
    result = ExtractionResult(url=fetched.url, schema_name=schema.name)
    if fetched.rendered_with_js is False and _static_looked_empty(fetched.html):
        result.warnings.append("Page may require JS rendering (install the 'js' extra).")

    cached = selector_cache.get(url, schema.name)
    used_llm = False

    if cached is not None:
        records = _extract(fetched.html, cached)
        if not _looks_broken(records, cached):
            result.records = records
            result.used_llm = False
            return result
        result.warnings.append("Cached selectors broke; regenerating (self-heal).")

    # Generate (or regenerate) selectors, cache them, extract.
    healed_schema, used_llm = llm.generate_selectors(schema, fetched.html)
    selector_cache.put(url, healed_schema)
    records = _extract(fetched.html, healed_schema)

    result.records = records
    result.healed = cached is not None
    result.used_llm = used_llm
    if _looks_broken(records, healed_schema):
        result.warnings.append("Extraction still incomplete after healing.")
    return result


def _static_looked_empty(html: str) -> bool:
    tree = HTMLParser(html)
    body = tree.body
    return body is None or len((body.text() or "").strip()) < 200


def _looks_broken(records: list[dict], schema: ExtractionSchema) -> bool:
    """Detect probable selector breakage."""
    if not records:
        return True
    required = [f.name for f in schema.fields if f.required]
    if not required:
        # No required fields declared: consider broken if every record is empty.
        return all(not any(v for v in rec.values()) for rec in records)
    for rec in records:
        if all(rec.get(name) for name in required):
            return False
    return True


# ---------------------------------------------------------------------------
# Deterministic extraction
# ---------------------------------------------------------------------------


def _extract(html: str, schema: ExtractionSchema) -> list[dict]:
    tree = HTMLParser(html)
    if schema.item_selector:
        items = tree.css(schema.item_selector)
        return [_extract_fields(item, schema.fields) for item in items]
    root = tree.body or tree.root
    if root is None:
        return []
    return [_extract_fields(root, schema.fields)]


def _extract_fields(scope: Node, fields: list[FieldSpec]) -> dict:
    record: dict = {}
    for field in fields:
        record[field.name] = _extract_one(scope, field)
    return record


def _extract_one(scope: Node, field: FieldSpec):
    if not field.selector:
        return None
    node = scope.css_first(field.selector)
    if node is None:
        return None

    raw: str | None = None
    if field.attribute:
        raw = node.attributes.get(field.attribute)
    # Fall back to text content when no attribute was requested, or when the
    # requested attribute is absent (common with itemprop microdata that puts
    # the value in text rather than a `content` attribute).
    if raw is None:
        raw = node.text()
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None

    return _coerce(raw, field.type)


_PRICE_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def _coerce(value: str, ftype: FieldType):
    if ftype in (FieldType.PRICE, FieldType.NUMBER):
        match = _PRICE_RE.search(value.replace(",", ""))
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
        return None
    if ftype == FieldType.BOOL:
        return value.strip().lower() in {"true", "yes", "in stock", "available", "1"}
    return value
