"""Turning scores and findings into a governance decision.

The whole point of this module is that it is boring and deterministic. No LLM participates.

Invariants, each covered by a test:

* **Only gated scores are read.** Benchmarks emit extra metrics (AgentDojo's benign utility,
  BLEU, Jaccard). Those are stored for a human, and this module never looks at them.
* **The composite is never read.** It exists for the leaderboard only.
* **Absence is never approval.** A missing required check, an unreliable judge, or a scanner
  error withholds approval rather than defaulting to it.
* **Advisory mode cannot approve.** It can only ever return NEEDS_DEEP_TESTING.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import AssetType, Decision, Score, Severity
from app.scoring.policy import Policy

__all__ = [
    "Decision",
    "DecisionResult",
    "GateOutcome",
    "decide_llm",
    "decide_scanner",
    "decide_weights",
]


@dataclass
class GateOutcome:
    check_id: str
    metric: str
    raw_value: float | None
    threshold: float
    direction: str
    passed: bool
    reason: str


@dataclass
class DecisionResult:
    decision: Decision
    reason: str
    gate_outcomes: list[GateOutcome] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.decision is Decision.AUTO_APPROVE


def decide_llm(
    policy: Policy,
    scores: list[Score],
    judge_refusal_rate: float | None = None,
) -> DecisionResult:
    """Evaluate the LLM benchmark gates."""
    judge_unreliable = (
        judge_refusal_rate is not None and judge_refusal_rate > policy.judge_max_refusal_rate
    )

    # Only gated scores participate. Everything else is display detail.
    gated = {score.check_id: score for score in scores if score.gated}

    outcomes: list[GateOutcome] = []
    blocking: list[str] = []

    for check_id, gate in policy.llm_gates.items():
        score = gated.get(check_id)
        if score is None or score.raw_value is None:
            outcomes.append(
                GateOutcome(
                    check_id=check_id,
                    metric=gate.metric,
                    raw_value=None,
                    threshold=gate.threshold,
                    direction=gate.direction.value,
                    passed=False,
                    reason="no score recorded for this benchmark",
                )
            )
            blocking.append(f"{check_id}: missing score")
            continue

        # Compared raw against raw. Normalization is display-only and cannot move a gate.
        passed = gate.passes(score.raw_value)
        comparator = "≥" if gate.direction.value == "higher_is_better" else "≤"
        outcomes.append(
            GateOutcome(
                check_id=check_id,
                metric=gate.metric,
                raw_value=score.raw_value,
                threshold=gate.threshold,
                direction=gate.direction.value,
                passed=passed,
                reason=(
                    f"{score.raw_value:.4g} vs required {comparator} {gate.threshold:.4g}"
                ),
            )
        )
        if not passed:
            blocking.append(
                f"{check_id}: {gate.metric} {score.raw_value:.4g}, "
                f"needs {comparator} {gate.threshold:.4g}"
            )

    if not policy.llm_gates:
        return DecisionResult(
            decision=Decision.ERROR,
            reason="Policy defines no LLM gates; nothing to decide against.",
            blocking_reasons=["no_gates_configured"],
        )

    # An unreliable judge invalidates the run rather than making it lenient: a refusal parsed
    # as "the subject did not comply" inflates refusal-style metrics. The gate outcomes are
    # still returned so a reviewer can see the numbers that were produced — suppressing them
    # would hide evidence without adding any safety — but no decision is emitted from them.
    if judge_unreliable:
        return DecisionResult(
            decision=Decision.ERROR,
            reason=(
                f"Judge unreliable: refused {judge_refusal_rate:.1%} of samples, above the "
                f"{policy.judge_max_refusal_rate:.1%} limit. The scores below were computed "
                "but must not be trusted, so no decision is emitted. Re-run with a different "
                "judge model."
            ),
            gate_outcomes=outcomes,
            blocking_reasons=["judge_unreliable"],
        )

    if blocking:
        return DecisionResult(
            decision=Decision.NEEDS_DEEP_TESTING,
            reason=f"{len(blocking)} gate(s) not satisfied: " + "; ".join(blocking),
            gate_outcomes=outcomes,
            blocking_reasons=blocking,
        )

    return DecisionResult(
        decision=Decision.AUTO_APPROVE,
        reason=f"All {len(outcomes)} benchmark gates satisfied.",
        gate_outcomes=outcomes,
    )


def decide_weights(policy: Policy, unsafe_files: list[str], scans_done: bool) -> DecisionResult:
    """Evaluate an open-weight model's supply-chain scan.

    The gate is the upstream scanners' own verdict. "Not yet scanned" is deliberately not
    treated as "safe" — absence of a finding is not evidence of absence.
    """
    if unsafe_files and policy.weights_block_on_unsafe_file:
        return DecisionResult(
            decision=Decision.NEEDS_DEEP_TESTING,
            reason=(
                f"{len(unsafe_files)} weight file(s) flagged unsafe by upstream scanners: "
                + ", ".join(unsafe_files[:5])
            ),
            blocking_reasons=[f"unsafe_file:{f}" for f in unsafe_files],
        )
    if not scans_done and not policy.weights_treat_unscanned_as_pass:
        return DecisionResult(
            decision=Decision.NEEDS_DEEP_TESTING,
            reason=(
                "Upstream scans are incomplete for this repository. Unscanned is not the "
                "same as safe, so this needs a local scan or manual review."
            ),
            blocking_reasons=["scans_incomplete"],
        )
    return DecisionResult(
        decision=Decision.AUTO_APPROVE,
        reason="All scanned weight files reported safe by upstream scanners.",
    )


def decide_scanner(
    policy: Policy,
    asset_type: AssetType,
    severity_counts: dict[Severity, int],
    scanner_says_safe: bool | None = None,
    scan_failed: bool = False,
) -> DecisionResult:
    """Evaluate an MCP server or agent skill from its scanner findings.

    Gated on a severity rule, not a score. Scanner findings have no fixed denominator, so a
    numeric threshold over them would be invented precision.
    """
    scanner_policy = policy.scanner_policy(asset_type)
    if scanner_policy is None:
        return DecisionResult(
            decision=Decision.ERROR,
            reason=f"Policy defines no scanner rule for {asset_type.value}.",
            blocking_reasons=["no_scanner_policy"],
        )

    if scan_failed:
        return DecisionResult(
            decision=Decision.ERROR,
            reason="The scan did not complete, so there is nothing to decide against.",
            blocking_reasons=["scan_failed"],
        )

    blocking: list[str] = []
    for severity in sorted(scanner_policy.block_on, key=lambda s: s.value):
        count = severity_counts.get(severity, 0)
        if count:
            blocking.append(f"{count} {severity.value} finding(s)")

    if scanner_policy.trust_scanner_verdict and scanner_says_safe is False:
        blocking.append("scanner verdict: not safe")

    if blocking:
        return DecisionResult(
            decision=Decision.NEEDS_DEEP_TESTING,
            reason="Blocking findings: " + "; ".join(blocking),
            blocking_reasons=blocking,
        )

    # Clean scan, but advisory mode still withholds approval: without a false-positive
    # baseline we cannot yet claim a clean scan means safe.
    if scanner_policy.is_advisory:
        return DecisionResult(
            decision=Decision.NEEDS_DEEP_TESTING,
            reason=(
                "No blocking findings, but this asset class is in advisory mode: the severity "
                "rule has no false-positive baseline yet, so every result goes to human "
                "review. Set mode: gating in policy.yaml once the distribution is understood."
            ),
            blocking_reasons=["advisory_mode"],
        )

    return DecisionResult(
        decision=Decision.AUTO_APPROVE,
        reason="No findings at or above the blocking severity, and the scanner reported safe.",
    )
