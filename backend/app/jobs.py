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
from pathlib import Path

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
from app.scoring.policy import Gate, Policy, get_active_policy

# Keeps a local Ollama box from being asked to serve several evals at once, which would make
# every one of them slower without finishing any sooner.
_RUN_SEMAPHORE = asyncio.Semaphore(1)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def close_orphaned_runs(session: Session) -> int:
    """Fail any run left `running`/`pending` by a previous process. Called at startup.

    Jobs are in-process asyncio tasks, so a backend restart kills them silently. Without
    this, such a run spins forever in the UI claiming work that is no longer happening.
    """
    orphans = session.exec(
        select(Run).where(Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]))
    ).all()
    for run in orphans:
        run.status = RunStatus.FAILED
        run.decision = Decision.ERROR
        run.decision_reason = (
            "Interrupted by a backend restart before finishing. Scores recorded up to "
            "that point are partial; start a new run."
        )
        run.error = run.error or "interrupted by backend restart"
        run.finished_at = _utcnow()
        session.add(run)
    session.commit()
    return len(orphans)


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
            with session_scope() as session:
                run = session.get(Run, run_id)
                asset = session.get(Asset, run.asset_id) if run else None
                asset_type = asset.type if asset else None

            if asset_type in (AssetType.MCP, AssetType.SKILL):
                await _run_scanner_checks(settings, run_id, asset_type)
            else:
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
    with session_scope() as session:
        # The policy is resolved ONCE, at run start, and its identity is recorded before any
        # work happens: a policy edited mid-run must not change what this run means.
        policy = get_active_policy(session)
        run = session.get(Run, run_id)
        if run is None:
            return
        asset = session.get(Asset, run.asset_id)
        if asset is None:
            return
        meta = policy.meta_for(AssetType.LLM)
        run.status = RunStatus.RUNNING
        run.policy_version = meta.version
        run.policy_hash = meta.content_hash
        session.add(run)
        session.commit()
        subject_alias = run.gateway_model or asset.identifier
        judge_alias = run.judge_model or policy.judge_default_model
        hf_repo_id = asset.hf_repo_id
        sample_override = limit_override or run.sample_override

    checks = checks_for(AssetType.LLM)
    if only_checks:
        wanted = set(only_checks)
        checks = tuple(check for check in checks if check.id in wanted)
    unresolved_rates: list[float] = []
    heuristic_rates: list[float] = []

    for check in checks:
        # Harvest first: a published number costs nothing to reuse.
        published = harvest_catalog.lookup(
            settings.policy_dir.parent / "catalog" / "published_scores.yaml",
            subject_alias,
            check.id,
        )
        if published is not None:
            _record_published_score(run_id, check, published, policy)
            continue

        await _run_single_check(
            settings,
            run_id,
            check,
            policy,
            subject_alias,
            judge_alias,
            sample_override,
            unresolved_rates,
            heuristic_rates,
        )

    # Open-weight models additionally get a supply-chain scan. Harvested from the Hub rather
    # than recomputed: reproducing it would mean downloading tens of gigabytes of weights to
    # re-run scanners that have already run.
    weights_outcome = None
    if hf_repo_id:
        weights_outcome = await _harvest_weight_scan(settings, run_id, hf_repo_id, policy)

    # A judge that would not grade makes the whole run unusable, so the worst rate across
    # checks decides rather than an average that would dilute one bad check.
    overall_unresolved = max(unresolved_rates) if unresolved_rates else None
    overall_heuristic = max(heuristic_rates) if heuristic_rates else None
    _finalize_run(
        run_id, policy, overall_unresolved, weights_outcome, heuristic=overall_heuristic
    )


