"""Pre-built extraction schemas for specific domains (verticals).

The engine is general-purpose; verticals are just packaged schemas + defaults
that make the tool best-in-class for a specific data type out of the box.
"""

from .ecommerce import PRODUCT_LIST_SCHEMA, PRODUCT_SCHEMA, resolve

__all__ = ["PRODUCT_SCHEMA", "PRODUCT_LIST_SCHEMA", "resolve"]
