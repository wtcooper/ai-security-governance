"""Child process that loads a benchmark's dataset and writes a preview JSON.

Runs as `python -m app.engines.dataset_preview`, never in the API process — building a task
imports the heavy eval packages and may download the dataset on first use. It is launched
with the same scrubbed environment as the eval child: loading a dataset performs no model
calls, so it needs no credentials of any kind, and giving it none keeps that true.

The preview is what the benchmark pages show (real example test cases, dataset size,
strata) and what core-set selection draws from (the full id list with stratum labels).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# How many example test cases the page shows. Enough to convey what the benchmark asks;
# few enough that the payload stays a page, not a dump.
EXAMPLE_COUNT = 6
INPUT_TRUNCATE = 600
TARGET_TRUNCATE = 300
METADATA_TRUNCATE = 200


def _sample_input_text(sample: Any) -> str:
    """A sample's input as displayable text. Inputs are either a string or a message list."""
    raw = getattr(sample, "input", "")
    if isinstance(raw, str):
        return raw
    parts: list[str] = []
    for message in raw or []:
        role = getattr(message, "role", "?")
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            content = str(content)
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


def _truncate(text: str, length: int) -> str:
    text = text.strip()
    return text if len(text) <= length else text[: length - 1] + "…"


def build_preview(check_id: str) -> dict[str, Any]:
    from app.engines.registry import get_check

    check = get_check(check_id)

    import importlib

    builder = getattr(importlib.import_module(check.module), check.function)
    kwargs = dict(check.task_kwargs)
    for arg in check.model_kwargs:
        # Building a task object loads its dataset without calling any model, so a
        # placeholder satisfies the signature and can never be exercised here.
        kwargs[arg] = "openai-api/gateway/preview-only-never-called"
    task = builder(**kwargs)

    dataset = task.dataset
    ids: list[str] = []
    id_strata: dict[str, str] = {}
    metadata_keys: set[str] = set()
    strata_counts: dict[str, int] = {}
    examples: list[dict[str, Any]] = []

    for sample in dataset:
        sample_id = str(sample.id)
        ids.append(sample_id)
        metadata = getattr(sample, "metadata", None) or {}
        metadata_keys.update(metadata.keys())

        if check.strata_key:
            stratum = str(metadata.get(check.strata_key, "unknown"))
            id_strata[sample_id] = stratum
            strata_counts[stratum] = strata_counts.get(stratum, 0) + 1

        if len(examples) < EXAMPLE_COUNT:
            target = getattr(sample, "target", "")
            examples.append(
                {
                    "id": sample_id,
                    "input": _truncate(_sample_input_text(sample), INPUT_TRUNCATE),
                    "target": _truncate(
                        target if isinstance(target, str) else str(target), TARGET_TRUNCATE
                    ),
                    "metadata": {
                        key: _truncate(str(value), METADATA_TRUNCATE)
                        for key, value in metadata.items()
                    },
                }
            )

    return {
        "check_id": check_id,
        "built_at": datetime.now(UTC).isoformat(),
        "total_samples": len(ids),
        "strata_key": check.strata_key,
        "strata": dict(sorted(strata_counts.items(), key=lambda kv: -kv[1])),
        "metadata_keys": sorted(metadata_keys),
        "examples": examples,
        # Everything below is for core-set selection, not display.
        "ids": ids,
        "id_strata": id_strata,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a benchmark dataset preview.")
    parser.add_argument("--check", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        preview = build_preview(args.check)
    except Exception as exc:  # noqa: BLE001 - surfaced as JSON to the parent
        print(
            json.dumps({"check_id": args.check, "error": f"{type(exc).__name__}: {exc}"}),
            file=sys.stdout,
        )
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(preview, indent=2))
    print(json.dumps({"check_id": args.check, "total_samples": preview["total_samples"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
