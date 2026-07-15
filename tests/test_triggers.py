"""Tests for alert triggers + the rules template."""

from __future__ import annotations

from crawlr import config, triggers
from crawlr.models import PriceChange, TriggerType


def _pc(field: str, old, new) -> PriceChange:
    return PriceChange(product_url="p1", field=field, old_value=old, new_value=new)


def test_is_in_stock_parsing():
    assert triggers.is_in_stock("In Stock") is True
    assert triggers.is_in_stock("Out of Stock") is False
    assert triggers.is_in_stock("mystery") is None
    assert triggers.is_in_stock(None) is None


def test_should_alert_any_change():
    assert triggers.should_alert(TriggerType.ANY_CHANGE, None, _pc("price", "10", "9"))
    assert triggers.should_alert(TriggerType.ANY_CHANGE, None, _pc("availability", "a", "b"))


def test_should_alert_price_drop():
    assert triggers.should_alert(TriggerType.PRICE_DROP, None, _pc("price", "10", "9"))
    assert not triggers.should_alert(TriggerType.PRICE_DROP, None, _pc("price", "10", "12"))


def test_should_alert_price_below_target():
    assert triggers.should_alert(TriggerType.PRICE_BELOW, 25, _pc("price", "30", "24"))
    assert not triggers.should_alert(TriggerType.PRICE_BELOW, 25, _pc("price", "30", "26"))


def test_should_alert_back_in_stock():
    assert triggers.should_alert(
        TriggerType.BACK_IN_STOCK, None, _pc("availability", "Out of stock", "In stock")
    )
    assert not triggers.should_alert(
        TriggerType.BACK_IN_STOCK, None, _pc("availability", "In stock", "Out of stock")
    )


def test_filter_changes_uses_site_trigger():
    site = {"alert_trigger": "price_drop", "target_price": None}
    changes = [_pc("price", "10", "9"), _pc("price", "9", "12"), _pc("availability", "x", "y")]
    out = triggers.filter_changes(site, changes)
    assert len(out) == 1 and out[0].new_value == "9"


def test_rules_template_overrides_trigger():
    config.RULES_FILE.write_text(
        "default_action: ignore\n"
        "rules:\n"
        "  - when: price_drops_below\n"
        "    amount: 25\n"
        "    action: alert\n"
    )
    site = {"alert_trigger": "any_change", "target_price": None}
    changes = [_pc("price", "30", "20"), _pc("price", "30", "27")]
    out = triggers.filter_changes(site, changes)
    assert len(out) == 1 and out[0].new_value == "20"


def test_write_template_is_idempotent():
    written, _ = triggers.write_template()
    assert written and config.RULES_FILE.exists()
    written_again, _ = triggers.write_template()
    assert not written_again  # refuses to overwrite without force
