"""Benchmark transparency: what each benchmark is, what its test cases look like, and
proposing fixed core sample sets.

The dataset preview is built by a subprocess (`app.engines.dataset_preview`) with the same
scrubbed environment as the eval child — loading a dataset performs no model calls — and
cached under the artifact directory. Core-set proposals are computed from that cache, so
proposing is instant and deterministic once the preview exists.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.engines.inspect_runner import build_child_env
from app.engines.registry import CHECKS_BY_ID, LLM_CHECKS
from app.scoring.core_set import propose_core_set
from app.scoring.policy import get_active_policy

router = APIRouter(tags=["benchmarks"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]

PREVIEW_BUILD_TIMEOUT = 600.0


def _preview_path(settings: Settings, check_id: str):
    return settings.artifact_dir / "benchmark-previews" / f"{check_id}.json"


def _load_preview(settings: Settings, check_id: str) -> dict[str, Any] | None:
    path = _preview_path(settings, check_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _display_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """The preview minus the full id list, which is selection input rather than reading."""
    return {k: v for k, v in preview.items() if k not in ("ids", "id_strata")}


def _benchmark_out(check, policy, preview: dict[str, Any] | None) -> dict[str, Any]:
    gate = policy.llm_gates.get(check.id)
    return {
        "id": check.id,
        "description": check.description,
        "intent": check.intent,
        "metric": check.metric_name,
        "direction": check.direction.value,
        "needs_judge": check.needs_judge,
        "strata_key": check.strata_key,
        "gate": (
            {
                "threshold": gate.threshold,
                "samples": gate.samples,
                "sample_ids_count": len(gate.sample_ids),
                "uses_core_set": bool(gate.sample_ids),
            }
            if gate
            else None
        ),
        "composite_weight": policy.composite_weights.get(check.id),
        "dataset_total": preview.get("total_samples") if preview else None,
        "preview_available": preview is not None,
    }


@router.get("/benchmarks")
def list_benchmarks(settings: SettingsDep, session: SessionDep) -> list[dict[str, Any]]:
    policy = get_active_policy(session)
    return [
        _benchmark_out(check, policy, _load_preview(settings, check.id))
        for check in LLM_CHECKS
    ]


@router.get("/benchmarks/{check_id}")
def get_benchmark(check_id: str, settings: SettingsDep, session: SessionDep) -> dict[str, Any]:
    check = CHECKS_BY_ID.get(check_id)
    if check is None:
        raise HTTPException(status_code=404, detail=f"unknown benchmark {check_id!r}")
    policy = get_active_policy(session)
    preview = _load_preview(settings, check_id)
    out = _benchmark_out(check, policy, preview)
    out["preview"] = _display_preview(preview) if preview else None
    gate = policy.llm_gates.get(check_id)
    out["active_sample_ids"] = list(gate.sample_ids) if gate else []
    return out


@router.post("/benchmarks/{check_id}/preview")
async def build_preview(
    check_id: str, settings: SettingsDep, session: SessionDep
) -> dict[str, Any]:
    """Build (or rebuild) the dataset preview. Slow on first use: may download the dataset."""
    check = CHECKS_BY_ID.get(check_id)
    if check is None:
        raise HTTPException(status_code=404, detail=f"unknown benchmark {check_id!r}")

    out_path = _preview_path(settings, check_id)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.engines.dataset_preview",
        "--check",
        check_id,
        "--out",
        str(out_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=build_child_env(settings),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=PREVIEW_BUILD_TIMEOUT
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise HTTPException(
            status_code=504,
            detail=f"preview build exceeded {PREVIEW_BUILD_TIMEOUT:.0f}s and was killed",
        ) from None

    if process.returncode != 0:
        detail = "preview build failed"
        try:
            detail = json.loads(stdout.decode().strip()).get("error", detail)
        except (json.JSONDecodeError, AttributeError):
            detail = (stderr.decode()[-500:] or detail).strip()
        # Deliberately NOT cached: a transient failure must not masquerade as a permanent
        # "preview unavailable".
        raise HTTPException(status_code=502, detail=detail)

    preview = _load_preview(settings, check_id)
    if preview is None:
        raise HTTPException(status_code=502, detail="preview build wrote no readable output")
    policy = get_active_policy(session)
    out = _benchmark_out(check, policy, preview)
    out["preview"] = _display_preview(preview)
    return out


class CoreSetRequest(BaseModel):
    size: int = Field(ge=1, le=5000)
    # A seed phrase, recorded in the YAML snippet so the draw is reproducible by anyone.
    seed: str = "governance-v1"


@router.post("/benchmarks/{check_id}/core-set")
def propose(
    check_id: str, request: CoreSetRequest, settings: SettingsDep
) -> dict[str, Any]:
    """Propose a stratified, seeded core set. Adopting it is a policy edit, done elsewhere."""
    check = CHECKS_BY_ID.get(check_id)
    if check is None:
        raise HTTPException(status_code=404, detail=f"unknown benchmark {check_id!r}")
    preview = _load_preview(settings, check_id)
    if preview is None:
        raise HTTPException(
            status_code=409,
            detail="no dataset preview yet — build the preview first, then propose",
        )

    try:
        proposal = propose_core_set(
            ids=preview.get("ids") or [],
            id_strata=preview.get("id_strata") or {},
            size=request.size,
            seed=request.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    id_lines = "\n".join(f"      - {sample_id}" for sample_id in proposal.sample_ids)
    yaml_snippet = (
        f"    # Core set: n={proposal.size}, seed={proposal.seed!r}, "
        f"stratified by {check.strata_key or 'nothing (single stratum)'}\n"
        f"    sample_ids:\n{id_lines}"
    )
    return {
        "check_id": check_id,
        "size": proposal.size,
        "seed": proposal.seed,
        "sample_ids": proposal.sample_ids,
        "allocation": {
            stratum: {"selected": sel, "available": avail}
            for stratum, (sel, avail) in proposal.allocation.items()
        },
        # Paste-ready: replaces the gate's `samples:` line in the LLM policy editor.
        "yaml_snippet": yaml_snippet,
    }