async def _run_scanner_checks(settings: Settings, run_id: int, asset_type: AssetType) -> None:
    """MCP server / agent skill: acquire the source, sweep it, decide on a severity rule."""
    import json

    from app.engines import mcp_scanner, skill_scanner, source

    with session_scope() as session:
        policy = get_active_policy(session)
        run = session.get(Run, run_id)
        if run is None:
            return
        asset = session.get(Asset, run.asset_id)
        if asset is None:
            return
        meta = policy.meta_for(asset_type)
        run.status = RunStatus.RUNNING
        run.policy_version = meta.version
        run.policy_hash = meta.content_hash
        session.add(run)
        session.commit()
        origin = asset.source_url or asset.identifier

    workspace = source.workspace_for_run(settings.workspace_dir, run_id)

    # Acquire read-only. Nothing from the submission is ever executed.
    try:
        if origin.startswith("https://"):
            acquired = await source.clone_repo(origin, workspace)
        else:
            # Validated against an allowlist of roots: the identifier is client-controlled,
            # so it must not be able to name /etc or the app's own database.
            candidate = source.resolve_submission_path(origin, settings.submission_roots)
            if candidate.is_dir():
                acquired = source.AcquiredSource(path=candidate, kind="dir", origin=origin)
            else:
                acquired = source.extract_zip(candidate, workspace)
    except source.SourceError as exc:
        _record_scanner_failure(run_id, f"Could not acquire source: {exc}")
        return

    if asset_type is AssetType.MCP:
        result = await mcp_scanner.scan_source(settings, acquired.path)
        scanner_safe = result.scanner_says_safe
    else:
        result = await skill_scanner.scan_skill(settings, acquired.path)
        scanner_safe = result.scanner_says_safe

    with session_scope() as session:
        if result.raw:
            artifact_path = settings.artifact_dir / f"{asset_type.value}-scan-run{run_id}.json"
            artifact_path.write_text(json.dumps(result.raw, indent=2))
            session.add(
                Artifact(
                    run_id=run_id,
                    kind=f"{asset_type.value}_scanner_json",
                    path=str(artifact_path),
                )
            )

        for finding in result.findings:
            session.add(
                Finding(
                    run_id=run_id,
                    analyzer=finding.analyzer,
                    severity=finding.severity,
                    rule_id=finding.rule_id,
                    title=finding.title,
                    detail=finding.detail,
                    file_path=finding.file_path,
                )
            )

        run = session.get(Run, run_id)
        if run:
            run.engine_version = result.engine_version
            run.ruleset_version = result.ruleset_version
            if result.errors:
                run.error = "\n".join(result.errors)[:4000]

            outcome = gates.decide_scanner(
                policy,
                asset_type,
                result.severity_counts(),
                scanner_says_safe=scanner_safe,
                scan_failed=not result.ok,
            )
            run.decision = outcome.decision
            run.decision_reason = outcome.reason
            run.status = (
                RunStatus.FAILED if outcome.decision is Decision.ERROR else RunStatus.COMPLETE
            )
            run.finished_at = _utcnow()
            session.add(run)

        # Severity roll-up for leaderboard ordering only, stored ungated so the gate
        # evaluator cannot read it. The penalty table comes from this class's own policy.
        penalty = policy.scanner[asset_type].severity_penalty
        rollup = normalize.severity_rollup(result.severity_counts(), penalty)
        session.add(
            Score(
                run_id=run_id,
                check_id=f"{asset_type.value}.severity_rollup",
                metric="severity_rollup",
                raw_value=rollup,
                normalized=rollup,
                gated=False,
                provenance=Provenance.SELF_RUN,
            )
        )
        session.commit()


def _record_scanner_failure(run_id: int, message: str) -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        run.status = RunStatus.FAILED
        # A scan that did not happen is an error, never a pass.
        run.decision = Decision.ERROR
        run.decision_reason = message
        run.error = message
        run.finished_at = _utcnow()
        session.add(run)
        session.commit()


async def _harvest_weight_scan(settings: Settings, run_id: int, repo_id: str, policy: Policy):
    """Pull Hub scan results, record them, and return the supply-chain verdict."""
    import json

    from app.engines import harvest_hf

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
    policy: Policy,
    subject_alias: str,
    judge_alias: str,
    sample_override: int | None,
    unresolved_rates: list[float],
    heuristic_rates: list[float],
) -> None:
    gate: Gate | None = policy.llm_gates.get(check.id)

    # How many test cases, and which ones, comes from the POLICY — the governed document —
    # not from a form default. Resolution order:
    #   1. an explicit per-run override (a dev/wiring facility, recorded and flagged);
    #   2. the gate's fixed core set (`sample_ids`), which runs exactly those cases;
    #   3. the gate's `samples` count (the dataset's first N — deterministic);
    #   4. the registry fallback, only for a check the policy does not gate.
    sample_ids: tuple[str, ...] = ()
    if sample_override is not None:
        limit: int | None = sample_override
    elif gate is not None and gate.sample_ids:
        limit = None
        sample_ids = gate.sample_ids
    elif gate is not None:
        limit = gate.samples
    else:
        limit = check.default_limit

    result = await inspect_runner.run_eval(
        settings,
        task=check.id,
        model_alias=subject_alias,
        judge_alias=judge_alias if check.needs_judge else None,
        limit=limit,
        sample_ids=sample_ids,
        timeout=3600.0,
    )
    payload = result.payload
    metrics: dict[str, float] = payload.get("metrics") or {}

    # Gate on the structural signal only. The phrasing heuristic is recorded separately.
    unresolved = payload.get("judge_unresolved_rate")
    if isinstance(unresolved, (int, float)):
        unresolved_rates.append(float(unresolved))
    heuristic = payload.get("judge_refusal_rate_heuristic")
    if isinstance(heuristic, (int, float)):
        heuristic_rates.append(float(heuristic))

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
    judge_unresolved_rate: float | None,
    weights_outcome: gates.DecisionResult | None = None,
    heuristic: float | None = None,
) -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        scores = list(session.exec(select(Score).where(Score.run_id == run_id)))

        outcome = gates.decide_llm(policy, scores, judge_unresolved_rate)

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
        run.judge_unresolved_rate = judge_unresolved_rate
        run.judge_refusal_rate = heuristic
        run.status = (
            RunStatus.FAILED if outcome.decision is Decision.ERROR else RunStatus.COMPLETE
        )
        run.finished_at = _utcnow()
        session.add(run)
        session.commit()


def composite_for_run(session: Session, run_id: int, policy) -> float | None:
    """Leaderboard number. Display only — `gates.py` never reads this.

    Returns None unless every gated benchmark produced a score. A composite over a subset is
    not comparable to one over the full suite, and showing "100" beside "1/5 gates" reads as
    a strong result when it actually means almost nothing was measured. Better to show
    nothing than a number that flatters an incomplete run.
    """
    scores = session.exec(select(Score).where(Score.run_id == run_id)).all()
    normalized = {
        score.check_id: score.normalized
        for score in scores
        if score.gated and score.normalized is not None
    }
    if set(normalized) != set(policy.composite_weights):
        return None
    return normalize.composite_score(normalized, policy.composite_weights)
