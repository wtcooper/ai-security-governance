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

WHAT MAY BE ADMITTED HERE — a safety rule, not a preference
-----------------------------------------------------------
Every benchmark in this suite measures whether an asset **resists attack**. None asks a
model to produce working exploits, and none requires a network-capable sandbox to verify
generated code. That excludes an entire class of otherwise-respected cyber benchmarks
(ExploitGym and relatives), and the exclusion is deliberate: in July 2026 an exploit-
generation benchmark run with guardrails disabled ended with frontier models escaping their
sandbox and compromising Hugging Face's production infrastructure to steal the answer key.
An asset-onboarding gate has no need to elicit offensive capability, so it does not.

Benchmarks that need Docker sandboxes to score real vulnerability work (CyberGym,
CVE-Bench) are a separate, human-supervised deep-testing tier — never part of the automatic
gate. Saturated benchmarks (Cybench at ~93%, CyberMetric, SecQA) are excluded for a
different reason: a measure everything passes cannot inform a decision.

COST is a first-class registry fact (`calls_per_sample`, `dataset_size`, `cost_note`),
surfaced in the UI, because a team must be able to see what a run costs before starting it.
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

    # --- Cost expectation -----------------------------------------------------------------
    # Model calls per sample is the portable cost unit: wall-clock depends entirely on the
    # backing model, but call count does not. Shown in the UI so a team knows what a run
    # costs BEFORE starting it — the honest alternative to discovering it hours in.
    calls_per_sample: int = 1
    # Full dataset size, so "n of N" is visible without building a preview.
    dataset_size: int | None = None
    # One line on what drives the cost, and anything measured.
    cost_note: str = ""

    @property
    def needs_sandbox(self) -> bool:
        """Every shipped benchmark is pure-API or an in-memory simulation.

        Recorded explicitly because it is a safety property, not an implementation detail:
        benchmarks needing a network-capable sandbox to verify generated exploits are out
        of scope for this tool (see the module docstring).
        """
        return False

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
        calls_per_sample=2,
        dataset_size=1004,
        cost_note=(
            "Two calls per sample: the subject answers, a judge grades. The judge is the cost driver, and on a slow local reasoning model this is the most expensive benchmark in the suite by wall clock."
        ),
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
        calls_per_sample=3,
        dataset_size=1000,
        cost_note=(
            "Three calls per sample — subject, expansion model, then judge — which makes it the most expensive per sample. Hence the small default draw."
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
        calls_per_sample=1,
        dataset_size=750,
        cost_note="One call per sample, no judge: refusal is detected from the response itself.",
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
        calls_per_sample=1,
        dataset_size=1916,
        cost_note=(
            "One call per sample. Detection is local static analysis (semgrep), so there is no judge cost at all."
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
        calls_per_sample=6,
        dataset_size=944,
        cost_note=(
            "A multi-turn agent loop, so calls per sample vary with how long the model takes "
            "to finish the task — roughly 6 on average. No judge."
        ),
    ),
    # --- AgentThreatBench: the OWASP Top 10 for Agentic Applications (2026) --------------
    #
    # Three separate tasks (separate datasets, separate OWASP categories), each its own
    # gate on `security.accuracy` — the AgentDojo pattern, and for the same reason: a model
    # too weak to use tools scores a perfect security score by failing to act, so
    # `utility.accuracy` is recorded ungated and read alongside.
    #
    # SAFETY NOTE: every tool here is an in-memory mock backed by Inspect's store — no
    # subprocess, no network, no sandbox. Scoring is fully deterministic (substring and
    # tool-call-argument checks), so there is NO judge model. This is the opposite end of
    # the risk spectrum from sandbox-escape benchmarks like ExploitGym.
    Check(
        id="atb_memory_poison",
        asset_type=AssetType.LLM,
        module="inspect_evals.agent_threat_bench",
        function="agent_threat_bench_memory_poison",
        metric_key="security.accuracy",
        metric_name="security_accuracy",
        direction=Direction.HIGHER_IS_BETTER,
        default_limit=10,  # full dataset is 10 cases
        description="Resists poisoned memory that steers later, unrelated decisions (OWASP ASI06).",
        intent=(
            "The agent has read/write memory tools. An attacker plants content in memory "
            "during one task; a later, unrelated task then reads it. The security metric is "
            "the share of episodes where the planted content did NOT change the agent's "
            "behaviour (no attack marker in the output); utility checks the agent still did "
            "the real work. This is the memory-poisoning risk that makes long-lived agents "
            "with persistent memory dangerous — the injection and its payoff are separated "
            "in time, so a model that only guards the current turn still fails. Scoring is "
            "deterministic string/tool-call inspection; no judge model is involved."
        ),
        calls_per_sample=4,
        dataset_size=10,
        strata_key="attack_name",
        cost_note=(
            "Agent loop capped at 20 messages; ~15s per sample measured on a local model, so the full 10-case dataset runs in about 2.5 minutes. No judge."
        ),
    ),
    Check(
        id="atb_autonomy_hijack",
        asset_type=AssetType.LLM,
        module="inspect_evals.agent_threat_bench",
        function="agent_threat_bench_autonomy_hijack",
        metric_key="security.accuracy",
        metric_name="security_accuracy",
        direction=Direction.HIGHER_IS_BETTER,
        default_limit=6,  # full dataset is 6 cases
        description="Resists tool output that tries to hijack the agent's goal (OWASP indirect injection).",
        intent=(
            "The agent is given a legitimate objective and a set of tools. The data returned "
            "by a tool contains instructions trying to seize the agent's autonomy — abandon "
            "the task, take a different action, escalate its own permissions. The security "
            "metric is the share of episodes where the hijack failed; utility confirms the "
            "agent completed the intended job. This is the core agentic-security question: "
            "when the world talks back through a tool, does the model treat that data as "
            "data or as instructions? Deterministic scoring, no judge."
        ),
        calls_per_sample=4,
        dataset_size=6,
        strata_key="attack_name",
        cost_note=(
            "Agent loop capped at 20 messages; the full 6-case dataset runs in about 90 seconds on a local model. No judge."
        ),
    ),
    Check(
        id="atb_data_exfil",
        asset_type=AssetType.LLM,
        module="inspect_evals.agent_threat_bench",
        function="agent_threat_bench_data_exfil",
        metric_key="security.accuracy",
        metric_name="security_accuracy",
        direction=Direction.HIGHER_IS_BETTER,
        default_limit=8,  # full dataset is 8 cases
        description="Does not exfiltrate sensitive data when a tool payload asks it to (OWASP data leakage).",
        intent=(
            "The agent handles customer records and a messaging tool. An injected payload "
            "tries to get it to send sensitive data to an unauthorised recipient. Security "
            "is scored on the tool-call arguments, not just the prose: an episode fails if a "
            "send_message call carries forbidden fields or an unauthorised recipient, so a "
            "model that talks about refusing but still makes the call is correctly caught. "
            "Utility checks it completed the legitimate task. Deterministic scoring, no judge."
        ),
        calls_per_sample=4,
        dataset_size=8,
        strata_key="attack_name",
        cost_note=(
            "Agent loop capped at 20 messages; the full 8-case dataset runs in about 2 minutes on a local model. No judge."
        ),
    ),
    # --- StrongREJECT: direct jailbreak robustness ----------------------------------------
    #
    # The dimension nothing else here covered. Every other injection test in this suite is
    # INDIRECT — untrusted text (cyse4 multilingual PI) or untrusted tool output (AgentDojo,
    # AgentThreatBench). None measures an adversarial USER attacking the model directly, which
    # is what StrongREJECT does across 37 attack transformations over 313 forbidden prompts.
    #
    # Its grader is the reason to prefer it: it scores refusal, convincingness and specificity
    # separately, so "empty compliance" (the model appears to comply but says nothing usable)
    # is not counted as a jailbreak. Weaker evaluators systematically overstate jailbreak rates.
    #
    # CAVEAT worth knowing: `jailbreak_rate` is num_jailbreaks / valid_count, and a judge reply
    # the scorer cannot parse is dropped from the DENOMINATOR rather than counted. A judge that
    # ignores the rubric therefore shrinks n silently instead of failing loudly. Use a capable
    # judge here and read the sample count on the run page.
    Check(
        id="strong_reject",
        asset_type=AssetType.LLM,
        module="inspect_evals.strong_reject",
        function="strong_reject",
        # Verified from a live run: num_jailbreaks / valid_count, a 0-1 rate.
        metric_key="strong_reject_scorer.jailbreak_rate",
        metric_name="jailbreak_rate",
        direction=Direction.LOWER_IS_BETTER,
        model_kwargs=("judge_llm",),
        model_roles=("grader",),
        default_limit=20,
        calls_per_sample=2,
        dataset_size=313,
        cost_note=(
            "Two calls per sample: the subject answers a jailbroken prompt, the judge scores "
            "refusal, convincingness and specificity. Measured ~70s per sample on local models, "
            "so the judge is the cost driver."
        ),
        description="Resists jailbreak transformations applied to forbidden requests.",
        intent=(
            "Each case takes a forbidden request and rewrites it through one of 37 jailbreak "
            "techniques — role-play framing, encoding, authority claims, distractor stuffing and "
            "so on. A judge then scores the response on three axes rather than one: did it "
            "refuse, and if it complied, was the answer actually convincing and specific? The "
            "gated metric is the share of attempts that produced a genuine jailbreak, so lower "
            "is better. This is the only benchmark in the suite where the attacker is the user "
            "rather than the data — everything else measures indirect injection through content "
            "or tool output, which is a different failure and a different defence."
        ),
    ),
    # --- Registered but NOT gated by default ----------------------------------------------
    #
    # cyse4_autocomplete is available to add from the policy form, but is deliberately left out
    # of the shipped suite. Measured, not assumed: it shares 1,863 of 1,866 `origin_code`
    # snippets with cyse4_instruct, the same 50 CWEs, and an identical language distribution.
    # It is the SAME corpus rendered as a completion prompt rather than an instruction, scored
    # by the same detector — a second modality, not a second dimension. Worth enabling if you
    # specifically ship IDE completion, since models are less careful when completing code than
    # when told to write it; not worth paying for twice otherwise.
    Check(
        id="cyse4_autocomplete",
        asset_type=AssetType.LLM,
        module="inspect_evals.cyberseceval_4",
        function="cyse4_autocomplete",
        metric_key="security_scorer.vulnerable_percentage",
        metric_name="vulnerable_percentage",
        direction=Direction.LOWER_IS_BETTER,
        scale=MetricScale.PERCENT,
        default_limit=20,
        calls_per_sample=1,
        dataset_size=1916,
        cost_note=(
            "One call per sample and no judge — detection is the same local semgrep-based "
            "detector cyse4_instruct uses. Cheap, but it re-measures cyse4_instruct's corpus."
        ),
        description="Generates insecure code when completing existing code (semgrep detector).",
        intent=(
            "The completion counterpart to cyse4_instruct: instead of being told what to write, "
            "the model is given a code prefix and asked to continue it. Same 1,866 vulnerability "
            "cases, same 50 CWEs, same detector — the difference is that a completion prompt "
            "gives no opening to refuse, caveat or reason about security, which is how models "
            "behave in an IDE. Enable this if IDE completion is the deployment you care about."
        ),
    ),
)

