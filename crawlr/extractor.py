"""The self-healing extraction core.

Flow per scrape:
  1. Fetch HTML (static, auto-escalate to JS).
  2. Load cached selectors for (host, schema). If none, generate them.
  3. Extract deterministically using selectors (fast, free, stable).
  4. If extraction "looks broken" (required fields empty / zero items),
     regenerate selectors once and retry -> this is the self-healing step.
"""

from __future__ import annotations

import hashlib

from selectolax.parser import HTMLParser, Node

from . import archive, config, fallback, llm, normalize, selector_cache, structured, usage
from .fetcher import fetch
from .models import ExtractionResult, ExtractionSchema, FieldSpec, FieldType
from .validate import confidence_score, validate_records


def _content_hash(html: str) -> str | None:
    if not html:
        return None
    return hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest()


def scrape(url: str, schema: ExtractionSchema, force_js: bool = False) -> ExtractionResult:
    """Scrape a URL against a schema, self-healing selectors if they break."""
    usage.begin_run()
    fetched = fetch(url, force_js=force_js)
    result = ExtractionResult(url=fetched.url, schema_name=schema.name)
    result.blocked = fetched.blocked
    result.rendered_with_js = fetched.rendered_with_js
    result.content_hash = _content_hash(fetched.html)

    if fetched.blocked:
        result.warnings.append(f"Blocked ({fetched.blocked_reason or 'unknown'}).")
        return _finalize(result, [], schema, "")

    # Archive the raw HTML so it can be re-extracted offline / audited later.
    if config.ARCHIVE_ENABLED:
        archive.save(fetched.url, schema.name, fetched.html)

    if fetched.rendered_with_js is False and _static_looked_empty(fetched.html):
        result.warnings.append("Page looked JS-heavy; static HTML may be incomplete.")

    cached = selector_cache.get(url, schema.name)

    if cached is not None:
        records = _extract(fetched.html, cached)
        if not _looks_broken(records, cached):
            result.used_llm = False
            return _finalize(result, records, cached, fetched.html)
        result.warnings.append("Cached selectors broke; regenerating (self-heal).")

    # Generate (or regenerate) selectors, cache them, extract.
    healed_schema, used_llm = llm.generate_selectors(schema, fetched.html)
    selector_cache.put(url, healed_schema)
    records = _extract(fetched.html, healed_schema)

    result.healed = cached is not None
    result.used_llm = used_llm
    if _looks_broken(records, healed_schema):
        result.warnings.append("Extraction still incomplete after healing.")
    return _finalize(result, records, healed_schema, fetched.html)


def reextract(url: str, schema: ExtractionSchema, html: str) -> ExtractionResult:
    """Extract from already-fetched HTML with no network access.

    Powers `crawlr replay` (re-run against an archived snapshot) and offline
    selector testing. Uses cached selectors when they still work, else
    regenerates them — same self-healing + consensus as a live scrape.
    """
    usage.begin_run()
    result = ExtractionResult(url=url, schema_name=schema.name)
    cached = selector_cache.get(url, schema.name)
    if cached is not None:
        records = _extract(html, cached)
        if not _looks_broken(records, cached):
            return _finalize(result, records, cached, html)
    healed_schema, used_llm = llm.generate_selectors(schema, html)
    records = _extract(html, healed_schema)
    result.used_llm = used_llm
    return _finalize(result, records, healed_schema, html)


def _finalize(
    result: ExtractionResult,
    records: list[dict],
    schema: ExtractionSchema,
    html: str = "",
) -> ExtractionResult:
    """Attach records plus confidence/validity signals to the result.

    For single-record (product) pages, cross-checks selector output against
    structured data (JSON-LD / microdata / OpenGraph) to fill gaps, correct
    disagreements, and produce per-field confidence.
    """
    result.html = html
    # Consensus layer: only meaningful for single-record extraction.
    if records and html and not schema.item_selector:
        data = structured.extract_structured(html)
        if data:
            merged, field_conf, field_src = _consense(records[0], data, schema)
            # Merge reliable structured-only extras (brand, sku, currency, ...)
            # that the schema doesn't explicitly ask for, so records are richer
            # without letting brittle heuristic selectors pollute them.
            for key in _EXTRA_FIELDS:
                val = data.get(key)
                if val not in (None, "") and merged.get(key) in (None, ""):
                    merged[key] = val
                    field_src.setdefault(key, "structured")
            disc = normalize.compute_discount(merged.get("original_price"), merged.get("price"))
            if disc is not None:
                merged["discount_pct"] = disc
            records = [merged, *records[1:]]
            result.field_confidence = field_conf
            result.field_source = field_src
            if any(v == 0.5 for v in field_conf.values()):
                result.warnings.append("Structured data disagreed with selectors on a field.")

        # Last-resort page-level fallbacks: fill any essentials still missing
        # after structured data + selectors (title/price/currency/availability/
        # image), so a product page yields useful data even on unusual layouts.
        # These only fill gaps — they never overwrite an existing value.
        filled = _fill_fallbacks(records[0], html, schema)
        for name in filled:
            result.field_source.setdefault(name, "fallback")
        disc = normalize.compute_discount(
            records[0].get("original_price"), records[0].get("price")
        )
        if disc is not None:
            records[0]["discount_pct"] = disc

    result.records = records

    if result.field_confidence:
        names = [f.name for f in schema.fields if f.required] or [f.name for f in schema.fields]
        vals = [result.field_confidence.get(n, 0.0) for n in names]
        result.confidence = round(sum(vals) / len(vals), 3) if vals else 0.0
    else:
        result.confidence = confidence_score(records, schema)

    result.quality = _quality_label(result.confidence, result.field_source)

    valid, errors = validate_records(records, schema)
    result.valid = valid
    if errors:
        result.warnings.append(f"{len(errors)} validation issue(s); first: {errors[0]}")
    return result


