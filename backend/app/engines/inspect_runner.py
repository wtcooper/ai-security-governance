"""Spawns the Inspect child process and parses its result."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.engines.inspect_child import scrub_provider_credentials


@dataclass(frozen=True)
class EvalResult:
    ok: bool
    payload: dict[str, Any]
    stderr: str


def build_child_env(settings: Settings) -> dict[str, str]:
    """The child's environment: the gateway pair, and no provider credentials.

    Inspect resolves `openai-api/<provider>/<alias>` by reading `<PROVIDER>_BASE_URL` and
    `<PROVIDER>_API_KEY`. We set exactly that pair, which is why the same mechanism covers
    the subject model and every judge model without special-casing either.
    """
    env = scrub_provider_credentials(dict(os.environ))
    provider = settings.gateway_provider.upper().replace("-", "_")
    env[f"{provider}_BASE_URL"] = settings.gateway_base_url
    env[f"{provider}_API_KEY"] = settings.gateway_api_key
    return env


def build_eval_argv(
    settings: Settings,
    task: str,
    model_alias: str,
    judge_alias: str | None,
    limit: int | None,
    sample_ids: tuple[str, ...],
    log_dir: str,
) -> list[str]:
    """The child's argv, as a pure function so tests can hold it to the policy's word."""
    argv = [
        sys.executable,
        "-m",
        "app.engines.inspect_child",
        "--task",
        task,
        "--model",
        settings.inspect_model_string(model_alias),
        "--log-dir",
        log_dir,
    ]
    if judge_alias:
        argv += ["--judge-model", settings.inspect_model_string(judge_alias)]
    if limit is not None:
        argv += ["--limit", str(limit)]
    # A fixed core set: the policy names exact dataset sample ids, and the run executes
    # those and nothing else. Mutually exclusive with --limit by construction in jobs.py.
    for sample_id in sample_ids:
        argv += ["--sample-id", sample_id]
    return argv


async def run_eval(
    settings: Settings,
    task: str,
    model_alias: str,
    judge_alias: str | None = None,
    limit: int | None = None,
    sample_ids: tuple[str, ...] = (),
    timeout: float = 900.0,
) -> EvalResult:
    log_dir = settings.artifact_dir / "inspect-logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    argv = build_eval_argv(
        settings, task, model_alias, judge_alias, limit, sample_ids, str(log_dir)
    )

    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=build_child_env(settings),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return EvalResult(
            ok=False,
            payload={"status": "error", "error": f"eval exceeded {timeout}s and was killed"},
            stderr="",
        )

    text = stdout.decode().strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return EvalResult(
            ok=False,
            payload={
                "status": "error",
                "error": "child did not emit JSON",
                "stdout": text[-2000:],
            },
            stderr=stderr.decode()[-2000:],
        )

    return EvalResult(
        ok=process.returncode == 0 and payload.get("status") == "success",
        payload=payload,
        stderr=stderr.decode()[-2000:],
    )
