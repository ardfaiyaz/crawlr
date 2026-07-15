"""The self-healing extraction core.

Flow per scrape:
  1. Fetch HTML (static, auto-escalate to JS).
  2. Load cached selectors for (host, schema). If none, generate them.
  3. Extract deterministically using selectors (fast, free, stable).
  4. If extraction "looks broken" (required fields empty / zero items),
     regenerate selectors once and retry -> this is the self-healing step.
"""

from __future__ import annotations

from selectolax.parser import HTMLParser, Node

from . import llm, normalize, selector_cache, structured, usage
from .fetcher import fetch
from .models import ExtractionResult, ExtractionSchema, FieldSpec, FieldType
from .validate import confidence_score, validate_records


def scrape(url: str, schema: ExtractionSchema, force_js: bool = False) -> ExtractionResult:
    """Scrape a URL against a schema, self-healing selectors if they break."""
    usage.begin_run()
    fetched = fetch(url, force_js=force_js)
    result = ExtractionResult(url=fetched.url, schema_name=schema.name)

    if fetched.blocked:
        result.warnings.append("Blocked by robots.txt (set CRAWLR_RESPECT_ROBOTS=false to override).")
        return _finalize(result, [], schema, "")

    if fetched.rendered_with_js is False and _static_looked_empty(fetched.html):
        result.warnings.append("Page may require JS rendering (install the 'js' extra).")

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
    # Consensus layer: only meaningful for single-record extraction.
    if records and html and not schema.item_selector:
        data = structured.extract_structured(html)
        if data:
            merged, field_conf = _consense(records[0], data, schema)
            records = [merged, *records[1:]]
            result.field_confidence = field_conf
            if any(v == 0.5 for v in field_conf.values()):
                result.warnings.append("Structured data disagreed with selectors on a field.")

    result.records = records

    if result.field_confidence:
        names = [f.name for f in schema.fields if f.required] or [f.name for f in schema.fields]
        vals = [result.field_confidence.get(n, 0.0) for n in names]
        result.confidence = round(sum(vals) / len(vals), 3) if vals else 0.0
    else:
        result.confidence = confidence_score(records, schema)

    valid, errors = validate_records(records, schema)
    result.valid = valid
    if errors:
        result.warnings.append(f"{len(errors)} validation issue(s); first: {errors[0]}")
    return result


# ---------------------------------------------------------------------------
# Consensus: structured data vs selectors -> merged values + field confidence
# ---------------------------------------------------------------------------

# Canonical fields that structured data can provide.
_CANONICAL = {"title", "price", "currency", "availability", "rating", "image", "url"}


def _consense(record: dict, data: dict, schema: ExtractionSchema) -> tuple[dict, dict]:
    merged = dict(record)
    field_conf: dict = {}
    for field in schema.fields:
        sel = record.get(field.name)
        struct = data.get(field.name) if field.name in _CANONICAL else None
        merged[field.name] = _choose(field, sel, struct)
        field_conf[field.name] = _field_confidence(sel, struct, field.type)
    return merged, field_conf


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
