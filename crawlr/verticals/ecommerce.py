"""E-commerce / price-intelligence vertical.

Ships two ready-to-use schemas:
  * PRODUCT_SCHEMA       - a single product detail page.
  * PRODUCT_LIST_SCHEMA  - a search / category page with many products.

The field descriptions double as natural-language hints for LLM selector
generation, so these work on arbitrary stores without hand-written selectors.
"""

from __future__ import annotations

from ..models import ExtractionSchema, FieldSpec, FieldType

PRODUCT_SCHEMA = ExtractionSchema(
    name="product",
    fields=[
        FieldSpec(
            name="title",
            description="The product name / title",
            type=FieldType.TEXT,
            required=True,
        ),
        FieldSpec(
            name="price",
            description="The current selling price of the product",
            type=FieldType.PRICE,
            required=True,
        ),
        FieldSpec(
            name="availability",
            description="Stock status such as In Stock / Out of Stock",
            type=FieldType.TEXT,
        ),
        FieldSpec(
            name="rating",
            description="Average customer rating (numeric)",
            type=FieldType.NUMBER,
        ),
        FieldSpec(
            name="image",
            description="Main product image URL",
            type=FieldType.IMAGE,
            attribute="src",
        ),
    ],
)

PRODUCT_LIST_SCHEMA = ExtractionSchema(
    name="product_list",
    fields=[
        FieldSpec(
            name="title",
            description="The product name shown on the listing card",
            type=FieldType.TEXT,
            required=True,
        ),
        FieldSpec(
            name="price",
            description="The listed price on the product card",
            type=FieldType.PRICE,
            required=True,
        ),
        FieldSpec(
            name="url",
            description="Link to the product detail page",
            type=FieldType.URL,
            attribute="href",
        ),
        FieldSpec(
            name="image",
            description="Product thumbnail image URL",
            type=FieldType.IMAGE,
            attribute="src",
        ),
    ],
)

_REGISTRY = {s.name: s for s in (PRODUCT_SCHEMA, PRODUCT_LIST_SCHEMA)}


def resolve(schema_name: str) -> ExtractionSchema | None:
    """Look up a built-in schema by name (used by the monitor scheduler)."""
    return _REGISTRY.get(schema_name)