def _fill_fallbacks(record: dict, html: str, schema: ExtractionSchema) -> list[str]:
    """Fill still-empty canonical fields with aggressive page-level heuristics.

    Returns the names of the fields that were filled (used to mark provenance).
    Only fields the schema actually asks for are considered, and only when the
    record's value is still missing.
    """
    tree = HTMLParser(html)
    names = {f.name for f in schema.fields}
    filled: list[str] = []

    if "title" in names and record.get("title") in (None, ""):
        title = fallback.fallback_title(tree)
        if title:
            record["title"] = title
            filled.append("title")

    if "price" in names and record.get("price") in (None, ""):
        amount, currency = fallback.fallback_price(tree)
        if amount is not None:
            record["price"] = amount
            filled.append("price")
            if currency and record.get("currency") in (None, ""):
                record["currency"] = currency

    if "availability" in names and record.get("availability") in (None, ""):
        avail = fallback.fallback_availability(tree)
        if avail:
            record["availability"] = avail
            filled.append("availability")

    if "image" in names and record.get("image") in (None, ""):
        image = fallback.fallback_image(tree)
        if image:
            record["image"] = image
            filled.append("image")

    return filled


def _quality_label(confidence: float, field_source: dict) -> str:
    """Human-readable trust label for a run's data."""
    structured_backed = any(s in ("structured", "both") for s in field_source.values())
    if confidence >= 0.85:
        return "verified" if structured_backed else "high"
    if confidence >= 0.5:
        return "inferred"
    return "low"


# ---------------------------------------------------------------------------
# Consensus: structured data vs selectors -> merged values + field confidence
# ---------------------------------------------------------------------------

# Canonical fields that structured data can provide.
_CANONICAL = {
    "title", "price", "original_price", "currency", "availability", "rating",
    "review_count", "brand", "sku", "gtin", "mpn", "image", "url",
}

# Rich structured-only fields merged into single-product records even when the
# schema doesn't list them (always sourced from structured data, never guessed).
_EXTRA_FIELDS = {
    "original_price", "currency", "brand", "sku", "gtin", "mpn", "review_count",
}


def _consense(record: dict, data: dict, schema: ExtractionSchema) -> tuple[dict, dict, dict]:
    merged = dict(record)
    field_conf: dict = {}
    field_src: dict = {}
    for field in schema.fields:
        sel = record.get(field.name)
        struct = data.get(field.name) if field.name in _CANONICAL else None
        merged[field.name] = _choose(field, sel, struct)
        field_conf[field.name] = _field_confidence(sel, struct, field.type)
        field_src[field.name] = _source(sel, struct)
    return merged, field_conf, field_src


def _source(sel, struct) -> str:
    sel_present = sel not in (None, "")
    struct_present = struct not in (None, "")
    if sel_present and struct_present:
        return "both"
    if struct_present:
        return "structured"
    if sel_present:
        return "selector"
    return "none"


def _values_agree(a, b, ftype: FieldType) -> bool:
    if a in (None, "") or b in (None, ""):
        return False
    if ftype in (FieldType.PRICE, FieldType.NUMBER):
        na, nb = normalize.normalize_number(a), normalize.normalize_number(b)
        return na is not None and nb is not None and abs(na - nb) < 0.01
    ta, tb = normalize.normalize_stock(a), normalize.normalize_stock(b)
    if ta is not None and tb is not None:
        return ta == tb
    sa, sb = str(a).strip().lower(), str(b).strip().lower()
    return sa == sb or sa in sb or sb in sa


def _field_confidence(sel, struct, ftype: FieldType) -> float:
    sel_present = sel not in (None, "")
    struct_present = struct not in (None, "")
    if sel_present and struct_present:
        return 1.0 if _values_agree(sel, struct, ftype) else 0.5
    if sel_present or struct_present:
        return 0.7
    return 0.0


def _choose(field: FieldSpec, sel, struct):
    """Pick the best value: fill gaps from structured data; on disagreement,
    trust structured data for numeric fields and availability."""
    if struct in (None, ""):
        return sel
    if sel in (None, ""):
        return _coerce_value(struct, field.type)
    if _values_agree(sel, struct, field.type):
        return sel
    prefer_structured = field.type in (FieldType.PRICE, FieldType.NUMBER) or field.name == "availability"
    return _coerce_value(struct, field.type) if prefer_structured else sel


def _coerce_value(value, ftype: FieldType):
    if ftype in (FieldType.PRICE, FieldType.NUMBER):
        return normalize.normalize_number(value)
    if ftype == FieldType.BOOL:
        stock = normalize.normalize_stock(value)
        return stock if stock is not None else str(value).strip().lower() in {"true", "yes", "1"}
    return str(value)


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


def _coerce(value: str, ftype: FieldType):
    if ftype in (FieldType.PRICE, FieldType.NUMBER):
        return normalize.normalize_number(value)
    if ftype == FieldType.BOOL:
        stock = normalize.normalize_stock(value)
        if stock is not None:
            return stock
        return value.strip().lower() in {"true", "yes", "1"}
    return value
