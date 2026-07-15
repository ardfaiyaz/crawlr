"""Alert triggers + the user-editable rules template.

Two layers, simplest first:

  1. Per-watch trigger (``TriggerType``) — pick one filter (price drop, target,
     back in stock, ...). This is the easy path exposed in the CLI/dashboard.
  2. A rules template (``crawlr.rules.yaml``) — for power users who want to say
     "in circumstance X, do action Y" across many situations. When the template
     exists it takes precedence over per-watch triggers.

Both decide which detected changes are worth alerting on. The stock parser
normalizes availability text ("In stock", "Sold out", ...) into a boolean.
"""

from __future__ import annotations

import yaml

from . import config, normalize
from .models import PriceChange, TriggerType


def is_in_stock(value) -> bool | None:
    """Interpret availability text; None when it can't be determined.

    Delegates to :func:`normalize.normalize_stock` so stock parsing lives in
    exactly one place (single source of truth for availability semantics).
    """
    return normalize.normalize_stock(value)


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Per-watch trigger evaluation
# ---------------------------------------------------------------------------


def should_alert(trigger, target_price: float | None, change: PriceChange) -> bool:
    """Does this change satisfy the chosen trigger?"""
    t = trigger if isinstance(trigger, TriggerType) else TriggerType(str(trigger))

    if t == TriggerType.ANY_CHANGE:
        return True

    if t in (TriggerType.PRICE_DROP, TriggerType.PRICE_BELOW, TriggerType.PRICE_ABOVE):
        if change.field != "price":
            return False
        old, new = _to_float(change.old_value), _to_float(change.new_value)
        if new is None:
            return False
        if t == TriggerType.PRICE_DROP:
            return old is not None and new < old
        if t == TriggerType.PRICE_BELOW:
            return target_price is not None and new <= target_price
        return target_price is not None and new >= target_price  # PRICE_ABOVE

    if t in (TriggerType.BACK_IN_STOCK, TriggerType.OUT_OF_STOCK):
        if change.field != "availability":
            return False
        stock = is_in_stock(change.new_value)
        return stock is (t == TriggerType.BACK_IN_STOCK)

    return False


def filter_changes(site: dict, changes: list[PriceChange]) -> list[PriceChange]:
    """Filter detected changes to those that should alert for this site.

    Uses the rules template when present; otherwise the site's own trigger.
    """
    rules = load_rules()
    if rules is not None:
        return [c for c in changes if _rule_action(rules, c) == "alert"]

    trigger = site.get("alert_trigger") or site.get("trigger") or "any_change"
    target = site.get("target_price")
    return [c for c in changes if should_alert(trigger, target, c)]


def watch_status(
    current_price: float | None,
    in_stock: bool | None,
    prev_price: float | None,
    trigger: str | None = None,
    target_price: float | None = None,
) -> str:
    """A short human status for the watchlist row."""
    if in_stock is False:
        return "out of stock"
    if target_price is not None and current_price is not None and current_price <= target_price:
        return "target hit"
    if prev_price is not None and current_price is not None:
        if current_price < prev_price:
            return "price dropped"
        if current_price > prev_price:
            return "price rose"
    if in_stock is True:
        return "in stock"
    return "watching"


# ---------------------------------------------------------------------------
# Rules template (circumstance -> action)
# ---------------------------------------------------------------------------


def load_rules() -> dict | None:
    """Load the rules template if it exists and is valid, else None."""
    if not config.RULES_FILE.exists():
        return None
    try:
        data = yaml.safe_load(config.RULES_FILE.read_text())
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _rule_action(rules: dict, change: PriceChange) -> str:
    default = str(rules.get("default_action", "ignore")).lower()
    for rule in rules.get("rules", []) or []:
        if _rule_matches(rule, change):
            return str(rule.get("action", "alert")).lower()
    return default


def _rule_matches(rule: dict, change: PriceChange) -> bool:
    when = str(rule.get("when", "")).strip().lower()
    amount = _to_float(rule.get("amount", rule.get("value")))
    old, new = _to_float(change.old_value), _to_float(change.new_value)

    if when in ("any", "any_change"):
        return True
    if when in ("new_item",):
        return change.field == "_new_item"
    if when in ("removed_item",):
        return change.field == "_removed_item"

    if change.field == "price":
        if when in ("price_drops", "price_decreases", "price_drop"):
            return old is not None and new is not None and new < old
        if when in ("price_increases", "price_rises"):
            return old is not None and new is not None and new > old
        if when in ("price_drops_below", "price_below") and amount is not None:
            return new is not None and new <= amount
        if when in ("price_rises_above", "price_above") and amount is not None:
            return new is not None and new >= amount

    if change.field == "availability":
        if when == "back_in_stock":
            return is_in_stock(change.new_value) is True
        if when == "out_of_stock":
            return is_in_stock(change.new_value) is False

    return False


_TEMPLATE = """# Crawlr rules \u2014 tell Crawlr what to do in different circumstances.
#
# Each rule has a `when` (the circumstance) and an `action` (alert or ignore).
# Rules are checked top to bottom; the first match wins. If nothing matches,
# `default_action` is used. Delete this file to fall back to per-watch triggers.
#
# Supported `when` values:
#   any_change            - anything changed
#   price_drops           - price went down
#   price_increases       - price went up
#   price_drops_below     - price <= `amount`
#   price_rises_above     - price >= `amount`
#   back_in_stock         - item became available
#   out_of_stock          - item sold out
#   new_item / removed_item

default_action: ignore

rules:
  - when: price_drops_below
    amount: 25
    action: alert

  - when: back_in_stock
    action: alert

  - when: out_of_stock
    action: alert

  - when: price_increases
    action: ignore
"""


def write_template(path=None, overwrite: bool = False) -> tuple[bool, str]:
    """Write the starter rules template. Returns (written, path_or_message)."""
    target = path or config.RULES_FILE
    if target.exists() and not overwrite:
        return False, f"{target} already exists (use --force to overwrite)"
    target.write_text(_TEMPLATE)
    return True, str(target)
