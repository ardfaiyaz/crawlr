"""Core data models shared across the extraction engine and verticals."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FieldType(str, Enum):
    TEXT = "text"
    NUMBER = "number"
    PRICE = "price"
    URL = "url"
    IMAGE = "image"
    BOOL = "bool"


class FieldSpec(BaseModel):
    """A single field the user wants to extract.

    `description` is the natural-language hint the LLM uses to locate the field
    on first visit. `selector` is the deterministic CSS selector, filled in by
    the engine (LLM or heuristic) and cached for reuse.
    """

    name: str
    description: str
    type: FieldType = FieldType.TEXT
    selector: str | None = None
    attribute: str | None = None  # e.g. "href", "src"; None means text content
    required: bool = False


class ExtractionSchema(BaseModel):
    """Describes what to pull from a page and how items repeat.

    If `item_selector` is set, the page is treated as a list (e.g. a search
    results page) and fields are extracted relative to each matched item.
    Otherwise a single record is extracted from the whole document.
    """

    name: str
    fields: list[FieldSpec]
    item_selector: str | None = None

    def field(self, name: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.name == name), None)


class ExtractionResult(BaseModel):
    url: str
    schema_name: str
    records: list[dict] = Field(default_factory=list)
    healed: bool = False  # True if selectors were regenerated this run
    used_llm: bool = False
    fetched_at: datetime = Field(default_factory=_now)
    warnings: list[str] = Field(default_factory=list)
    # Fraction (0..1) of required-field cells populated across all records.
    confidence: float = 1.0
    # False when any record fails schema validation.
    valid: bool = True

    @property
    def count(self) -> int:
        return len(self.records)


# ---------------------------------------------------------------------------
# E-commerce vertical models
# ---------------------------------------------------------------------------


class Product(BaseModel):
    title: str | None = None
    price: float | None = None
    currency: str | None = None
    availability: str | None = None
    rating: float | None = None
    image: str | None = None
    url: str | None = None


class PriceChange(BaseModel):
    product_url: str
    field: str
    old_value: str | None
    new_value: str | None
    changed_at: datetime = Field(default_factory=_now)

    def item_key_display(self, n: int = 48) -> str:
        """Short, human-friendly identifier for the changed item."""
        key = self.product_url or ""
        return key if len(key) <= n else key[: n - 3] + "..."


class MonitoredSite(BaseModel):
    id: int | None = None
    url: HttpUrl
    schema_name: str
    interval_minutes: int = 60
    active: bool = True
    created_at: datetime = Field(default_factory=_now)
