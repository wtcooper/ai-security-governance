"""Turning raw metrics into the 0-100 numbers shown in the UI.

Normalization is for **display and ordering only**. Gates always compare the raw value
against the raw threshold (see `gates.py`), so a rounding choice here can never move a
governance decision.
"""

from __future__ import annotations

from app.models import Direction, Severity


def normalize_metric(raw_value: float, direction: Direction) -> float:
    """Map a 0-1 rate onto a 0-100 "better is higher" scale.

    Lower-is-better metrics are inverted so the leaderboard reads consistently: 100 is always
    the good end, whichever direction the underlying metric runs.
    """
    clamped = min(max(raw_value, 0.0), 1.0)
    if direction is Direction.LOWER_IS_BETTER:
        clamped = 1.0 - clamped
    return round(clamped * 100, 1)


def severity_rollup(
    counts: dict[Severity, int],
    penalty: dict[Severity, int],
) -> float:
    """Collapse scanner findings into one orderable number.

    This is NOT a safety measurement and must never be thresholded. Scanner findings have no
    fixed denominator — the count tracks how much code there is and what it does — so the
    result is only meaningful for sorting one artifact against another in a list.
    """
    total_penalty = sum(penalty.get(sev, 0) * count for sev, count in counts.items())
    return round(max(0.0, 100.0 - min(100.0, total_penalty)), 1)


def composite_score(
    normalized_by_check: dict[str, float],
    weights: dict[str, float],
) -> float | None:
    """Weighted mean of the normalized benchmark scores, over whatever is present.

    Returns None when nothing scored. Re-normalizing over present checks means a partial run
    still produces a sensible display number — but because the composite is never a gate, a
    partial run still cannot be approved (see `gates.py`).
    """
    usable = {k: v for k, v in normalized_by_check.items() if k in weights}
    if not usable:
        return None
    total_weight = sum(weights[k] for k in usable)
    if total_weight <= 0:
        return None
    weighted = sum(normalized_by_check[k] * weights[k] for k in usable)
    return round(weighted / total_weight, 1)
