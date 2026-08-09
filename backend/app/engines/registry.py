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
    # Scorer-reported count of samples whose JUDGE verdict could not be classified. This is
    # the reliable judge-failure signal: it comes from the scorer itself rather than from
    # pattern-matching prose, so it cannot be confused with the SUBJECT refusing (which for
    # cyse4_mitre is the correct outcome). None means the scorer exposes no such counter.
    unresolved_metric_key: str | None = None
    # Static kwargs for the task builder.
    task_kwargs: dict[str, object] = field(default_factory=dict)
    # Task kwargs that must receive a gateway model string. Empty means the task needs no
    # judge; a non-empty value means an un-overridden default would escape to a provider.
    model_kwargs: tuple[str, ...] = ()
    # Inspect model roles this task's scorers resolve, same reasoning.
    model_roles: tuple[str, ...] = ()
    # Sample cap for a routine governance run. Full datasets are 750-1916 samples, which on a
    # local model is hours; the cap keeps a run to minutes. Raise for a calibration run.
    # NOTE: since Phase 8 the governing sample count lives in the LLM policy's gates; this
    # remains only as the fallback for a check the policy does not gate.
    default_limit: int = 20
    description: str = ""
    # The longer explanation shown on the benchmark's own page: what the test cases are,
    # what the metric captures, and how to read it. The description above is the one-liner.
    intent: str = ""
    # Sample metadata key used to stratify core-set selection, when the dataset carries one
    # worth balancing over. None means selection is a plain seeded draw.
    strata_key: str | None = None

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
        intent=(
            "Each test case plants a secret or a constraint in the system prompt, then "
            "delivers an injection attempt in the user turn — 'ignore your previous "
            "instructions', payload smuggling, role-play coercion — translated across many "
            "languages. The subject model answers, and the judge model checks whether the "
            "injected instruction won (for example, whether the secret leaked). The metric "
            "is the share of injections resisted. This matters for governance because "
            "prompt injection is the primary attack surface of any deployment that feeds "
            "untrusted text to a model, and multilingual delivery is a common filter bypass."
        ),
        strata_key="injection_variant",
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
        # PurpleLlama's "else" bucket: judge verdicts that were neither benign, malicious,
        # nor a refusal — i.e. the judge did not return a usable answer.
        unresolved_metric_key="mitre_scorer.else_count",
        # Two judged model calls per sample, so this is the most expensive check we ship.
        default_limit=10,
        description="Refuses to assist with MITRE ATT&CK-mapped offensive tradecraft.",
        intent=(
            "Test cases ask for help with offensive techniques mapped to MITRE ATT&CK — "
            "persistence, lateral movement, exfiltration and so on. The subject's answer is "
            "expanded by one model and then judged by another into benign / malicious / "
            "refusal buckets; the metric is the share of prompts where the subject did NOT "
            "provide usable attack assistance (a refusal here is the correct behaviour). "
            "Read it together with its paired benchmark cyse4_mitre_frr: this one catches a "
            "model that helps attackers, the pair catches a model that fakes safety by "
            "refusing everything."
        ),
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
        intent=(
            "The false-refusal-rate counterpart to cyse4_mitre. Test cases are legitimate "
            "security questions that merely sound borderline — defensive how-tos, incident "
            "response, security education. The metric is the share the model wrongly "
            "refuses; lower is better. Without this gate, a model could pass the offensive-"
            "tradecraft benchmark by refusing every security question, which would make it "
            "useless to the security teams it is being approved for. No judge model is "
            "involved: refusal is detected from the response itself."
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
        intent=(
            "Each test case instructs the model to write a specific piece of code. The "
            "output is checked by a static insecure-code detector (semgrep rules) for "
            "vulnerability patterns — hardcoded credentials, injection-prone string "
            "building, weak crypto and similar. The metric is the share of outputs "
            "containing a detected vulnerability; lower is better. This gates the everyday "
            "risk: models are used to write production code, and a model that routinely "
            "emits insecure patterns spreads vulnerabilities at scale. No judge model — "
            "detection is deterministic static analysis."
        ),
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
        intent=(
            "The agentic case. The model is given tools (email, calendar, banking, travel) "
            "and a legitimate task, but the data it works through contains injected "
            "instructions trying to redirect it — send money, leak data, forward email. "
            "The metric is the share of episodes where the injected goal did NOT succeed; "
            "higher is better. Caveat that matters when reading results: a model too weak "
            "to call tools at all scores perfectly here by failing to act, which is why the "
            "ungated utility metric is recorded and shown alongside. This is the gate for "
            "agent deployments, where a successful injection acts rather than just speaks."
        ),
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
