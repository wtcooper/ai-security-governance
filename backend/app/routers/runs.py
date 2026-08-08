"""Submitting assets for evaluation and reading results."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app import jobs
from app.config import Settings, get_settings
from app.db import get_session
from app.engines import gateway
from app.engines.registry import checks_for
from app.models import Artifact, Asset, AssetType, Finding, Run, Score
from app.scoring import gates
from app.scoring.policy import get_policy

router = APIRouter(tags=["runs"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


class CreateRunRequest(BaseModel):
    asset_type: AssetType
    name: str
    # For an LLM this is a gateway alias; for MCP/skills a repo URL. Never a
    # provider-native model string — the UI offers a dropdown of aliases for exactly this
    # reason.
    identifier: str
    provider: str | None = None
    hf_repo_id: str | None = None
    judge_model: str | None = None
    # Overrides each check's default sample cap. Exists because local judge models are slow
    # (reasoning models emit long traces), so the test suite needs a small, explicit limit
    # rather than silently redefining what a governance run means.
    limit: int | None = None
    # Restrict to specific check ids. Used by the test suite to exercise one benchmark at a
    # time; a real governance run leaves this unset so every gate is evaluated.
    only_checks: list[str] | None = None


class ScoreOut(BaseModel):
    check_id: str
    metric: str
    raw_value: float | None
    normalized: float | None
    direction: str | None
    threshold: float | None
    gated: bool
    passed: bool | None
    provenance: str
    source_url: str | None
    model_used: str | None
    total_samples: int | None
    unresolved_samples: int | None


class FindingOut(BaseModel):
    analyzer: str
    severity: str
    rule_id: str | None
    title: str
    detail: str | None
    file_path: str | None


class GateOut(BaseModel):
    check_id: str
    metric: str
    raw_value: float | None
    threshold: float
    direction: str
    passed: bool
    reason: str
    description: str = ""


class RunOut(BaseModel):
    id: int
    asset_id: int
    asset_name: str
    asset_type: AssetType
    identifier: str
    status: str
    decision: str | None
    decision_reason: str | None
    gateway_model: str | None
    judge_model: str | None
    judge_refusal_rate: float | None
    policy_version: str | None
    policy_hash: str | None
    engine_version: str | None
    ruleset_version: str | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    composite_score: float | None
    # Display only. Never a gate — see scoring/gates.py.
    composite_is_display_only: bool = True
    scores: list[ScoreOut]
    findings: list[FindingOut]
    gate_outcomes: list[GateOut]
    artifacts: list[str]


@router.post("/runs", response_model=RunOut, status_code=201)
async def create_run(
    request: CreateRunRequest,
    settings: SettingsDep,
    session: SessionDep,
) -> RunOut:
    policy = get_policy(settings.policy_path)
    judge = request.judge_model or policy.judge_default_model

    if request.asset_type is not AssetType.LLM:
        raise HTTPException(
            status_code=501,
            detail=(
                f"{request.asset_type.value} evaluation is not implemented yet. "
                "LLM evaluation is available."
            ),
        )

    # Refuse to start an expensive run against a route that does not work. This is the whole
    # reason preflight exists — the historical failure was discovering broken model routing
    # part-way through an eval.
    for role, alias in (("subject", request.identifier), ("judge", judge)):
        result = await gateway.preflight(settings, alias)
        if not result.ok:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Preflight failed for the {role} model {alias!r} — not starting the run. "
                    f"{result.detail}. Upstream said: {result.upstream_error}"
                ),
            )

    asset = Asset(
        type=request.asset_type,
        name=request.name,
        identifier=request.identifier,
        provider=request.provider,
        hf_repo_id=request.hf_repo_id,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    run = Run(asset_id=asset.id, gateway_model=request.identifier, judge_model=judge)
    session.add(run)
    session.commit()
    session.refresh(run)

    await jobs.start_run(run.id, limit=request.limit, only_checks=request.only_checks)
    return _to_run_out(session, run, asset, settings)


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    settings: SettingsDep,
    session: SessionDep,
    asset_type: AssetType | None = None,
    limit: int = 50,
) -> list[RunOut]:
    statement = select(Run, Asset).join(Asset, Asset.id == Run.asset_id)
    if asset_type is not None:
        statement = statement.where(Asset.type == asset_type)
    statement = statement.order_by(Run.started_at.desc()).limit(limit)
    return [_to_run_out(session, run, asset, settings) for run, asset in session.exec(statement)]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, settings: SettingsDep, session: SessionDep) -> RunOut:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    asset = session.get(Asset, run.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"asset for run {run_id} not found")
    return _to_run_out(session, run, asset, settings)


@router.get("/checks", response_model=list[dict])
def list_checks(asset_type: AssetType = AssetType.LLM) -> list[dict]:
    """What this asset class is evaluated on, and how each gate is read."""
    return [
        {
            "id": check.id,
            "metric": check.metric_name,
            "direction": check.direction.value,
            "default_limit": check.default_limit,
            "needs_judge": check.needs_judge,
            "description": check.description,
        }
        for check in checks_for(asset_type)
    ]


def _to_run_out(session: Session, run: Run, asset: Asset, settings: Settings) -> RunOut:
    policy = get_policy(settings.policy_path)
    scores = list(session.exec(select(Score).where(Score.run_id == run.id)))
    findings = list(session.exec(select(Finding).where(Finding.run_id == run.id)))
    artifacts = list(session.exec(select(Artifact).where(Artifact.run_id == run.id)))

    outcome = gates.decide_llm(policy, scores, run.judge_refusal_rate)
    gate_outs = [
        GateOut(
            check_id=g.check_id,
            metric=g.metric,
            raw_value=g.raw_value,
            threshold=g.threshold,
            direction=g.direction,
            passed=g.passed,
            reason=g.reason,
            description=(
                policy.llm_gates[g.check_id].description if g.check_id in policy.llm_gates else ""
            ),
        )
        for g in outcome.gate_outcomes
    ]

    return RunOut(
        id=run.id,
        asset_id=asset.id,
        asset_name=asset.name,
        asset_type=asset.type,
        identifier=asset.identifier,
        status=run.status.value,
        decision=run.decision.value if run.decision else None,
        decision_reason=run.decision_reason,
        gateway_model=run.gateway_model,
        judge_model=run.judge_model,
        judge_refusal_rate=run.judge_refusal_rate,
        policy_version=run.policy_version,
        policy_hash=run.policy_hash,
        engine_version=run.engine_version,
        ruleset_version=run.ruleset_version,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        composite_score=jobs.composite_for_run(session, run.id, policy),
        scores=[
            ScoreOut(
                check_id=s.check_id,
                metric=s.metric,
                raw_value=s.raw_value,
                normalized=s.normalized,
                direction=s.direction.value if s.direction else None,
                threshold=s.threshold,
                gated=s.gated,
                passed=s.passed,
                provenance=s.provenance.value,
                source_url=s.source_url,
                model_used=s.model_used,
                total_samples=s.total_samples,
                unresolved_samples=s.unresolved_samples,
            )
            for s in scores
        ],
        findings=[
            FindingOut(
                analyzer=f.analyzer,
                severity=f.severity.value,
                rule_id=f.rule_id,
                title=f.title,
                detail=f.detail,
                file_path=f.file_path,
            )
            for f in findings
        ],
        gate_outcomes=gate_outs,
        artifacts=[a.path for a in artifacts],
    )
