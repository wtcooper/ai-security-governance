"""Leaderboard: latest decision per asset, ordered for scanning at a glance."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app import jobs
from app.config import Settings, get_settings
from app.db import get_session
from app.models import Asset, AssetType, Run, RunStatus, Score
from app.scoring.policy import policy_for_run

router = APIRouter(tags=["leaderboard"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


class LeaderboardGate(BaseModel):
    check_id: str
    metric: str
    raw_value: float | None
    threshold: float | None
    direction: str | None
    passed: bool | None
    provenance: str
    total_samples: int | None


class LeaderboardRow(BaseModel):
    run_id: int
    asset_name: str
    asset_type: AssetType
    identifier: str
    status: str
    decision: str | None
    decision_reason: str | None
    # Weighted mean of the gated benchmark scores. Shown because it is a useful summary;
    # explicitly not the gate, which is why the flag travels with it.
    composite_score: float | None
    composite_is_display_only: bool = True
    judge_model: str | None
    judge_unresolved_rate: float | None
    judge_refusal_rate: float | None
    policy_version: str | None
    gates_passed: int
    gates_total: int
    # The smallest and largest sample counts behind the gated scores. Surfaced because a
    # score over 2 samples must not read like a score over 1,000.
    samples_min: int | None
    samples_max: int | None
    sample_override: int | None
    started_at: datetime
    finished_at: datetime | None
    gates: list[LeaderboardGate]


@router.get("/leaderboard/{asset_type}", response_model=list[LeaderboardRow])
def leaderboard(
    asset_type: AssetType,
    settings: SettingsDep,
    session: SessionDep,
    limit: int = 100,
) -> list[LeaderboardRow]:
    statement = (
        select(Run, Asset)
        .join(Asset, Asset.id == Run.asset_id)
        .where(Asset.type == asset_type)
        .order_by(Run.started_at.desc())
        .limit(limit)
    )

    rows: list[LeaderboardRow] = []
    for run, asset in session.exec(statement):
        # Each row is interpreted under the policy that governed ITS run, not the active one:
        # otherwise adding a benchmark to the suite would retroactively change the gate
        # denominator and composite of every historical evaluation in this table.
        run_policy = policy_for_run(session, run, asset)
        scores = list(session.exec(select(Score).where(Score.run_id == run.id)))
        gated = [s for s in scores if s.gated]
        sample_counts = [s.total_samples for s in gated if s.total_samples is not None]

        # Scanner-backed classes have no benchmark composite; their ordering number is the
        # severity roll-up recorded on the run. Reading it here is what makes the column
        # match what the page says it shows — it was previously always empty for them.
        if asset.type is AssetType.LLM:
            score_value = jobs.composite_for_run(session, run.id, run_policy)
        else:
            rollup = next(
                (s for s in scores if s.check_id == f"{asset.type.value}.severity_rollup"),
                None,
            )
            score_value = rollup.raw_value if rollup else None
        rows.append(
            LeaderboardRow(
                run_id=run.id,
                asset_name=asset.name,
                asset_type=asset.type,
                identifier=asset.identifier,
                status=run.status.value,
                decision=run.decision.value if run.decision else None,
                decision_reason=run.decision_reason,
                composite_score=score_value,
                judge_model=run.judge_model,
                judge_unresolved_rate=run.judge_unresolved_rate,
                judge_refusal_rate=run.judge_refusal_rate,
                policy_version=run.policy_version,
                gates_passed=sum(1 for s in gated if s.passed),
                # Denominator is the policy's gate count, not the number of scores recorded:
                # "3 of 5" must stay visible when two checks never produced a score.
                gates_total=len(run_policy.gates_for(asset_type)) or len(gated),
                samples_min=min(sample_counts) if sample_counts else None,
                samples_max=max(sample_counts) if sample_counts else None,
                sample_override=run.sample_override,
                started_at=run.started_at,
                finished_at=run.finished_at,
                gates=[
                    LeaderboardGate(
                        check_id=s.check_id,
                        metric=s.metric,
                        raw_value=s.raw_value,
                        threshold=s.threshold,
                        direction=s.direction.value if s.direction else None,
                        passed=s.passed,
                        provenance=s.provenance.value,
                        total_samples=s.total_samples,
                    )
                    for s in gated
                ],
            )
        )
    return rows


@router.get("/stats/severity")
def severity_stats(session: SessionDep) -> dict[str, object]:
    """Finding distribution by analyzer and severity.

    This is the evidence for hand-tuning the MCP/skill severity rule. Without a calibration
    corpus, deciding whether `block_on: [critical, high]` is workable or just noisy means
    looking at what real submissions actually produce.
    """
    from app.models import Finding

    findings = list(session.exec(select(Finding)))
    by_analyzer: dict[str, dict[str, int]] = {}
    by_severity: dict[str, int] = {}
    for finding in findings:
        analyzer = by_analyzer.setdefault(finding.analyzer, {})
        analyzer[finding.severity.value] = analyzer.get(finding.severity.value, 0) + 1
        by_severity[finding.severity.value] = by_severity.get(finding.severity.value, 0) + 1

    completed_runs = len(
        list(session.exec(select(Run).where(Run.status == RunStatus.COMPLETE)))
    )
    return {
        "total_findings": len(findings),
        "completed_runs": completed_runs,
        "by_severity": by_severity,
        "by_analyzer": by_analyzer,
        "note": (
            "Use this to decide whether the configured block_on severities are workable "
            "before flipping mcp/skill from advisory to gating in policy.yaml."
        ),
    }
