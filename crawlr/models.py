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


class TriggerType(str, Enum):
    """When a watched site should raise an alert.

    Users pick one per watch (the simple path); the rules template can override
    with richer circumstance -> action logic.
    """

    ANY_CHANGE = "any_change"       # any watched field changed
    PRICE_DROP = "price_drop"       # price went down at all
    PRICE_BELOW = "price_below"     # price at/under target_price
    PRICE_ABOVE = "price_above"     # price at/over target_price
    BACK_IN_STOCK = "back_in_stock"  # availability flipped to in-stock
    OUT_OF_STOCK = "out_of_stock"   # availability flipped to out-of-stock


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
    # Per-field confidence (0..1) from structured-data vs selector consensus.
    field_confidence: dict = Field(default_factory=dict)
    # Per-field provenance: "structured" | "selector" | "both" | "none".
    field_source: dict = Field(default_factory=dict)
    # Overall data-quality label: verified | high | inferred | low.
    quality: str = "unknown"
    # Fetch diagnostics.
    blocked: bool = False           # the page was blocked / anti-bot challenged
    rendered_with_js: bool = False  # a headless browser rendered the page
    content_hash: str | None = None  # hash of fetched HTML (stale-page detection)
    # Raw fetched HTML, kept in-memory for extra extraction strategies (e.g. the
    # canvas JSON-LD product-list pass). Excluded from serialization/persistence.
    html: str = Field(default="", exclude=True, repr=False)
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
    original_price: float | None = None
    discount_pct: float | None = None
    currency: str | None = None
    availability: str | None = None
    rating: float | None = None
    review_count: float | None = None
    brand: str | None = None
    sku: str | None = None
    gtin: str | None = None
    mpn: str | None = None
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
    trigger: TriggerType = TriggerType.ANY_CHANGE
    target_price: float | None = None
    # Per-site overrides for the anomaly guard and retention window. None means
    # "inherit the global default" (config.ANOMALY_ZSCORE / ANOMALY_MIN_SAMPLES /
    # RETENTION_RUNS), so existing behavior is unchanged unless a site opts in.
    anomaly_zscore: float | None = None
    anomaly_min_samples: int | None = None
    retention_runs: int | None = None
    created_at: datetime = Field(default_factory=_now)
