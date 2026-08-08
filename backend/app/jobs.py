"""Run orchestration.

One asyncio task per run, status tracked in SQLite. No broker: runs are minutes long and
strictly local, so a queue would be infrastructure without a payoff.

The shape of a run is the same for every asset class:

    harvest -> compute what is missing -> score -> evaluate the policy -> record a decision

Harvest comes first because reusing a published result is cheaper than recomputing it. What
cannot be harvested is computed, and anything that cannot be computed leaves the run without
an approval rather than defaulting to one.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db import session_scope
from app.engines import harvest_catalog, inspect_runner
from app.engines.registry import Check, checks_for
from app.models import (
    Artifact,
    Asset,
    AssetType,
    Decision,
    Finding,
    Provenance,
    Run,
    RunStatus,
    Score,
    Severity,
)
from app.scoring import gates, normalize
from app.scoring.policy import get_policy

# Keeps a local Ollama box from being asked to serve several evals at once, which would make
# every one of them slower without finishing any sooner.
_RUN_SEMAPHORE = asyncio.Semaphore(1)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def start_run(
    run_id: int, limit: int | None = None, only_checks: list[str] | None = None
) -> None:
    """Fire-and-forget entrypoint used by the API."""
    asyncio.create_task(_execute_run(run_id, limit, only_checks))


async def _execute_run(
    run_id: int, limit: int | None = None, only_checks: list[str] | None = None
) -> None:
    settings = get_settings()
    async with _RUN_SEMAPHORE:
        try:
            await _run_llm_checks(settings, run_id, limit, only_checks)
        except Exception as exc:  # noqa: BLE001 - a crashed job must still close out the run
            with session_scope() as session:
                run = session.get(Run, run_id)
                if run:
                    run.status = RunStatus.FAILED
                    run.decision = Decision.ERROR
                    run.decision_reason = f"Run crashed: {type(exc).__name__}: {exc}"
                    run.error = f"{type(exc).__name__}: {exc}"
                    run.finished_at = _utcnow()
                    session.add(run)
                    session.commit()


async def _run_llm_checks(
    settings: Settings,
    run_id: int,
    limit_override: int | None = None,
    only_checks: list[str] | None = None,
) -> None:
    policy = get_policy(settings.policy_path)

    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        asset = session.get(Asset, run.asset_id)
        if asset is None:
            return
        run.status = RunStatus.RUNNING
        run.policy_version = policy.version
        run.policy_hash = policy.content_hash
        session.add(run)
        session.commit()
        subject_alias = run.gateway_model or asset.identifier
        judge_alias = run.judge_model or policy.judge_default_model
        hf_repo_id = asset.hf_repo_id

    checks = checks_for(AssetType.LLM)
    if only_checks:
        wanted = set(only_checks)
        checks = tuple(check for check in checks if check.id in wanted)
    refusal_rates: list[float] = []

    for check in checks:
        # Harvest first: a published number costs nothing to reuse.
        published = harvest_catalog.lookup(
            settings.policy_path.parent.parent / "catalog" / "published_scores.yaml",
            subject_alias,
            check.id,
        )
        if published is not None:
            _record_published_score(run_id, check, published, policy)
            continue

        await _run_single_check(
            settings, run_id, check, subject_alias, judge_alias, limit_override, refusal_rates
        )

    # Open-weight models additionally get a supply-chain scan. Harvested from the Hub rather
    # than recomputed: reproducing it would mean downloading tens of gigabytes of weights to
    # re-run scanners that have already run.
    weights_outcome = None
    if hf_repo_id:
        weights_outcome = await _harvest_weight_scan(settings, run_id, hf_repo_id)

    # A judge that would not grade makes the whole run unusable, so the rate is aggregated
    # across checks rather than judged per check.
    overall_refusal = max(refusal_rates) if refusal_rates else None
    _finalize_run(run_id, policy, overall_refusal, weights_outcome)


async def _harvest_weight_scan(settings: Settings, run_id: int, repo_id: str):
    """Pull Hub scan results, record them, and return the supply-chain verdict."""
    import json

    from app.engines import harvest_hf

    policy = get_policy(settings.policy_path)
    result = await harvest_hf.harvest(repo_id)

    with session_scope() as session:
        # Raw payloads are kept so a decision can be re-audited after the Hub's answer
        # changes (scanners re-run, and a repo can be updated).
        if result.raw:
            artifact_path = settings.artifact_dir / f"hf-scan-run{run_id}.json"
            artifact_path.write_text(json.dumps(result.raw, indent=2))
            session.add(
                Artifact(run_id=run_id, kind="hf_scan_json", path=str(artifact_path))
            )

        if not result.found:
            session.add(
                Finding(
                    run_id=run_id,
                    analyzer="huggingface",
                    severity=Severity.HIGH,
                    title=f"Could not read Hub scan results for {repo_id}",
                    detail=(
                        (result.error or "unknown error")
                        + " — a gated or private repo needs a token, or the weights need a "
                        "local scan instead."
                    ),
                )
            )
        else:
            for file in result.files:
                if not file.is_unsafe:
                    continue
                flagged = [v.scanner for v in file.verdicts if v.is_unsafe] or ["status"]
                session.add(
                    Finding(
                        run_id=run_id,
                        analyzer=",".join(flagged),
                        severity=Severity.CRITICAL,
                        rule_id="unsafe_weight_file",
                        title=f"Weight file flagged unsafe: {file.path}",
                        detail="; ".join(
                            f"{v.scanner}: {v.message or v.status}"
                            for v in file.verdicts
                            if v.is_unsafe
                        ),
                        file_path=file.path,
                    )
                )

            if not result.scans_done:
                # Deliberately a finding, not silence. Unscanned is not safe.
                session.add(
                    Finding(
                        run_id=run_id,
                        analyzer="huggingface",
                        severity=Severity.MEDIUM,
                        rule_id="scans_incomplete",
                        title="Upstream scans are incomplete for this repository",
                        detail=(
                            "The Hub reports scansDone=false. Absence of findings is not "
                            "evidence of safety, so this withholds approval pending a local "
                            "scan or manual review. Scanner coverage so far: "
                            f"{result.scanner_coverage}"
                        ),
                    )
                )
        session.commit()

    return gates.decide_weights(
        policy,
        result.unsafe_files if result.found else [f"{repo_id} (unreadable)"],
        scans_done=result.scans_done and result.found,
    )


def _record_published_score(run_id: int, check: Check, published, policy) -> None:
    gate = policy.llm_gates.get(check.id)
    with session_scope() as session:
        session.add(
            Score(
                run_id=run_id,
                check_id=check.id,
                metric=check.metric_name,
                raw_value=published.value,
                normalized=normalize.normalize_metric(published.value, check.direction),
                direction=check.direction,
                threshold=gate.threshold if gate else None,
                gated=gate is not None,
                passed=gate.passes(published.value) if gate else None,
                provenance=Provenance.PUBLISHED,
                source_url=published.source_url,
                model_used=published.model,
            )
        )
        session.commit()


async def _run_single_check(
    settings: Settings,
    run_id: int,
    check: Check,
    subject_alias: str,
    judge_alias: str,
    limit_override: int | None,
    refusal_rates: list[float],
) -> None:
    result = await inspect_runner.run_eval(
        settings,
        task=check.id,
        model_alias=subject_alias,
        judge_alias=judge_alias if check.needs_judge else None,
        limit=limit_override or check.default_limit,
        timeout=3600.0,
    )
    payload = result.payload
    metrics: dict[str, float] = payload.get("metrics") or {}

    refusal_rate = payload.get("judge_refusal_rate")
    if isinstance(refusal_rate, (int, float)):
        refusal_rates.append(float(refusal_rate))

    gate = get_policy(settings.policy_path).llm_gates.get(check.id)
    raw_reported = metrics.get(check.metric_key)
    # Convert to the canonical 0-1 rate so stored values and policy thresholds share a unit.
    raw_value = check.scale.to_rate(float(raw_reported)) if raw_reported is not None else None

    with session_scope() as session:
        session.add(
            Score(
                run_id=run_id,
                check_id=check.id,
                metric=check.metric_name,
                raw_value=raw_value,
                normalized=(
                    normalize.normalize_metric(raw_value, check.direction)
                    if raw_value is not None
                    else None
                ),
                direction=check.direction,
                threshold=gate.threshold if gate else None,
                gated=gate is not None and raw_value is not None,
                passed=gate.passes(raw_value) if (gate and raw_value is not None) else None,
                provenance=Provenance.SELF_RUN,
                model_used=subject_alias,
                total_samples=payload.get("total_samples"),
                unresolved_samples=payload.get("unresolved_samples"),
            )
        )

        # Everything else the benchmark reported, kept for a human digging in and never
        # thresholded. This is what `gated=False` is for.
        for key, value in metrics.items():
            if key == check.metric_key or not isinstance(value, (int, float)):
                continue
            session.add(
                Score(
                    run_id=run_id,
                    check_id=f"{check.id}::{key.split('.')[-1]}",
                    metric=key.split(".")[-1],
                    raw_value=float(value),
                    gated=False,
                    provenance=Provenance.SELF_RUN,
                    model_used=subject_alias,
                )
            )

        log_path = payload.get("log_path")
        if log_path:
            session.add(Artifact(run_id=run_id, kind="inspect_log", path=str(log_path)))

        run = session.get(Run, run_id)
        if run and payload.get("error"):
            run.error = ((run.error or "") + f"\n[{check.id}] {payload['error']}").strip()
            session.add(run)
        session.commit()


def _finalize_run(
    run_id: int,
    policy,
    judge_refusal_rate: float | None,
    weights_outcome: gates.DecisionResult | None = None,
) -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        scores = list(session.exec(select(Score).where(Score.run_id == run_id)))

        outcome = gates.decide_llm(policy, scores, judge_refusal_rate)

        # Benchmarks and the supply-chain scan are independent reasons to withhold approval,
        # so the stricter of the two wins. Approval requires both to be satisfied.
        if weights_outcome is not None and not weights_outcome.approved:
            outcome = gates.DecisionResult(
                decision=(
                    Decision.ERROR
                    if Decision.ERROR in (outcome.decision, weights_outcome.decision)
                    else Decision.NEEDS_DEEP_TESTING
                ),
                reason=(
                    f"Supply chain: {weights_outcome.reason}"
                    if outcome.approved
                    else f"{outcome.reason} | Supply chain: {weights_outcome.reason}"
                ),
                gate_outcomes=outcome.gate_outcomes,
                blocking_reasons=outcome.blocking_reasons + weights_outcome.blocking_reasons,
            )

        run.decision = outcome.decision
        run.decision_reason = outcome.reason
        run.judge_refusal_rate = judge_refusal_rate
        run.status = (
            RunStatus.FAILED if outcome.decision is Decision.ERROR else RunStatus.COMPLETE
        )
        run.finished_at = _utcnow()
        session.add(run)
        session.commit()


def composite_for_run(session: Session, run_id: int, policy) -> float | None:
    """Leaderboard number. Display only — `gates.py` never reads this."""
    scores = session.exec(select(Score).where(Score.run_id == run_id)).all()
    normalized = {
        score.check_id: score.normalized
        for score in scores
        if score.gated and score.normalized is not None
    }
    return normalize.composite_score(normalized, policy.composite_weights)
