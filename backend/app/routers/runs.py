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
from app.models import Artifact, Asset, AssetType, Finding, Run, RunStatus, Score
from app.scoring import gates
from app.scoring.policy import get_active_policy

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
    # Overrides the policy's per-benchmark sample counts for THIS run only. A development
    # facility (local judge models are slow), recorded on the run and flagged in the UI so
    # a wiring check can never be mistaken for a governance run. Absent means the policy's
    # counts (or fixed core sets) apply — which is the governed default.
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
    # Set when the submitter overrode the policy's sample counts. Flagged in the UI.
    sample_override: int | None = None
    judge_unresolved_rate: float | None
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
    policy = get_active_policy(session)
    judge = request.judge_model or policy.judge_default_model

    # Refuse to start an expensive run against a route that does not work. This is the whole
    # reason preflight exists — the historical failure was discovering broken model routing
    # part-way through an eval.
    #
    # For scanner-backed assets only the analyzer model is exercised; there is no subject
    # model, because the artifact under test is code rather than a model.
    if request.asset_type is AssetType.LLM:
        to_check = (("subject", request.identifier), ("judge", judge))
    else:
        to_check = (("scanner analyzer", settings.scanner_model),)

    for role, alias in to_check:
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
        source_url=request.identifier if request.asset_type is not AssetType.LLM else None,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    run = Run(
        asset_id=asset.id,
        gateway_model=request.identifier if request.asset_type is AssetType.LLM else None,
        judge_model=judge if request.asset_type is AssetType.LLM else settings.scanner_model,
        sample_override=request.limit if request.asset_type is AssetType.LLM else None,
    )
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
def list_checks(session: SessionDep, asset_type: AssetType = AssetType.LLM) -> list[dict]:
    """What this asset class is evaluated on, and how each gate is read."""
    policy = get_active_policy(session)
    out = []
    for check in checks_for(asset_type):
        gate = policy.llm_gates.get(check.id)
        out.append(
            {
                "id": check.id,
                "metric": check.metric_name,
                "direction": check.direction.value,
                "needs_judge": check.needs_judge,
                "description": check.description,
                # From the policy, because the policy is what controls a run.
                "planned_samples": gate.planned_samples if gate else check.default_limit,
                "uses_core_set": bool(gate and gate.sample_ids),
                "threshold": gate.threshold if gate else None,
            }
        )
    return out


@router.get("/runs/{run_id}/progress", response_model=dict)
def run_progress(run_id: int, settings: SettingsDep, session: SessionDep) -> dict:
    """Per-benchmark progress for a running LLM run, read from the live eval journal."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    asset = session.get(Asset, run.asset_id)

    if asset is None or asset.type is not AssetType.LLM:
        return {"status": run.status.value, "benchmarks": []}

    from app.engines.progress import collect_progress

    policy = get_active_policy(session)
    checks = checks_for(AssetType.LLM)
    planned: dict[str, int] = {}
    for check in checks:
        gate = policy.llm_gates.get(check.id)
        if run.sample_override is not None:
            planned[check.id] = run.sample_override
        elif gate is not None:
            planned[check.id] = gate.planned_samples
        else:
            planned[check.id] = check.default_limit

    scored = {
        score.check_id
        for score in session.exec(select(Score).where(Score.run_id == run_id))
        if score.gated or score.check_id in planned
    }
    progress = collect_progress(
        log_dir=settings.artifact_dir / "inspect-logs",
        started_at=run.started_at,
        ordered_check_ids=[check.id for check in checks],
        planned=planned,
        scored=scored,
    )
    return {
        "status": run.status.value,
        "sample_override": run.sample_override,
        "benchmarks": [
            {
                "check_id": p.check_id,
                "state": p.state if run.status is RunStatus.RUNNING else "done",
                "samples_completed": p.samples_completed,
                "samples_planned": p.samples_planned,
            }
            for p in progress
        ],
    }


def _run_policy(session: Session, run: Run, asset: Asset):
    """The policy to interpret this run under.

    Gate outcomes are recomputed at read time, so they must come from the policy version the
    run actually recorded — otherwise editing a threshold would silently rewrite the meaning
    of every historical run on screen. Falls back to the active policy when the recorded
    version cannot be resolved (runs that predate policy versioning)."""
    from app.scoring import policy as policy_store
    from app.scoring.policy import build_policy

    active = get_active_policy(session)
    if not run.policy_version or not run.policy_version.isdigit():
        return active
    row = policy_store.get_version(session, asset.type, int(run.policy_version))
    if row is None or row.content_hash != run.policy_hash:
        return active
    docs = {
        asset_type: (
            (row.content, str(row.version))
            if asset_type is asset.type
            else (policy_store.newest_version(session, asset_type).content, "current")
        )
        for asset_type in AssetType
    }
    try:
        return build_policy(docs)
    except Exception:  # noqa: BLE001 - a historical doc must never 500 the run page
        return active


def _to_run_out(session: Session, run: Run, asset: Asset, settings: Settings) -> RunOut:
    policy = _run_policy(session, run, asset)
    scores = list(session.exec(select(Score).where(Score.run_id == run.id)))
    findings = list(session.exec(select(Finding).where(Finding.run_id == run.id)))
    artifacts = list(session.exec(select(Artifact).where(Artifact.run_id == run.id)))

    # Benchmark gates only apply to LLMs. Scanner-backed assets are judged on a severity
    # rule, so presenting them as unmet benchmark gates would be actively misleading.
    outcome = (
        gates.decide_llm(policy, scores, run.judge_unresolved_rate)
        if asset.type is AssetType.LLM
        else gates.DecisionResult(decision=run.decision or gates.Decision.ERROR, reason="")
    )
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
        sample_override=run.sample_override,
        judge_unresolved_rate=run.judge_unresolved_rate,
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
