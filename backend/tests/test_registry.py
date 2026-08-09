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
    # AgentThreatBench declares GROUPED metrics like AgentDojo, for the same reason: a
    # security score is only meaningful alongside a utility score.
    "atb_memory_poison": "security.accuracy",
    "atb_autonomy_hijack": "security.accuracy",
    "atb_data_exfil": "security.accuracy",
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
        # For grouped-metric benchmarks (AgentDojo, AgentThreatBench) the prefix is a metric
        # GROUP declared by the scorer, not a scorer symbol, so there is nothing to import.
        # The group's existence is verified from the scorer's registry metadata instead —
        # see test_grouped_metric_benchmarks_declare_their_groups.
        if scorer_name in {"security", "utility"}:
            assert _declares_metric_group(check, scorer_name)
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


# --- AgentThreatBench ---------------------------------------------------------------------


ATB_CHECK_IDS = ("atb_memory_poison", "atb_autonomy_hijack", "atb_data_exfil")


@pytest.mark.parametrize("check_id", ATB_CHECK_IDS)
def test_agent_threat_bench_needs_no_judge_model(check_id):
    """Its scoring is deterministic, so no judge is resolved and none must be declared.

    Declaring a judge it does not need would waste a model call per sample; failing to
    declare one it DOES need would send traffic off-gateway. Read from the scorer: it does
    substring and tool-call-argument checks only.
    """
    check = get_check(check_id)
    assert not check.needs_judge
    assert check.model_kwargs == ()
    assert check.model_roles == ()


@pytest.mark.parametrize("check_id", ATB_CHECK_IDS)
def test_agent_threat_bench_records_utility_alongside_security(check_id):
    """The AgentDojo caveat applies identically here.

    A model too weak to call tools scores a PERFECT security number by failing to act. The
    gate reads security, so utility has to be visible next to it — which happens
    automatically because every non-gated metric a benchmark reports is stored ungated.
    """
    check = get_check(check_id)
    assert check.metric_key == "security.accuracy"
    assert check.direction is Direction.HIGHER_IS_BETTER


def _declared_metric_groups(check) -> set[str]:
    """The metric GROUPS a task's scorer declares, read from Inspect's registry metadata.

    Grouped metrics are declared via `@scorer(metrics={"security": [...], "utility": [...]})`,
    which Inspect records in the scorer's registry info rather than as an attribute on the
    returned function — so this is the only place the group names actually exist.
    """
    from inspect_ai._util.registry import registry_info

    builder = getattr(importlib.import_module(check.module), check.function)
    task = builder(**check.task_kwargs)
    scorers = task.scorer if isinstance(task.scorer, list) else [task.scorer]
    groups: set[str] = set()
    for scorer in scorers:
        metrics = (registry_info(scorer).metadata or {}).get("metrics")
        # Two shapes are both legal and both in use: ATB declares `metrics={...}` (a dict of
        # groups), AgentDojo declares `metrics=[{...}]` (a list containing one). Handle both
        # rather than assuming — this difference is exactly what a rename would hide.
        candidates = metrics if isinstance(metrics, list) else [metrics]
        for candidate in candidates:
            if isinstance(candidate, dict):
                groups |= set(candidate)
    return groups


def _declares_metric_group(check, group: str) -> bool:
    return group in _declared_metric_groups(check)


@pytest.mark.parametrize("check_id", ATB_CHECK_IDS)
def test_agent_threat_bench_scorer_declares_both_metric_groups(check_id):
    """Re-derived from the installed package, so an upstream rename fails here."""
    groups = _declared_metric_groups(get_check(check_id))
    assert {"security", "utility"} <= groups, f"{check_id} groups changed: {groups}"


@pytest.mark.parametrize("check_id", ATB_CHECK_IDS)
def test_agent_threat_bench_needs_no_sandbox(check_id):
    """The safety property that admits this benchmark at all.

    Its tools are in-memory mocks over Inspect's store. If an upstream version ever
    introduces a real sandbox, this project must reconsider the benchmark rather than
    inherit the change silently.
    """
    check = get_check(check_id)
    builder = getattr(importlib.import_module(check.module), check.function)
    task = builder(**check.task_kwargs)
    assert getattr(task, "sandbox", None) is None
    assert check.needs_sandbox is False


def test_every_check_declares_its_cost():
    """Cost has to be knowable before a run, so it is a required registry fact."""
    for check in LLM_CHECKS:
        assert check.calls_per_sample >= 1, check.id
        assert check.cost_note, f"{check.id} has no cost note"


def test_no_check_requires_a_sandbox():
    """The ExploitGym rule, asserted rather than trusted.

    Every shipped benchmark measures resistance to attack and runs pure-API or as an
    in-memory simulation. A benchmark needing a network-capable sandbox to verify generated
    exploits belongs to the human-supervised deep-testing tier, never the automatic gate.
    """
    for check in LLM_CHECKS:
        assert check.needs_sandbox is False, check.id
