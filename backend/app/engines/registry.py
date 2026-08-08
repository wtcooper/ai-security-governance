"""The benchmark registry: what we run, how it is routed, and what we read from it.

Every fact in here was read off a real run or the installed package source, not from
documentation. Two of them contradicted the docs, which is why the rule exists:

* The judge task argument is `judge_llm`, not `judge_model`.
* `cyse4_mitre` takes **two** model arguments — `expansion_llm` as well as `judge_llm`.
  Both default to a hardcoded `openai/gpt-4o-mini`, so missing either one sends traffic to a
  real provider.

Both are also reachable as Inspect model *roles* (`grader`, `expander`), which is the more
robust override because a scorer can use a role without exposing a task argument. We set
both the task arguments and the roles, and the credential scrubbing in `inspect_child`
catches anything either mechanism misses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.models import AssetType, Direction


class MetricScale(StrEnum):
    """The units a scorer actually reports in.

    This is not pedantry — the suite genuinely mixes them. `accuracy` and `refusal_rate` come
    back as 0-1 rates, while `vulnerable_percentage` and `pass_rate` come back as 0-100
    percentages (they are built from a `percentage_of` helper upstream). Reading 50.0 as a
    fraction would compare it against a 0.25 threshold and pass a model that writes insecure
    code half the time.

    Everything is converted to a 0-1 RATE before it is stored, so `Score.raw_value` and every
    threshold in policy.yaml share one unit.
    """

    RATE = "rate"  # already 0-1
    PERCENT = "percent"  # 0-100, divided by 100 on ingest

    def to_rate(self, value: float) -> float:
        return value / 100.0 if self is MetricScale.PERCENT else value


@dataclass(frozen=True)
class Check:
    """One benchmark. One score. One threshold."""

    id: str
    asset_type: AssetType
    # Import path of the task builder, resolved lazily so the API process never imports the
    # heavy eval packages.
    module: str
    function: str
    # The single metric the gate reads, as `<scorer_name>.<metric_name>` exactly as Inspect
    # emits it. Verified against live output — see tests/test_registry.py.
    metric_key: str
    metric_name: str
    direction: Direction
    scale: MetricScale = MetricScale.RATE
    # Static kwargs for the task builder.
    task_kwargs: dict[str, object] = field(default_factory=dict)
    # Task kwargs that must receive a gateway model string. Empty means the task needs no
    # judge; a non-empty value means an un-overridden default would escape to a provider.
    model_kwargs: tuple[str, ...] = ()
    # Inspect model roles this task's scorers resolve, same reasoning.
    model_roles: tuple[str, ...] = ()
    # Sample cap for a routine governance run. Full datasets are 750-1916 samples, which on a
    # local model is hours; the cap keeps a run to minutes. Raise for a calibration run.
    default_limit: int = 20
    description: str = ""

    @property
    def needs_judge(self) -> bool:
        return bool(self.model_kwargs or self.model_roles)


LLM_CHECKS: tuple[Check, ...] = (
    Check(
        id="cyse4_multilingual_prompt_injection",
        asset_type=AssetType.LLM,
        module="inspect_evals.cyberseceval_4",
        function="cyse4_multilingual_prompt_injection",
        metric_key="prompt_injection_scorer.accuracy",
        metric_name="accuracy",
        direction=Direction.HIGHER_IS_BETTER,
        # epochs defaults to 4 upstream, which quadruples cost for no governance benefit.
        task_kwargs={"epochs": 1},
        model_kwargs=("judge_llm",),
        model_roles=("grader",),
        description="Resists prompt injection delivered across languages.",
    ),
    Check(
        id="cyse4_mitre",
        asset_type=AssetType.LLM,
        module="inspect_evals.cyberseceval_4",
        function="cyse4_mitre",
        metric_key="mitre_scorer.accuracy",
        metric_name="accuracy",
        direction=Direction.HIGHER_IS_BETTER,
        model_kwargs=("judge_llm", "expansion_llm"),
        model_roles=("grader", "expander"),
        # Two judged model calls per sample, so this is the most expensive check we ship.
        default_limit=10,
        description="Refuses to assist with MITRE ATT&CK-mapped offensive tradecraft.",
    ),
    Check(
        id="cyse4_mitre_frr",
        asset_type=AssetType.LLM,
        module="inspect_evals.cyberseceval_4",
        function="cyse4_mitre_frr",
        metric_key="refusal_scorer.refusal_rate",
        metric_name="refusal_rate",
        direction=Direction.LOWER_IS_BETTER,
        description=(
            "Over-refusal on benign security questions. Paired with cyse4_mitre so a model "
            "cannot pass by refusing everything, but gated on its own metric."
        ),
    ),
    Check(
        id="cyse4_instruct",
        asset_type=AssetType.LLM,
        module="inspect_evals.cyberseceval_4",
        function="cyse4_instruct",
        metric_key="security_scorer.vulnerable_percentage",
        metric_name="vulnerable_percentage",
        direction=Direction.LOWER_IS_BETTER,
        # Reported 0-100 upstream, not 0-1.
        scale=MetricScale.PERCENT,
        description="Generates insecure code when asked to write code (semgrep detector).",
    ),
    Check(
        id="agentdojo",
        asset_type=AssetType.LLM,
        module="inspect_evals.agentdojo",
        function="agentdojo",
        # AgentDojo declares GROUPED metrics, so the group name replaces the scorer name in
        # the metric key: the live keys are `security.accuracy` and `utility.accuracy`, not
        # `compute_score.*`. A HIGH security value means the injected instruction did NOT
        # succeed, so this is higher-is-better rather than an attack-success rate.
        #
        # INTERPRETATION CAVEAT: security accuracy is only meaningful alongside utility. A
        # model too weak to call tools scores a perfect 1.0 here simply by failing to act.
        # `utility.accuracy` is therefore recorded as an ungated metric and shown next to
        # this one, so a suspiciously perfect security score can be read in context.
        metric_key="security.accuracy",
        metric_name="security_accuracy",
        direction=Direction.HIGHER_IS_BETTER,
        # Sandbox suites need Docker-in-Docker; excluded so the suite stays pure-API.
        task_kwargs={"with_sandbox_tasks": "no"},
        default_limit=10,
        description="Falls for injected instructions while using tools.",
    ),
)

CHECKS_BY_ID: dict[str, Check] = {check.id: check for check in LLM_CHECKS}


def checks_for(asset_type: AssetType) -> tuple[Check, ...]:
    return tuple(check for check in LLM_CHECKS if check.asset_type is asset_type)


def get_check(check_id: str) -> Check:
    try:
        return CHECKS_BY_ID[check_id]
    except KeyError:
        raise KeyError(
            f"unknown check {check_id!r}; known: {sorted(CHECKS_BY_ID)}"
        ) from None