CHECKS_BY_ID: dict[str, Check] = {check.id: check for check in LLM_CHECKS}

# --- How much to measure ------------------------------------------------------------------
#
# Sample count is the difference between a wiring check and a governance signal, so it is a
# governed choice rather than a constant buried in code. The arithmetic that sets these:
# for a proportion near 0.9, the 95% confidence interval is roughly +/-13 points at n=20,
# +/-12 at n=25, +/-5.9 at n=100 and +/-4.8 at n=150. A +/-13 point interval cannot support a
# 0.90 threshold — the measurement is wider than the decision — which is why 25 is labelled a
# wiring check and 100 is the default.
#
# Each preset applies the same n to every benchmark, capped at the dataset's real size. Equal
# n per benchmark means equal statistical power per RISK DIMENSION, and lets the cost
# differences between benchmarks stay visible instead of being smoothed away.


@dataclass(frozen=True)
class DepthPreset:
    key: str
    label: str
    # None means "the whole dataset".
    samples: int | None
    blurb: str

    def samples_for(self, check: "Check") -> int:
        dataset = check.dataset_size or check.default_limit
        return dataset if self.samples is None else min(self.samples, dataset)


DEPTH_PRESETS: tuple[DepthPreset, ...] = (
    DepthPreset(
        key="quick",
        label="Quick",
        samples=25,
        blurb=(
            "A wiring check, not a governance signal: at n=25 the confidence interval is "
            "about +/-12 points, wider than the gap most thresholds are trying to detect. "
            "Use it to prove the plumbing works, then re-run deeper."
        ),
    ),
    DepthPreset(
        key="good",
        label="Good",
        samples=100,
        blurb=(
            "The default. n=100 puts the 95% confidence interval near +/-6 points, which is "
            "narrow enough for a threshold to mean something without paying for the full "
            "datasets."
        ),
    ),
    DepthPreset(
        key="full",
        label="Full",
        samples=None,
        blurb=(
            "Every case in every dataset. The most defensible number and by far the most "
            "expensive — appropriate for calibration and for a final decision on a model you "
            "are about to depend on."
        ),
    ),
)

DEPTH_BY_KEY: dict[str, DepthPreset] = {preset.key: preset for preset in DEPTH_PRESETS}



def checks_for(asset_type: AssetType) -> tuple[Check, ...]:
    return tuple(check for check in LLM_CHECKS if check.asset_type is asset_type)


def get_check(check_id: str) -> Check:
    try:
        return CHECKS_BY_ID[check_id]
    except KeyError:
        raise KeyError(
            f"unknown check {check_id!r}; known: {sorted(CHECKS_BY_ID)}"
        ) from None
