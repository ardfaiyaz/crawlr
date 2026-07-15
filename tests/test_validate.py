"""Tests for extraction validation + confidence scoring (roadmap item 2)."""

from __future__ import annotations

from crawlr.models import ExtractionSchema, FieldSpec, FieldType
from crawlr.validate import confidence_score, validate_records


def _schema() -> ExtractionSchema:
    return ExtractionSchema(
        name="x",
        fields=[
            FieldSpec(name="title", description="t", required=True),
            FieldSpec(name="price", description="p", type=FieldType.PRICE, required=True),
        ],
    )


def test_confidence_full():
    records = [{"title": "A", "price": 1.0}, {"title": "B", "price": 2.0}]
    assert confidence_score(records, _schema()) == 1.0


def test_confidence_partial():
    # 4 required cells, 2 populated -> 0.5
    records = [{"title": "A", "price": None}, {"title": None, "price": 2.0}]
    assert confidence_score(records, _schema()) == 0.5


def test_confidence_empty():
    assert confidence_score([], _schema()) == 0.0


def test_validate_missing_required():
    ok, errors = validate_records([{"title": "A", "price": None}], _schema())
    assert not ok
    assert any("price" in e for e in errors)


def test_validate_type_mismatch():
    ok, errors = validate_records([{"title": "A", "price": "cheap"}], _schema())
    assert not ok


def test_validate_ok():
    ok, errors = validate_records([{"title": "A", "price": 1.0}], _schema())
    assert ok and errors == []
