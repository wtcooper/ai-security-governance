"""Child process that runs Inspect AI evals.

Runs as `python -m app.engines.inspect_child`, never in the API process. Three reasons:

1. **Env isolation.** The child is launched with every provider API key stripped, so a task
   whose grader defaults to a hardcoded `openai/gpt-4o-mini` fails loudly instead of
   silently calling a real provider on someone's card. That default is the specific failure
   mode this project has hit before.
2. **Resource isolation.** Evals are long and memory-hungry; a crash must not take the API
   down.
3. **Debuggability.** It runs standalone from a shell, so gateway wiring can be diagnosed
   without the web app in the loop.

Output is a single JSON document on stdout (`--out` to also write a file), so the parent
never has to parse Inspect's display output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Provider credentials that must never reach an eval. Anything routed anywhere other than
# our gateway is a bug, and failing loudly is the point.
SCRUBBED_ENV_PREFIXES = ("OPENAI_", "ANTHROPIC_", "GOOGLE_", "GEMINI_", "AZURE_", "AWS_")
SCRUBBED_ENV_EXACT = ("HF_TOKEN", "MISTRAL_API_KEY", "COHERE_API_KEY", "GROQ_API_KEY")


def scrub_provider_credentials(env: dict[str, str]) -> dict[str, str]:
    """Strip provider credentials, keeping the gateway's own GATEWAY_* pair."""
    cleaned = {}
    for key, value in env.items():
        if key.startswith("GATEWAY_"):
            cleaned[key] = value
            continue
        if key in SCRUBBED_ENV_EXACT:
            continue
        if any(key.startswith(prefix) for prefix in SCRUBBED_ENV_PREFIXES) and key.endswith(
            ("_API_KEY", "_TOKEN", "_ACCESS_KEY_ID", "_SECRET_ACCESS_KEY")
        ):
            continue
        cleaned[key] = value
    return cleaned


def _gateway_selftest_task():
    """A tiny real eval used to prove gateway routing end to end.

    Deliberately not a mock: it performs actual generations against the configured subject
    model and, when a judge is supplied, actually grades one sample through the judge. It
    needs no dataset download, so it can run in CI and on a fresh checkout.
    """
    from inspect_ai import Task
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import includes
    from inspect_ai.solver import generate

    return Task(
        name="gateway_selftest",
        dataset=[
            Sample(input="Reply with exactly one word: ready", target="ready"),
            Sample(input="What is 2+2? Reply with only the number.", target="4"),
        ],
        solver=generate(),
        scorer=includes(),
    )


def _gateway_judge_selftest_task(judge_model: str):
    """Same idea, but exercises the model-graded path — where judge routing breaks."""
    from inspect_ai import Task
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import model_graded_qa
    from inspect_ai.solver import generate

    return Task(
        name="gateway_judge_selftest",
        dataset=[Sample(input="Name the capital of France. One word.", target="Paris")],
        solver=generate(),
        scorer=model_graded_qa(model=judge_model),
    )


BUILTIN_TASKS = {"gateway_selftest", "gateway_judge_selftest"}

# Phrases that mean the judge declined to grade rather than delivering a verdict. A refusal
# parsed as "the subject did not comply" INFLATES refusal-style metrics and can turn a
# failing model into an auto-approval, so these samples are counted separately and never
# treated as passes.
JUDGE_REFUSAL_MARKERS = (
    "i can't help",
    "i cannot help",
    "i can't assist",
    "i cannot assist",
    "i can't provide",
    "i cannot provide",
    "i won't",
    "i will not",
    "i'm unable",
    "i am unable",
    "i must decline",
    "i'm not able to",
    "as an ai",
    "against my guidelines",
    "violates my",
    "i'm sorry, but i can",
)


def _build_task(task_name: str, judge_model: str | None):
    if task_name == "gateway_selftest":
        return _gateway_selftest_task()
    if task_name == "gateway_judge_selftest":
        if not judge_model:
            raise ValueError("gateway_judge_selftest requires --judge-model")
        return _gateway_judge_selftest_task(judge_model)
    return _build_registry_task(task_name, judge_model)


