"""Accuracy regression gate: golden-fixture extraction must stay accurate.

Runs in the normal pytest suite (and therefore CI), so extraction accuracy
can't silently degrade as the engine evolves.
"""

from __future__ import annotations

import pytest

from crawlr.eval import run_eval

MIN_ACCURACY = 0.9


def test_extraction_accuracy_gate():
    result = run_eval()
    if result["checks"] == 0:
        pytest.skip("no golden cases defined")
    assert result["accuracy"] >= MIN_ACCURACY, result["failures"]
