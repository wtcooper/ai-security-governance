"""Gate invariants. These are the rules a governance tool must never get wrong.

Pure-logic tests on purpose: each asserts a property of the decision function that no amount
of real traffic would demonstrate (you cannot prove "a missing score never approves" by
observing runs that happened to have scores).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import Decision, Direction, Provenance, Score, Severity
from app.scoring import gates, normalize
from app.scoring.policy import load_policy

POLICY_PATH = Path(__file__).resolve().parents[1] / "policy" / "policy.yaml"


@pytest.fixture
def policy():
    return load_policy(POLICY_PATH)


def _score(check_id: str, value: float, policy, gated: bool = True) -> Score:
    gate = policy.llm_gates.get(check_id)
    return Score(
        run_id=1,
        check_id=check_id,
        metric=gate.metric if gate else "extra",
        raw_value=value,
        normalized=normalize.normalize_metric(value, gate.direction if gate else Direction.HIGHER_IS_BETTER),
        direction=gate.direction if gate else None,
        threshold=gate.threshold if gate else None,
        gated=gated,
        passed=gate.passes(value) if gate else None,
        provenance=Provenance.SELF_RUN,
    )


def _all_passing(policy) -> list[Score]:
    """A score just inside the threshold for every gate."""
    scores = []
    for check_id, gate in policy.llm_gates.items():
        value = gate.threshold if gate.direction is Direction.HIGHER_IS_BETTER else gate.threshold
        scores.append(_score(check_id, value, policy))
    return scores


def test_all_gates_satisfied_approves(policy):
    result = gates.decide_llm(policy, _all_passing(policy))
    assert result.decision is Decision.AUTO_APPROVE
    assert len(result.gate_outcomes) == len(policy.llm_gates)


def test_one_breached_gate_blocks(policy):
    scores = _all_passing(policy)
    # Push the prompt-injection gate below its threshold.
    gate = policy.llm_gates["cyse4_multilingual_prompt_injection"]
    scores = [s for s in scores if s.check_id != gate.check_id]
    scores.append(_score(gate.check_id, gate.threshold - 0.5, policy))

    result = gates.decide_llm(policy, scores)
    assert result.decision is Decision.NEEDS_DEEP_TESTING
    assert any("cyse4_multilingual_prompt_injection" in r for r in result.blocking_reasons)


def test_missing_score_never_approves(policy):
    """Absence of evidence is not evidence of safety."""
    scores = _all_passing(policy)[:-1]
    result = gates.decide_llm(policy, scores)
    assert result.decision is Decision.NEEDS_DEEP_TESTING
    assert any("missing score" in r for r in result.blocking_reasons)


def test_no_scores_at_all_never_approves(policy):
    result = gates.decide_llm(policy, [])
    assert result.decision is Decision.NEEDS_DEEP_TESTING


def test_ungated_metrics_are_never_thresholded(policy):
    """Extra metrics are recorded for humans and must not affect the decision."""
    scores = _all_passing(policy)
    # Add terrible-looking extra metrics. They are ungated, so they must be ignored.
    scores.append(_score("cyse4_instruct::bleu_score_average", 0.0, policy, gated=False))
    scores.append(_score("agentdojo::utility_accuracy", 0.0, policy, gated=False))

    result = gates.decide_llm(policy, scores)
    assert result.decision is Decision.AUTO_APPROVE


def test_composite_is_never_a_gate(policy):
    """A dreadful composite cannot block if every gate passes, and vice versa."""
    scores = _all_passing(policy)
    normalized = {s.check_id: 0.0 for s in scores}  # composite would be 0
    assert normalize.composite_score(normalized, policy.composite_weights) == 0.0
    # The decision is unchanged, because gates.py never reads the composite.
    assert gates.decide_llm(policy, scores).decision is Decision.AUTO_APPROVE


def test_unreliable_judge_errors_and_emits_no_decision(policy):
    """A judge that would not grade invalidates the run rather than making it lenient."""
    scores = _all_passing(policy)
    result = gates.decide_llm(
        policy, scores, judge_refusal_rate=policy.judge_max_refusal_rate + 0.01
    )
    assert result.decision is Decision.ERROR
    assert "judge_unreliable" in result.blocking_reasons
    # Crucially: not an approval, even though every gate passed.
    assert not result.approved


def test_judge_refusal_at_or_below_limit_is_fine(policy):
    result = gates.decide_llm(
        policy, _all_passing(policy), judge_refusal_rate=policy.judge_max_refusal_rate
    )
    assert result.decision is Decision.AUTO_APPROVE


def test_direction_is_respected_in_both_senses(policy):
    higher = policy.llm_gates["cyse4_multilingual_prompt_injection"]
    assert higher.direction is Direction.HIGHER_IS_BETTER
    assert higher.passes(higher.threshold + 0.1)
    assert not higher.passes(higher.threshold - 0.1)

    lower = policy.llm_gates["cyse4_instruct"]
    assert lower.direction is Direction.LOWER_IS_BETTER
    assert lower.passes(lower.threshold - 0.1)
    assert not lower.passes(lower.threshold + 0.1)


# --- scanner-backed asset classes -------------------------------------------------------


def test_advisory_mode_never_approves_even_on_a_clean_scan(policy):
    from app.models import AssetType

    for asset_type in (AssetType.MCP, AssetType.SKILL):
        result = gates.decide_scanner(policy, asset_type, {}, scanner_says_safe=True)
        assert result.decision is Decision.NEEDS_DEEP_TESTING, asset_type
        assert "advisory_mode" in result.blocking_reasons


def test_blocking_severity_blocks(policy):
    from app.models import AssetType

    result = gates.decide_scanner(
        policy, AssetType.MCP, {Severity.CRITICAL: 1}, scanner_says_safe=True
    )
    assert result.decision is Decision.NEEDS_DEEP_TESTING
    assert any("critical" in r for r in result.blocking_reasons)


def test_failed_scan_is_an_error_not_an_approval(policy):
    from app.models import AssetType

    result = gates.decide_scanner(policy, AssetType.SKILL, {}, scan_failed=True)
    assert result.decision is Decision.ERROR


def test_gating_mode_can_approve_a_clean_scan(policy):
    """Proves advisory is the only thing withholding approval, not a hidden second rule."""
    from dataclasses import replace

    from app.models import AssetType

    gating = replace(policy.scanner[AssetType.MCP], mode="gating")
    patched = replace(policy, scanner={**policy.scanner, AssetType.MCP: gating})

    result = gates.decide_scanner(patched, AssetType.MCP, {}, scanner_says_safe=True)
    assert result.decision is Decision.AUTO_APPROVE


# --- open-weight supply chain ------------------------------------------------------------


def test_unsafe_weight_file_blocks(policy):
    result = gates.decide_weights(policy, ["pytorch_model.bin"], scans_done=True)
    assert result.decision is Decision.NEEDS_DEEP_TESTING


def test_unscanned_is_not_treated_as_safe(policy):
    result = gates.decide_weights(policy, [], scans_done=False)
    assert result.decision is Decision.NEEDS_DEEP_TESTING
    assert "scans_incomplete" in result.blocking_reasons


def test_clean_completed_scan_approves(policy):
    result = gates.decide_weights(policy, [], scans_done=True)
    assert result.decision is Decision.AUTO_APPROVE


# --- normalization ----------------------------------------------------------------------


def test_normalization_inverts_lower_is_better():
    assert normalize.normalize_metric(0.0, Direction.LOWER_IS_BETTER) == 100.0
    assert normalize.normalize_metric(1.0, Direction.LOWER_IS_BETTER) == 0.0
    assert normalize.normalize_metric(0.0, Direction.HIGHER_IS_BETTER) == 0.0
    assert normalize.normalize_metric(1.0, Direction.HIGHER_IS_BETTER) == 100.0


def test_normalization_clamps_out_of_range_values():
    assert normalize.normalize_metric(1.7, Direction.HIGHER_IS_BETTER) == 100.0
    assert normalize.normalize_metric(-0.4, Direction.HIGHER_IS_BETTER) == 0.0


def test_severity_rollup_is_monotonic_and_floored(policy):
    clean = normalize.severity_rollup({}, policy.severity_penalty)
    one_high = normalize.severity_rollup({Severity.HIGH: 1}, policy.severity_penalty)
    many = normalize.severity_rollup({Severity.CRITICAL: 99}, policy.severity_penalty)
    assert clean == 100.0
    assert one_high < clean
    assert many == 0.0


def test_composite_returns_none_when_nothing_scored(policy):
    assert normalize.composite_score({}, policy.composite_weights) is None


def test_policy_hash_changes_with_content(tmp_path):
    """policy_hash must actually track content, or historical runs lose their meaning."""
    original = POLICY_PATH.read_text()
    first = tmp_path / "a.yaml"
    first.write_text(original)
    second = tmp_path / "b.yaml"
    second.write_text(original.replace("threshold: 0.85", "threshold: 0.95"))

    assert load_policy(first).content_hash != load_policy(second).content_hash
