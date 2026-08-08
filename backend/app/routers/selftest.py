"""Real end-to-end self-tests of the compute path.

These endpoints run actual Inspect AI evals against actual models through the configured
gateway. They exist because a mocked test of this path proves nothing: the failure modes
that matter (model string not resolving, judge routing escaping to a real provider, the
gateway not speaking OpenAI shape) only appear on a real round trip.

Defaults are local Ollama aliases so running them costs nothing.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.engines import inspect_runner

router = APIRouter(tags=["selftest"], prefix="/selftest")

SettingsDep = Annotated[Settings, Depends(get_settings)]


class InspectSelftestRequest(BaseModel):
    # Local by default: all routine testing should be free.
    model: str = "gemma4"
    judge_model: str = "qwen35"
    # Whether to also exercise the model-graded path, which is where judge routing breaks.
    include_judge: bool = True


class InspectSelftestResult(BaseModel):
    task: str
    ok: bool
    payload: dict[str, Any]
    stderr: str | None = None


class InspectSelftestResponse(BaseModel):
    ok: bool
    base_url: str
    subject_model: str
    judge_model: str | None
    results: list[InspectSelftestResult]


@router.post("/inspect", response_model=InspectSelftestResponse)
async def inspect_selftest(
    request: InspectSelftestRequest, settings: SettingsDep
) -> InspectSelftestResponse:
    """Run real evals: generation-only, then model-graded through the same gateway."""
    plan: list[tuple[str, str | None]] = [("gateway_selftest", None)]
    if request.include_judge:
        plan.append(("gateway_judge_selftest", request.judge_model))

    results: list[InspectSelftestResult] = []
    for task, judge in plan:
        outcome = await inspect_runner.run_eval(
            settings,
            task=task,
            model_alias=request.model,
            judge_alias=judge,
        )
        results.append(
            InspectSelftestResult(
                task=task,
                ok=outcome.ok,
                payload=outcome.payload,
                stderr=outcome.stderr or None,
            )
        )

    return InspectSelftestResponse(
        ok=all(result.ok for result in results),
        base_url=settings.gateway_base_url,
        subject_model=request.model,
        judge_model=request.judge_model if request.include_judge else None,
        results=results,
    )
