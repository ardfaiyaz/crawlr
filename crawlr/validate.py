"""Extraction validation + confidence scoring (roadmap item 2).

Two independent signals of extraction quality:

  * validity   - do the extracted values satisfy the schema's declared types
                 and required-field constraints?
  * confidence - what fraction of the required-field "cells" (record x required
                 field) were actually populated? A cheap, interpretable proxy
                 for how well the selectors matched.

These feed the self-healing decision and are surfaced in the CLI / dashboard so
users can trust (or distrust) a given run at a glance.
"""

from __future__ import annotations

from .models import ExtractionSchema, FieldType


def confidence_score(records: list[dict], schema: ExtractionSchema) -> float:
    """Fraction of required-field cells that are populated (0.0..1.0)."""
    if not records:
        return 0.0
    required = [f.name for f in schema.fields if f.required]
    if not required:
        # No required fields: score by overall field fill rate instead.
        cells = sum(len(r) for r in records) or 1
        filled = sum(1 for r in records for v in r.values() if v not in (None, ""))
        return round(filled / cells, 3)

    total = len(records) * len(required)
    filled = sum(
        1 for rec in records for name in required if rec.get(name) not in (None, "")
    )
    return round(filled / total, 3) if total else 0.0


def validate_records(records: list[dict], schema: ExtractionSchema) -> tuple[bool, list[str]]:
    """Check records against the schema. Returns (all_valid, error_messages)."""
    errors: list[str] = []
    required = [f.name for f in schema.fields if f.required]

    for i, rec in enumerate(records):
        for name in required:
            if rec.get(name) in (None, ""):
                errors.append(f"record[{i}]: missing required field '{name}'")
        for fld in schema.fields:
            value = rec.get(fld.name)
            if value in (None, ""):
                continue
            if not _type_ok(value, fld.type):
                errors.append(
                    f"record[{i}]: field '{fld.name}' expected {fld.type.value}, "
                    f"got {type(value).__name__}"
                )
    return (len(errors) == 0, errors)


def _type_ok(value, ftype: FieldType) -> bool:
    if ftype in (FieldType.PRICE, FieldType.NUMBER):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ftype == FieldType.BOOL:
        return isinstance(value, bool)
    # TEXT / URL / IMAGE are strings once coerced.
    return isinstance(value, str)
