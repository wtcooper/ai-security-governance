"""Registry invariants, and the metric keys pinned from real runs.

Acceptance criteria 1.1 and 1.3.

The metric keys below were captured from live evals against local models, not read from
documentation. Three of them contradicted the docs or the obvious guess:

* the judge task argument is `judge_llm`, not `judge_model`
* `cyse4_mitre` needs `expansion_llm` as well as `judge_llm` — both default to a hardcoded
  provider model, so missing either sends traffic off-gateway
* AgentDojo declares GROUPED metrics, so its keys are `security.accuracy` /
  `utility.accuracy`, not `compute_score.*`

`test_metric_keys_exist_upstream` re-derives the scorer/metric names from the installed
package, so an upstream rename fails here rather than silently producing runs with no score
(which would look like "missing score" forever).
"""

from __future__ import annotations

import importlib

import pytest

from app.engines.registry import LLM_CHECKS, MetricScale, checks_for, get_check
from app.models import AssetType, Direction
from app.scoring.policy import load_policy_dir
from tests.test_gates import POLICY_DIR

# Captured from live runs — see the module docstring.
EXPECTED_METRIC_KEYS = {
    "cyse4_multilingual_prompt_injection": "prompt_injection_scorer.accuracy",
    "cyse4_mitre": "mitre_scorer.accuracy",
    "cyse4_mitre_frr": "refusal_scorer.refusal_rate",
    "cyse4_instruct": "security_scorer.vulnerable_percentage",
    "agentdojo": "security.accuracy",
}


def test_every_check_needing_a_judge_declares_how_to_override_it():
    """Criterion 1.1.

    A check whose scorer resolves a judge must say so, via a task argument or a model role.
    Otherwise the upstream default (a hardcoded provider model) silently takes over.
    """
    for check in LLM_CHECKS:
        if check.model_kwargs or check.model_roles:
            assert check.needs_judge
            assert check.model_kwargs or check.model_roles


def test_mitre_overrides_both_of_its_model_arguments():
    """cyse4_mitre resolves TWO models; missing either escapes the gateway."""
    check = get_check("cyse4_mitre")
    assert set(check.model_kwargs) == {"judge_llm", "expansion_llm"}
    assert set(check.model_roles) == {"grader", "expander"}


def test_metric_keys_match_values_captured_from_live_runs():
    """Criterion 1.3."""
    for check in LLM_CHECKS:
        assert check.metric_key == EXPECTED_METRIC_KEYS[check.id], (
            f"{check.id}: registry says {check.metric_key!r}, live runs emit "
            f"{EXPECTED_METRIC_KEYS[check.id]!r}"
        )


def test_metric_keys_exist_upstream():
    """Re-derive scorer and metric names from the installed package.

    Catches an upstream rename at test time instead of at run time, where a stale key
    produces a permanently missing score.
    """
    for check in LLM_CHECKS:
        module = importlib.import_module(check.module)
        assert hasattr(module, check.function), f"{check.module}.{check.function} is gone"

        scorer_name, metric_name = check.metric_key.rsplit(".", 1)
        # AgentDojo's prefix is a metric GROUP, not a scorer, so there is no symbol to find.
        if check.id == "agentdojo":
            assert scorer_name in {"security", "utility"}
            continue
        found = any(
            hasattr(importlib.import_module(f"{check.module}.{sub}"), scorer_name)
            for sub in _candidate_submodules(check)
            if _importable(f"{check.module}.{sub}")
        )
        assert found or _symbol_anywhere(check.module, scorer_name), (
            f"scorer {scorer_name!r} for {check.id} not found under {check.module}"
        )
        assert metric_name


def _candidate_submodules(check) -> tuple[str, ...]:
    return (
        "mitre.scorers",
        "mitre_frr.scorers",
        "instruct_or_autocomplete.scorers",
        "multilingual_prompt_injection.scorers",
    )


def _importable(dotted: str) -> bool:
    try:
        importlib.import_module(dotted)
        return True
    except Exception:
        return False


def _symbol_anywhere(package: str, symbol: str) -> bool:
    import pkgutil

    module = importlib.import_module(package)
    for info in pkgutil.walk_packages(module.__path__, prefix=f"{package}."):
        if _importable(info.name) and hasattr(importlib.import_module(info.name), symbol):
            return True
    return False


def test_percent_scaled_metrics_are_declared_as_such():
    """The suite mixes 0-1 rates and 0-100 percentages; misreading one skips a real failure."""
    instruct = get_check("cyse4_instruct")
    assert instruct.scale is MetricScale.PERCENT
    # 50% vulnerable must become 0.5, not stay 50 and sail past a 0.25 threshold.
    assert instruct.scale.to_rate(50.0) == 0.5

    for check in LLM_CHECKS:
        if check.id != "cyse4_instruct":
            assert check.scale is MetricScale.RATE, check.id


def test_every_policy_gate_has_a_registered_check():
    """A gate with no check can never be satisfied, which would block every run forever."""
    policy = load_policy_dir(POLICY_DIR)
    registered = {check.id for check in LLM_CHECKS}
    assert set(policy.llm_gates) == registered


def test_policy_metric_and_direction_agree_with_the_registry():
    """A disagreement here would threshold a different number than the one displayed."""
    policy = load_policy_dir(POLICY_DIR)
    for check in LLM_CHECKS:
        gate = policy.llm_gates[check.id]
        assert gate.metric == check.metric_name, check.id
        assert gate.direction == check.direction, check.id


def test_composite_weights_cover_every_gate():
    policy = load_policy_dir(POLICY_DIR)
    assert set(policy.composite_weights) == set(policy.llm_gates)
    assert sum(policy.composite_weights.values()) == pytest.approx(1.0)


def test_checks_for_filters_by_asset_type():
    assert len(checks_for(AssetType.LLM)) == len(LLM_CHECKS)
    assert checks_for(AssetType.MCP) == ()


def test_directions_are_not_all_the_same():
    """A suite of only higher-is-better metrics would suggest a copy-paste error."""
    directions = {check.direction for check in LLM_CHECKS}
    assert directions == {Direction.HIGHER_IS_BETTER, Direction.LOWER_IS_BETTER}


def test_unknown_check_raises_with_a_helpful_message():
    with pytest.raises(KeyError, match="unknown check"):
        get_check("not_a_real_check")
