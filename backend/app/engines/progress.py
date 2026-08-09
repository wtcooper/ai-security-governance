"""Live progress for a running LLM evaluation.

The eval child writes an Inspect `.eval` log incrementally as samples complete. Reading
that journal is the only ground truth available while a benchmark is mid-flight, so the
progress endpoint reads it rather than inventing a spinner. Benchmarks run sequentially,
which makes the mapping simple: a benchmark is *done* when its score row exists, *running*
when a fresh log file exists for its task, and *queued* otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class CheckProgress:
    check_id: str
    state: str  # "done" | "running" | "queued"
    samples_completed: int | None
    samples_planned: int | None


def _log_matches(path: Path, task_token: str, started_after: float) -> bool:
    return task_token in path.name and path.stat().st_mtime >= started_after


def _completed_samples(path: Path) -> int | None:
    # Lazy import: inspect_ai is heavy, and this endpoint is the API process's only reason
    # to touch it. The log reader parses the journal without running anything.
    try:
        from inspect_ai.log import read_eval_log_sample_summaries

        return len(read_eval_log_sample_summaries(str(path)))
    except Exception:  # noqa: BLE001 - a half-written journal must not 500 the endpoint
        return None


def collect_progress(
    log_dir: Path,
    started_at: datetime,
    ordered_check_ids: list[str],
    planned: dict[str, int],
    scored: set[str],
) -> list[CheckProgress]:
    if started_at.tzinfo is None:
        # SQLite drops timezones; runs store UTC.
        started_at = started_at.replace(tzinfo=UTC)
    started_after = started_at.timestamp()

    log_files = sorted(log_dir.glob("*.eval")) if log_dir.is_dir() else []

    out: list[CheckProgress] = []
    for check_id in ordered_check_ids:
        plan = planned.get(check_id)
        if check_id in scored:
            out.append(CheckProgress(check_id, "done", plan, plan))
            continue
        # Inspect names log files with the task name dash-separated.
        token = check_id.replace("_", "-")
        current = [p for p in log_files if _log_matches(p, token, started_after)]
        if current:
            out.append(
                CheckProgress(check_id, "running", _completed_samples(current[-1]), plan)
            )
        else:
            out.append(CheckProgress(check_id, "queued", None, plan))
    return out
