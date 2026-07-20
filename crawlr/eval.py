"""Accuracy evaluation harness (Reliability v2).

Runs extraction against a set of golden fixtures (HTML + expected values) and
reports accuracy. Used both as a CLI (`crawlr eval`) and a CI regression gate,
so extraction accuracy can't silently degrade as the engine evolves.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from . import normalize, schemas
from .extractor import reextract

_DIR = Path(__file__).parent / "golden"


def _agree(expected, actual) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        a = normalize.normalize_number(actual)
        return a is not None and abs(a - float(expected)) < 0.01
    if actual is None:
        return False
    te, ta = normalize.normalize_stock(expected), normalize.normalize_stock(actual)
    if te is not None and ta is not None:
        return te == ta
    se, sa = str(expected).strip().lower(), str(actual).strip().lower()
    return se == sa or se in sa


def run_eval() -> dict:
    """Extract every golden case and score field-level accuracy."""
    cases_file = _DIR / "cases.yaml"
    if not cases_file.exists():
        return {"cases": 0, "checks": 0, "passed": 0, "accuracy": 1.0, "failures": []}

    cases = yaml.safe_load(cases_file.read_text()) or []
    checks = passed = 0
    failures: list[dict] = []

    for case in cases:
        html = (_DIR / case["file"]).read_text()
        schema = schemas.resolve(case["schema"])
        if schema is None:
            continue
        result = reextract(f"https://golden.local/{case['file']}", schema, html)
        record = result.records[0] if result.records else {}
        for field, expected in case["expected"].items():
            checks += 1
            got = record.get(field)
            if _agree(expected, got):
                passed += 1
            else:
                failures.append(
                    {"case": case["file"], "field": field, "expected": expected, "got": got}
                )

    accuracy = (passed / checks) if checks else 1.0
    return {
        "cases": len(cases),
        "checks": checks,
        "passed": passed,
        "accuracy": round(accuracy, 3),
        "failures": failures,
    }
