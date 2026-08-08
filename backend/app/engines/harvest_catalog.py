"""Published-score lookup — the "harvest before compute" first stop.

If a benchmark result is already published for a model, reuse it rather than spending tokens
recomputing it. A harvested score is stored with provenance `published` and its source URL, so
a reviewer can always see whether a number was read from a vendor's own reporting or measured
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PublishedScore:
    model: str
    check_id: str
    metric: str
    value: float
    source_url: str
    captured: str | None = None
    note: str | None = None


@lru_cache
def load_catalog(path: Path) -> tuple[PublishedScore, ...]:
    if not path.exists():
        return ()
    data = yaml.safe_load(path.read_text()) or {}
    entries = data.get("scores") or []
    return tuple(
        PublishedScore(
            model=str(entry["model"]),
            check_id=str(entry["check_id"]),
            metric=str(entry["metric"]),
            value=float(entry["value"]),
            source_url=str(entry["source_url"]),
            captured=entry.get("captured"),
            note=entry.get("note"),
        )
        for entry in entries
    )


def lookup(path: Path, model: str, check_id: str) -> PublishedScore | None:
    """Exact match only.

    Deliberately not fuzzy: `claude-opus-4.5` and `claude-opus-4.5-thinking` are different
    models with different security behaviour, and quietly accepting a near-match would put an
    unmeasured model's approval on another model's evidence.
    """
    for entry in load_catalog(path):
        if entry.model == model and entry.check_id == check_id:
            return entry
    return None
