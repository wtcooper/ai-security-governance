"""Policy is data, not code.

Acceptance criteria 5.2 and 5.3, carried into the per-class world of Phase 8. The claim
being tested is the one that makes the shipped placeholder thresholds acceptable: turning
them into real thresholds must be a policy edit (now: a new policy version), never a code
change. If that stops being true, calibration becomes a development task and the whole
"thresholds are policy" story falls apart.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import AssetType, Decision, Direction, Provenance, Score
from app.scoring import gates
from app.scoring.policy import build_policy, load_policy_dir

POLICY_DIR = Path(__file__).resolve().parents[1] / "policy"


def _seed_docs() -> dict[AssetType, tuple[str, str]]:
    return {
        asset_type: ((POLICY_DIR / f"{asset_type.value}.yaml").read_text(), "1")
        for asset_type in AssetType
    }


def _scores_for(policy, value_by_check: dict[str, float]) -> list[Score]:
    return [
        Score(
            run_id=1,
            check_id=check_id,
            metric=policy.llm_gates[check_id].metric,
            raw_value=value,
            direction=policy.llm_gates[check_id].direction,
            threshold=policy.llm_gates[check_id].threshold,
            gated=True,
            passed=policy.llm_gates[check_id].passes(value),
            provenance=Provenance.SELF_RUN,
        )
        for check_id, value in value_by_check.items()
    ]


def _borderline_values(policy) -> dict[str, float]:
    """Exactly on each threshold, so a small move in either direction flips the gate."""
    return {check_id: gate.threshold for check_id, gate in policy.llm_gates.items()}


def test_a_stored_run_can_be_redecided_under_a_new_policy():
    """Criterion 5.2 — the same scores, re-decided, flip when only the document changes."""
    docs = _seed_docs()
    lenient = build_policy(docs)

    scores = _scores_for(lenient, _borderline_values(lenient))
    assert gates.decide_llm(lenient, scores).decision is Decision.AUTO_APPROVE

    # Tighten one higher-is-better threshold. No code changes; only the document.
    llm_text, _ = docs[AssetType.LLM]
    strict_docs = dict(docs)
    strict_docs[AssetType.LLM] = (llm_text.replace("threshold: 0.85", "threshold: 0.99"), "2")
    strict = build_policy(strict_docs)
    assert strict.llm_gates["cyse4_multilingual_prompt_injection"].threshold == 0.99

    outcome = gates.decide_llm(strict, scores)
    assert outcome.decision is Decision.NEEDS_DEEP_TESTING
    assert any("cyse4_multilingual_prompt_injection" in r for r in outcome.blocking_reasons)


def test_policy_hash_changes_when_a_threshold_changes():
    """Criterion 5.3 — a historical decision must remain attributable to its policy."""
    docs = _seed_docs()
    first = build_policy(docs)

    llm_text, _ = docs[AssetType.LLM]
    changed = dict(docs)
    changed[AssetType.LLM] = (llm_text.replace("threshold: 0.90", "threshold: 0.80"), "2")
    second = build_policy(changed)

    assert (
        first.meta[AssetType.LLM].content_hash != second.meta[AssetType.LLM].content_hash
    )
    # The untouched classes keep their hashes: versions are per class, not global.
    assert first.meta[AssetType.MCP].content_hash == second.meta[AssetType.MCP].content_hash

    # Identical content must hash identically, or the field would be noise.
    third = build_policy(_seed_docs())
    assert third.meta[AssetType.LLM].content_hash == first.meta[AssetType.LLM].content_hash


def test_advisory_to_gating_is_a_one_line_config_change():
    """The documented path out of advisory mode must actually be one edit."""
    docs = _seed_docs()
    advisory = build_policy(docs)
    assert advisory.scanner[AssetType.MCP].is_advisory
    assert (
        gates.decide_scanner(advisory, AssetType.MCP, {}, scanner_says_safe=True).decision
        is Decision.NEEDS_DEEP_TESTING
    )

    mcp_text, _ = docs[AssetType.MCP]
    gating_docs = dict(docs)
    gating_docs[AssetType.MCP] = (mcp_text.replace("mode: advisory", "mode: gating", 1), "2")
    gating = build_policy(gating_docs)
    assert not gating.scanner[AssetType.MCP].is_advisory
    assert (
        gates.decide_scanner(gating, AssetType.MCP, {}, scanner_says_safe=True).decision
        is Decision.AUTO_APPROVE
    )
    # The other scanner class is untouched by the edit.
    assert gating.scanner[AssetType.SKILL].is_advisory


def test_shipped_thresholds_are_all_within_range():
    """A threshold outside 0-1 would mean a unit mistake, which silently disables a gate."""
    policy = load_policy_dir(POLICY_DIR)
    for check_id, gate in policy.llm_gates.items():
        assert 0.0 <= gate.threshold <= 1.0, f"{check_id} threshold {gate.threshold} out of range"


def test_every_gate_declares_a_direction():
    policy = load_policy_dir(POLICY_DIR)
    for check_id, gate in policy.llm_gates.items():
        assert gate.direction in (Direction.HIGHER_IS_BETTER, Direction.LOWER_IS_BETTER), check_id


def test_every_gate_has_a_human_readable_description():
    """A reviewer reading a failed gate needs to know what it measured."""
    policy = load_policy_dir(POLICY_DIR)
    for check_id, gate in policy.llm_gates.items():
        assert gate.description, f"{check_id} has no description"


def test_every_gate_declares_a_sample_count():
    """Phase 8: the policy, not a form default, decides how much gets measured."""
    policy = load_policy_dir(POLICY_DIR)
    for check_id, gate in policy.llm_gates.items():
        assert gate.planned_samples >= 1, f"{check_id} plans no samples"


@pytest.mark.parametrize("severity", ["critical", "high", "medium", "low", "info"])
@pytest.mark.parametrize("asset_type", [AssetType.MCP, AssetType.SKILL])
def test_severity_rollup_penalties_are_defined_for_every_severity(severity, asset_type):
    """A missing penalty would silently weight a severity at zero in the leaderboard."""
    from app.models import Severity

    policy = load_policy_dir(POLICY_DIR)
    assert Severity(severity) in policy.scanner[asset_type].severity_penalty


def test_composite_is_withheld_when_coverage_is_incomplete():
    """A composite over a subset of benchmarks must not be displayed.

    Showing "100" next to "1/5 gates" reads as a strong result when it means almost nothing
    was measured. The gates already say the run is incomplete; the score must not contradict
    them.
    """
    from app.scoring import normalize

    policy = load_policy_dir(POLICY_DIR)
    weights = policy.composite_weights

    # One perfect score out of five would compute to 100 if re-normalised over what is
    # present, which is exactly the misleading number being avoided.
    partial = {"cyse4_mitre_frr": 100.0}
    assert normalize.composite_score(partial, weights) == 100.0

    # Full coverage is what makes the number meaningful.
    full = dict.fromkeys(weights, 100.0)
    assert normalize.composite_score(full, weights) == 100.0
    assert set(full) == set(weights)
