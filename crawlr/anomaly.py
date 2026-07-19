"""Statistical anomaly detection for price series (an accuracy guard).

The plausibility guard catches absurd absolute jumps (e.g. 100x). This adds a
*relative* guard: a price that's a wild outlier versus the item's own history is
almost always an extraction glitch (a coupon field scraped as the price, a
"0", a currency mix-up). We quarantine those so they can't poison alerts or the
recorded price history.

Robustness matters here: we use the median and MAD (median absolute deviation)
rather than mean/standard-deviation, because mean/std are themselves skewed by
the very spikes we're trying to detect.
"""

from __future__ import annotations

from statistics import median

# MAD -> standard-deviation scaling factor for normally distributed data.
_MAD_SCALE = 1.4826


def is_price_outlier(
    value: float | None,
    history: list,
    z_threshold: float = 6.0,
    min_samples: int = 6,
) -> bool:
    """Return True if ``value`` is a robust-z outlier versus prior ``history``.

    Returns False when the guard is disabled (``z_threshold <= 0``), the value is
    missing, or there isn't enough history — we never quarantine on thin data.
    """
    if z_threshold <= 0 or value is None:
        return False
    clean = [
        float(v) for v in history
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    if len(clean) < min_samples:
        return False

    med = median(clean)
    mad = median([abs(v - med) for v in clean])
    if mad == 0:
        # History was perfectly flat: flag only a clearly different value.
        return abs(value - med) > max(1e-9, abs(med) * 0.5)
    robust_z = abs(value - med) / (_MAD_SCALE * mad)
    return robust_z > z_threshold