def _build_registry_task(check_id: str, judge_model: str | None):
    """Build a registered governance benchmark, with every model argument overridden."""
    import importlib

    from app.engines.registry import get_check

    check = get_check(check_id)
    builder = getattr(importlib.import_module(check.module), check.function)

    kwargs = dict(check.task_kwargs)
    for arg in check.model_kwargs:
        if not judge_model:
            raise ValueError(
                f"check {check_id!r} requires a judge: task arg {arg!r} would otherwise fall "
                "back to a hardcoded provider default"
            )
        kwargs[arg] = judge_model
    return builder(**kwargs)


def _judge_refusal_rate(log: Any) -> tuple[float | None, int]:
    """Fraction of scored samples where the judge declined to grade.

    Model-graded scorers put the judge's own response in `score.explanation`, which is the
    only place a refusal is visible: a refusal usually produces a confident-looking INCORRECT
    rather than an error, so counting errors alone would miss it entirely.
    """
    samples = getattr(log, "samples", None)
    if not samples:
        return None, 0

    refused = 0
    considered = 0
    for sample in samples:
        for score in (getattr(sample, "scores", None) or {}).values():
            explanation = (getattr(score, "explanation", None) or "").strip().lower()
            if not explanation:
                continue
            considered += 1
            if any(marker in explanation for marker in JUDGE_REFUSAL_MARKERS):
                refused += 1
    if considered == 0:
        return None, 0
    return round(refused / considered, 4), refused


def run(
    task_name: str,
    model: str,
    judge_model: str | None,
    limit: int | None,
    log_dir: str,
) -> dict[str, Any]:
    from inspect_ai import eval as inspect_eval

    task = _build_task(task_name, judge_model)

    # Roles are belt-and-braces alongside the task kwargs: a scorer can resolve `grader` or
    # `expander` without exposing a task argument, and either route left unset falls back to
    # a hardcoded provider model.
    model_roles: dict[str, str] = {}
    if judge_model:
        roles: tuple[str, ...] = ("grader", "expander")
        if task_name not in BUILTIN_TASKS:
            from app.engines.registry import get_check

            roles = get_check(task_name).model_roles or roles
        model_roles = {role: judge_model for role in roles}

    logs = inspect_eval(
        task,
        model=model,
        limit=limit,
        log_dir=log_dir,
        display="none",
        **({"model_roles": model_roles} if model_roles else {}),
    )
    log = logs[0]

    metrics: dict[str, float] = {}
    if log.results:
        for scorer in log.results.scores:
            for metric_name, metric in scorer.metrics.items():
                metrics[f"{scorer.name}.{metric_name}"] = metric.value

    total = getattr(log.results, "total_samples", None) if log.results else None
    completed = getattr(log.results, "completed_samples", None) if log.results else None
    refusal_rate, refused_count = _judge_refusal_rate(log)

    return {
        "task": task_name,
        "status": log.status,
        "model": model,
        "judge_model": judge_model,
        "metrics": metrics,
        "total_samples": total,
        "completed_samples": completed,
        # Samples that produced no score at all. Reported so a partially-failed run is
        # visible rather than silently averaged over fewer samples.
        "unresolved_samples": (total - completed) if (total and completed is not None) else None,
        # Samples the judge declined to grade, detected from the judge's own response text.
        "judge_refusal_rate": refusal_rate,
        "judge_refusal_count": refused_count,
        "error": str(log.error) if log.error else None,
        "log_path": getattr(log, "location", None),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an Inspect AI eval through the gateway.")
    parser.add_argument("--task", required=True, help=f"one of {sorted(BUILTIN_TASKS)}")
    parser.add_argument(
        "--model",
        required=True,
        help="full Inspect model string, e.g. openai-api/gateway/gemma4",
    )
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--out", default=None, help="also write the result JSON here")
    args = parser.parse_args(argv)

    if not os.environ.get("GATEWAY_BASE_URL"):
        print(
            json.dumps({"status": "error", "error": "GATEWAY_BASE_URL is not set"}),
            file=sys.stdout,
        )
        return 2

    try:
        result = run(args.task, args.model, args.judge_model, args.limit, args.log_dir)
    except Exception as exc:  # noqa: BLE001 - surfaced as JSON to the parent
        result = {"task": args.task, "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    payload = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload)
    print(payload)
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
