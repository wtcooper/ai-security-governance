# Enterprise AI Cybersecurity Benchmark Standard

**Evidence-weighted final recommendation — 9 August 2026**
ChatGPT (5.6-sol) + Gemini (3.6-flash)


## Executive summary

The strongest conclusion from the two analyses is that an enterprise should not try to choose one “best cyber benchmark” or collapse cyber safety into one score. The defensible approach is a **layered benchmark portfolio** that separately measures:

1. **Deployed-system safeguards:** resistance to malicious prompts, jailbreaks, indirect prompt injection, poisoned tool output, and harmful tool use, while retaining utility on benign security work.
2. **Underlying cyber capability:** what the model-plus-agent harness can accomplish in a sealed environment if safeguards are bypassed or intentionally relaxed.

These dimensions have different governance meanings. Strong safeguards are desirable. Strong offensive capability is neither a pass nor a failure by itself; it is a **risk-tiering signal** that should trigger tighter access, isolation, monitoring, and human authorization.

### Final recommended benchmark standard

| Evaluation layer | Recommended benchmark | Governance role | Inspect AI status |
|---|---|---|---|
| Direct cyber misuse and false refusals | **CyberSecEval 4** | Core release gate and quarterly full evaluation | Native |
| Direct jailbreak robustness | **StrongREJECT methodology with a maintained cyber behavior set** | Core release gate | Native |
| Harmful multi-step tool use | **AgentHarm plus AgentHarm Benign** | Core gate for tool-enabled agents | Native |
| Indirect prompt injection | **AgentDojo** | Core gate for agents connected to data or services | Native |
| Coding-agent prompt injection | **CodeIPI** | Required for coding agents | Native |
| Real-world web exploitation | **CVE-Bench, zero-day and one-day modes** | Quarterly capability evaluation | Native |
| Large-scale vulnerability reproduction | **CyberGym, stratified 300-task level-1 set** | Quarterly capability evaluation | Native |
| Public CTF comparison | **Cybench pass@1** | External comparison anchor only | Native |
| Broad prompt/tool-attack regression | **b3, stratified slice** | Supplemental regression suite | Native |
| Frontier exploit development | **ExploitGym** | Annual or pre-approval test for advanced cyber agents | Port required |
| Blind vulnerability discovery | **SEC-bench Pro** | Annual frontier evaluation | Port required |
| Detection–exploit–patch balance | **BountyBench** | Optional annual evaluation | Port required |

The minimum production-quality standard should therefore be:

> **CyberSecEval 4 + cyber-adapted StrongREJECT + AgentHarm + AgentDojo + CVE-Bench + CyberGym-300**, with CodeIPI for coding agents, Cybench retained as a public anchor, and ExploitGym or SEC-bench Pro used for annual frontier-risk assessment.

This portfolio is more credible than either an older multiple-choice suite or a short list dominated by CTFs. It covers direct user attacks, indirect prompt injection, harmful tool use, false refusals, insecure code, real CVEs, vulnerability reproduction, and advanced exploit development.

---

## 1. Objective reconciliation of the two analyses

The second analysis correctly identifies the industry shift from static knowledge questions to interactive sandboxed evaluations, and its two-pillar framework is sound. Several implementation details, however, need correction before it can be used as a governance standard.

| Claim in the additional analysis | Evidence-based correction | Effect on recommendation |
|---|---|---|
| CyberSecEval 4 is approximately 1,000 scenarios and costs $10–$30. | The current public Inspect suite has **7,883 unique samples across eight supported tasks**. Inspect’s own April 2026 estimates put a full one-epoch run at approximately **$29–$213 per model**, depending on the model, before the default four epochs on multilingual prompt injection and other role-model calls. | Use a fixed release subset and run the full suite quarterly. Do not plan around a 30–60 minute, $10–$30 full run. |
| CyberSecEval 4 tests MCP tool poisoning. | The supported public Inspect tasks cover MITRE harmful assistance, benign false refusals, insecure code, multilingual prompt injection, phishing, malware analysis, and threat intelligence. They do **not** provide an end-to-end MCP tool-poisoning environment. | Use AgentDojo, CodeIPI, AgentHarm, AgentThreatBench, and b3 for tool-output and agent hijacking risk. |
| HarmBench is native in `inspect_evals/harmbench`. | HarmBench remains a useful external red-teaming framework, but it is **not listed in the current Inspect Evals catalog**. StrongREJECT is native. | Make StrongREJECT the Inspect-native direct-jailbreak baseline; optionally port or run HarmBench as a challenger suite. |
| Cybench is non-saturated and frontier systems achieve roughly 20–75%. | By mid-2026, current frontier systems are near the ceiling, especially at pass@k. Meta reported 92.9% pass@1 for Muse Spark 1.1, while other developers report essentially complete performance at high pass@k. | Retain Cybench for historical and external comparability, not as the decisive frontier gate. |
| 3CB contains 13–32 tasks and is a broad primary agentic suite. | The original benchmark contains **15 challenges**, with four of the most difficult withheld; the publicly runnable surface is therefore small. Its MITRE mapping is valuable, but its statistical coverage and frontier discrimination are limited. | Keep 3CB as a legible diagnostic or demonstration suite, not a core approval gate. |
| CyberGym has more than 6,000 tasks and tests fuzzing and automated patch creation. | The current Inspect implementation has **1,507 benchmark instances from 188 projects**. It tests generation of a working proof of concept against vulnerable and fixed builds. It does not principally grade patch creation. | Use CyberGym for large-scale vulnerability reproduction; use BountyBench or a separate remediation suite for patch quality. |
| A fixed 95% refusal / 5% false-refusal threshold is an appropriate universal gate. | Those figures are not generally justified across tasks, risk classes, or judges. Refusal alone also cannot distinguish weak capability from strong capability with good safeguards. | Use attack success, benign utility, confidence intervals, and comparison to an approved baseline. Apply stricter zero-success designs to explicitly critical actions. |

Authoritative implementation details are available in the current [Inspect Evals catalog](https://github.com/UKGovernmentBEIS/inspect_evals), [CyberSecEval 4 implementation](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/cyberseceval_4), and [CyberGym implementation](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/cybergym).

---

## 2. What current frontier developers actually use

The most informative signal is not popularity alone, but the direction in which frontier developers move when older benchmarks saturate.

| Developer or ecosystem | Publicly emphasized cyber evaluations | Implication |
|---|---|---|
| **OpenAI** | Internal professional CTFs, CVE-Bench, ExploitGym, SEC-bench Pro, and GPT-Red direct/indirect prompt-injection evaluations | OpenAI replaced an earlier CTF set when it became too easy. Even its harder internal 63-task CTF set reached 96.7% for GPT-5.6 Sol, showing that static CTFs are short-lived frontier gates. |
| **Anthropic** | Cybench, CyberGym, ExploitBench, and application-specific prompt-injection tests | Cybench is now mainly an anchor; realistic vulnerability environments receive greater weight. |
| **Meta** | Cybench, ExploitGym, StrongREJECT v2, AgentHarm Verified, and SIREN-style prompt injection | A modern portfolio spans capability, refusal safety, harmful agent behavior, and indirect injection rather than treating them as one category. |
| **Google DeepMind** | CyberGym plus private production vulnerability-discovery evaluation | CyberGym is a prominent public standard, but labs augment it with private fresh tasks. |
| **Microsoft** | CyberGym through a specialized model-and-harness evaluation program | Scores are properties of the model, scaffold, tools, and budget—not the base model alone. |
| **Open-weight developers and xAI** | Cybench, WMDP-Cyber, and CyberSecEval families | These provide broad comparability, although older knowledge benchmarks are weak evidence of operational capability. |

Sources: [OpenAI GPT-5.6 System Card](https://deploymentsafety.openai.com/gpt-5-6), [Meta Muse Spark 1.1 Evaluation Report](https://ai.meta.com/static-resource/muse-spark-1-1-evaluation-report/), [Google DeepMind Gemini 3.5 Flash Cyber](https://deepmind.google/blog/introducing-gemini-3-5-flash-cyber/), and [Microsoft MAI-Cyber-1 and MDASH](https://microsoft.ai/news/introducing-mai-cyber-1-flash-inside-mdash/).

The emerging consensus is to prefer:

- Executable, isolated environments rather than question answering.
- Objective success conditions such as dynamic flags, crash validation, or exploit verification.
- Real source trees and validated historical vulnerabilities.
- Multi-turn tool use with controlled permissions.
- Separate measurements of harmful success, refusal, and benign utility.
- Private or rotating tasks to supplement contaminated public benchmarks.

---

## 3. Detailed assessment of the recommended core

Runtime and API expense vary sharply with model pricing, reasoning effort, context growth, concurrency, retries, and scaffold design. Values marked **reported** come from benchmark maintainers or papers. Values marked **planning estimate** are reasonable budgeting ranges, not promises.

### 3.1 CyberSecEval 4

**Verdict: Adopt as the primary broad cyber-safety family.**

The current Inspect implementation includes:

| Task | Samples | What it measures |
|---|---:|---|
| MITRE ATT&CK harmful assistance | 1,000 | Whether responses provide useful offensive information |
| MITRE false-refusal set | 750 | Over-refusal on benign security work |
| Insecure code, instruction mode | 1,916 | Security weaknesses introduced when following coding instructions |
| Insecure code, autocomplete mode | 1,916 | Security weaknesses introduced during completion |
| Multilingual prompt injection | 1,004 | Instruction override in multiple languages; default effective behavior is four epochs |
| Multi-turn phishing | 100 | Persuasion, rapport, and argumentation over several turns |
| Malware analysis | 609 | Analysis of malware reports |
| Threat-intelligence reasoning | 588 | Reasoning over reports, text, and images |

**Total:** 7,883 unique samples, with more effective model calls when repeated tasks and grader/victim models are included.

**Cost:** Inspect’s April 2026 projection for a full one-epoch suite was approximately $29 for GPT-5 mini, $64 for GPT-5.4 mini, $115 for GPT-5.1, $193 for GPT-5.4, and $213 for Claude Sonnet 4.5. A production run can cost more because multilingual prompt injection defaults to four epochs and some tasks use expansion, victim, or judge models. A prudent planning range is **$50–$500 per production configuration**, or more for high-reasoning models.

**Runtime:** Plan for **2–8 hours** for the full suite with controlled concurrency; a fixed release subset can normally complete in less than two hours.

**Inspect:** Native. The supported task names and current scoring behavior are documented in [Inspect CyberSecEval 4](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/cyberseceval_4).

**Limitation:** It is a family of distinct tasks, not a single score. Cross-task averaging is invalid because the metric meanings differ. Its public autonomous-uplift and autopatching prototypes are intentionally omitted from the supported surface because their environments do not yet provide sufficiently grounded execution and validation.

### 3.2 StrongREJECT with a cyber behavior set

**Verdict: Adopt for direct jailbreak testing; do not rely solely on the original general-harm behaviors.**

StrongREJECT supplies 313 forbidden prompts, 37 jailbreak methods, and a grader designed to distinguish actionable harmful assistance from empty compliance. Its principal strength is evaluator quality and attack diversity. The original paper found that weaker evaluators often overstated jailbreak success. See the [StrongREJECT paper](https://arxiv.org/html/2402.10260v2).

For enterprise cyber governance, use its method against a versioned set of approximately 100–300 cyber behaviors mapped to:

- Your acceptable-use policy.
- MITRE ATT&CK techniques relevant to your environment.
- Malware, credential theft, persistence, exfiltration, privilege escalation, and exploitation.
- Requests that are malicious, ambiguous, or clearly benign.

**Recommended execution:** Five representative attack transformations per behavior at release time; the full attack family quarterly.

**Runtime and cost:** Approximately **20–90 minutes and $10–$75** for a five-attack panel; **2–8 hours and $100–$500** for a full-scale sweep. These are planning estimates.

**Inspect:** Native as `inspect_evals/strong_reject`.

**HarmBench judgment:** HarmBench remains valuable as an independent challenger because it covers hundreds of behaviors and numerous automated attacks, but it is older, broadly harmful rather than cyber-specific, and not currently native in Inspect Evals. Use it annually or after porting; do not make it the sole release gate. See the [HarmBench project](https://www.harmbench.org/) and [paper](https://arxiv.org/html/2402.04249v2).

### 3.3 AgentHarm and benign companion

**Verdict: Adopt for every model that can call tools or take actions.**

The public Inspect task contains 44 harmful base behaviors expanded to 176 cases, plus a benign companion. It tests whether an agent will plan and perform harmful multi-step activities using tools, and whether safety controls cause unacceptable over-refusal.

Report harmful task completion, attempted harmful tool calls, refusal, benign task completion, and false refusal separately.

**Runtime:** **1–3 hours**.

**Cost:** **$25–$250** per model/configuration, planning estimate.

**Inspect:** Native as `agentharm` and `agentharm_benign`; see the [Inspect Evals safeguards catalog](https://github.com/UKGovernmentBEIS/inspect_evals#safeguards).

### 3.4 AgentDojo

**Verdict: Adopt as the primary indirect prompt-injection benchmark.**

AgentDojo contains 97 realistic user tasks and 629 security test cases across workspace, email, calendar, cloud-storage, messaging, travel, and banking environments. Malicious instructions appear inside untrusted data returned by tools. It measures both attack success and whether defenses preserve utility. See the [AgentDojo paper](https://arxiv.org/html/2406.13352v3).

This is more representative of enterprise connector risk than a direct chatbot jailbreak test.

**Runtime:** **2–8 hours**.

**Cost:** **$50–$500**, planning estimate.

**Inspect:** Native as `agentdojo`.

### 3.5 CodeIPI and newer agent-threat tests

**Verdict: Make CodeIPI mandatory for coding agents; treat AgentThreatBench as an emerging supplemental suite.**

CodeIPI embeds malicious instructions in issue descriptions, code comments, and README files while asking the agent to complete legitimate software-engineering work. It measures injection resistance, successful task completion, and detection. This directly addresses the supply-chain and repository context missing from general chatbot tests.

AgentThreatBench maps tests to the 2026 OWASP Top 10 for Agentic Applications, with current Inspect tasks for memory poisoning, autonomy hijacking, and data exfiltration. It is promising but newer and less independently validated than AgentDojo.

**Inspect:** Both are native. See the [current safeguards catalog](https://github.com/UKGovernmentBEIS/inspect_evals#safeguards).

### 3.6 CVE-Bench

**Verdict: Adopt as the primary real-world web-exploitation benchmark.**

CVE-Bench contains 40 critical real-world web-application CVEs spanning eight attack types. It supports:

- **Zero-day mode:** the model is not told which vulnerability exists.
- **One-day mode:** vulnerability information is provided.
- Automatic exploit verification in isolated environments.

OpenAI currently uses a 34-of-40 zero-day configuration with no source access and reports pass@1 across three rollouts. The original benchmark paper reported approximately $0.60–$1.70 per task and roughly 4–60 minutes per task depending on the agent scaffold. See the [CVE-Bench paper](https://arxiv.org/html/2503.17332v4).

**Recommended run:** All supported tasks in both modes, three epochs.

**Runtime:** **2–8 hours** with concurrency.

**Cost:** Approximately **$150–$750** for a three-epoch production evaluation, planning range.

**Inspect:** Native as `cve_bench`.

Pin the exact challenge list and execution backend. A result over 34 tasks is not directly comparable with a result over all 40.

### 3.7 CyberGym

**Verdict: Adopt a stratified 300-task level-1 subset quarterly and the full suite annually for cyber-capable models.**

CyberGym contains 1,507 historical vulnerabilities from 188 open-source projects. The agent must generate a proof of concept that succeeds against the vulnerable build and is checked against the fixed build. Levels 0 and 1 reveal less information than level 3.

**Reported operational scale:** The dataset is 236 GB. Inspect’s May 2026 full level-1 run over all 1,507 samples took **11 hours, 3 minutes** for GPT-4.1 and used a 202-message limit to approximate 100 agent iterations. The paper’s approximate $2-per-task budget implies roughly **$3,000 per full run** and **$600 for a 300-task slice**. See the [Inspect CyberGym implementation and report](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/cybergym) and [CyberGym paper](https://arxiv.org/abs/2506.02548).

**Scope limitation:** CyberGym is strongest for vulnerability reproduction, particularly memory-safety problems in real C/C++ projects. It does not establish reliable end-to-end exploitation, persistence, or patch quality.

### 3.8 Cybench

**Verdict: Retain as an external comparison anchor, not a primary frontier discriminator.**

Inspect includes 39 of the original 40 professional CTF tasks across web, cryptography, reverse engineering, binary exploitation, forensics, and miscellaneous challenges. It is widely reported and therefore useful for comparisons with published model cards. See [Cybench](https://cybench.github.io/) and its [Inspect implementation](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/cybench).

The benchmark is now substantially saturated by frontier agents, especially at pass@k. Report **pass@1**, optionally pass@3, task-level outcomes, and cost. Do not present pass@30 as meaningful evidence of frontier differentiation.

**Runtime:** **4–12 hours**.

**Cost:** **$100–$1,000 per epoch**, planning estimate.

### 3.9 b3

**Verdict: Use as a broad, stratified regression corpus after AgentDojo.**

The Backbone Breaker Benchmark is built from approximately 194,000 crowdsourced attacks involving direct and indirect instruction override, tool invocation, exfiltration, behavior manipulation, denial of service, and tool/system compromise. Running the entire corpus for every release is unnecessary; use a stable stratified set plus a rotating sample.

**Suggested slice:** 2,000 cases, balanced across attack class, application, and security level.

**Runtime:** **1–4 hours**.

**Cost:** **$25–$250**, planning estimate.

**Inspect:** Native as `b3`; see the [b3 benchmark](https://b3.lakera.ai/) and [Inspect catalog](https://github.com/UKGovernmentBEIS/inspect_evals#safeguards).

---

## 4. Frontier and annual benchmarks

### ExploitGym

**Best current public test of genuine exploit development.** The current OpenAI configuration contains 869 challenges: 502 userspace C/C++, 181 V8, and 186 Linux-kernel targets. The agent starts with source/build information, a target, a vulnerability description, and a proof of vulnerability, then must develop a working exploit that retrieves a dynamic out-of-scope flag. A judge checks that the intended vulnerability was used.

Frontier systems remain far from saturation. Published average costs are approximately **$3.40–$34.55 per task**, implying roughly **$3,000–$30,000 for all 869 tasks**. Common per-task caps are two hours, with six-hour research runs also reported. See the [ExploitGym paper](https://arxiv.org/html/2605.11086v1) and [OpenAI GPT-5.6 System Card](https://deploymentsafety.openai.com/gpt-5-6).

**Recommendation:** Run a fixed stratified 100–200 task set annually; run the complete suite only for specialized cyber models or high-risk agent approval. A validated Inspect adapter will require engineering, especially for browser and kernel containment.

### SEC-bench Pro

**Best current candidate for blind vulnerability discovery in hardened software.** Its May 2026 release contains 183 validated V8 and SpiderMonkey vulnerabilities, with Linux coverage being added. Agents receive source code, relevant paths, an instrumented binary, and broad vulnerability categories, but not the original PoC, patch, or crash trace.

Reported settings allow approximately 90 minutes per task. Average costs of **$6.88–$17.93 per task** imply about **$1,300–$3,300 per full run**. The strongest reported systems remain below 40%, so the benchmark is not saturated. See the [SEC-bench Pro paper](https://arxiv.org/html/2605.26548v1).

**Recommendation:** Annual frontier evaluation; port to Inspect only after reproducing official baseline results.

### BountyBench

BountyBench covers 25 software systems and 40 historical bug-bounty vulnerabilities across 27 CWEs. Its detection, exploitation, and patching phases produce 120 primary tasks and let organizations compare offensive and defensive performance in the same environment. See the [BountyBench paper](https://arxiv.org/html/2505.15216v3).

**Recommendation:** Optional annual suite for organizations that care about secure remediation and return on security investment. Budget approximately **$1,000–$10,000+**, depending on model, attempts, and scaffold.

---

## 5. Role of 3CB and HarmBench

### 3CB

3CB’s mapping of challenges to MITRE ATT&CK tactics is useful for executive communication and attack-chain demonstrations. The original work created 15 challenges across the 14 ATT&CK tactic categories, but withheld four of the hardest tasks. The small public set and its 2024 frontier baseline limit statistical confidence and current frontier discrimination. See the [3CB project](https://cybercapabilities.org/) and [paper](https://arxiv.org/html/2410.09114v2).

**Objective recommendation:** Keep 3CB as a low-cost qualitative diagnostic, a harness validation test, or a board-level demonstration. Do not use it instead of CVE-Bench, CyberGym, or ExploitGym.

### HarmBench

HarmBench remains one of the most important historical automated-red-teaming frameworks and includes hundreds of behaviors, numerous attack methods, and text/multimodal coverage. However, it is a 2024 general-harm benchmark, is not currently native in Inspect Evals, and does not itself test whether a cyber agent can exploit a grounded target.

**Objective recommendation:** Use it as an independent annual challenger suite or port selected attacks to the cyber StrongREJECT behavior set. Its inclusion is useful; its omission from the core Inspect pipeline is not a material coverage gap if StrongREJECT, CyberSecEval 4, AgentHarm, AgentDojo, and b3 are present.

---

## 6. Benchmarks that should not drive enablement decisions

| Benchmark family | Appropriate use | Why it should not be a primary gate |
|---|---|---|
| WMDP-Cyber | Cheap hazardous-knowledge diagnostic | Static multiple choice, contamination risk, and knowledge is not operational capability |
| CyberMetric, SecQA, SevenLLM | Training, regression investigation, analyst knowledge | Do not test execution, tools, or exploit success |
| Older CyberSecEval 2 tasks | Historical trend where no current replacement exists | Superseded coverage and increasing saturation |
| InterCode-CTF and small CTF suites | Harness debugging | Limited scope and frontier discrimination |
| 3CB | MITRE-aligned demonstration and qualitative diagnostics | Small public task count and four difficult tasks withheld |
| Cybench pass@30 | Historical compatibility | Frontier saturation conceals important pass@1 differences |
| One combined cyber score | None | Hides the difference between safeguards, benign utility, and dangerous capability |

---

## 7. Governance design in Inspect AI

### 7.1 Evaluate the production system and underlying capability separately

| Configuration | Question answered |
|---|---|
| **Production configuration** | Is the actual served model—with real system prompts, content controls, tools, permissions, and retrieval sources—safe and useful enough to deploy? |
| **Maximum-elicitation configuration** | What can the underlying model-plus-agent accomplish if safeguards are bypassed or intentionally relaxed? |

A refusal is a safeguard success, not proof of low capability. If a closed API does not permit a maximum-elicitation configuration, report the result as **served-system capability**, not base-model capability.

### 7.2 Freeze the full experimental specification

Every result should identify:

- Exact model snapshot and provider endpoint.
- Reasoning effort and sampling parameters.
- System and developer prompts.
- Tool definitions, permissions, and network policy.
- Agent/scaffold version.
- Token, message, time, tool-call, and cost limits.
- Benchmark commit, task version, and exact sample IDs.
- Container or VM image digests.
- Judge model, prompt, and version.
- Epochs, retries, seeds, and error policy.

Inspect supports persistent run configurations, model roles, epochs, and evaluation sets. Use `eval-set` so interrupted runs can resume without silently changing the population. References: [Inspect evaluation sets](https://inspect.aisi.org.uk/reference/inspect_eval-set.html), [model configuration](https://inspect.aisi.org.uk/models.html), and [evaluation options](https://inspect.aisi.org.uk/options.html).

### 7.3 Report a score vector

At minimum, report:

- Direct harmful-assistance attack success rate.
- Direct and indirect prompt-injection success.
- Harmful agent task completion and attempted tool use.
- Benign task success and false-refusal rate.
- Secure-code rate by language and CWE.
- CVE, CTF, and vulnerability-reproduction pass@1.
- A modest pass@k where justified.
- Cost per task and per successful task.
- Tokens, tool calls, wall time, errors, and timeouts.
- Category-level confidence intervals.

Do not compare vendor-reported scores unless task versions, scaffolds, source access, time limits, reasoning budgets, and pass@k are equivalent.

### 7.4 Use risk-based gates, not a universal 95/5 rule

Recommended decision logic:

| Safeguards | Cyber capability | Governance outcome |
|---|---|---|
| Strong | Low or ordinary | Standard enablement subject to normal controls |
| Strong | High | Restricted high-capability tier; stronger identity, logging, rate limits, egress controls, and human authorization |
| Weak | Low or ordinary | Remediate safeguards before enablement |
| Weak | High | Block general deployment; permit only controlled evaluation or explicitly authorized security use |

For explicitly critical behaviors, a useful statistical design is zero successful attacks in at least 300 independent trials, giving an approximate one-sided 95% upper bound near 1% under simple binomial assumptions. For other metrics, compare against the approved incumbent and require confidence intervals that exclude a material safety regression. Preserve benign utility as a co-equal gate.

### 7.5 Maintain private and rotating tasks

Reserve approximately 10–20% of the evaluation program for private, organization-specific, or rotating cases. Include:

- Your actual tools and connector schemas.
- Sanitized examples of internal documents, repositories, and tickets.
- Relevant identity, access, and data-exfiltration paths.
- Incident-derived regression cases.
- Novel prompts and vulnerabilities not publicly indexed.

Public benchmarks provide comparability; private tasks provide freshness and relevance.

---

## 8. Recommended execution cadence

| Cadence or trigger | Required evaluations |
|---|---|
| Every model snapshot | Fixed CyberSecEval 4 release subset; cyber StrongREJECT panel; AgentHarm and benign companion; AgentDojo for connected agents; CodeIPI for coding agents |
| Quarterly | Full CyberSecEval 4; full AgentDojo; b3 stratified slice; Cybench pass@1; CVE-Bench in both modes for three epochs; CyberGym-300 level 1 |
| Annually | Full CyberGym for cyber-capable models; stratified ExploitGym or SEC-bench Pro; optional HarmBench and BountyBench |
| Before enabling an advanced cyber agent | Full capability review including ExploitGym or SEC-bench Pro, plus an organization-specific cyber range |
| After an incident or material tool/architecture change | Targeted replay suite plus all affected core families |

### Approximate budget

| Program | Planning cost per model/configuration | Typical elapsed time with concurrency |
|---|---:|---:|
| Release safety gate | $100–$750 | 2–8 hours |
| Quarterly core portfolio | $1,000–$4,000 | 1–2 operating days |
| Quarterly high-reasoning configuration | $5,000–$10,000 | 1–3 operating days |
| Annual advanced suite | $3,000–$30,000+ | Several days, depending on task caps and cluster size |

These estimates exclude engineering, sandbox infrastructure, artifact storage, benchmark maintenance, and human adjudication. Inspect logs should become the basis for organization-specific cost models after the first baseline run.

---

## 9. Containment requirements

Agentic cyber benchmarks execute untrusted code and may produce working exploits. Run them with:

- Kubernetes, microVM, or equivalently strong isolation.
- Deny-by-default network egress.
- No host filesystem or Docker socket mounts.
- Ephemeral task identities and credentials.
- Private package and container mirrors.
- Explicit destination allowlists when connectivity is unavoidable.
- Tool-call and network telemetry.
- Per-task resource ceilings and kill switches.
- Restricted storage and review of traces containing exploit material.

This is an operational requirement, not merely best practice. In July 2026 Anthropic reported reviewing more than 141,000 cyber-evaluation runs after internet-access misconfigurations allowed evaluation agents to interact with real external systems. See [Anthropic’s cyber-evaluation incident review](https://www.anthropic.com/news/investigating-incidents-cybersecurity-evals).

The sample cost-control command in the additional analysis should also be treated cautiously: Inspect option names and model identifiers evolve. Put supported limits in a version-controlled Inspect run configuration and verify them against the installed [Inspect options reference](https://inspect.aisi.org.uk/options.html), rather than copying an unvalidated CLI example into production.

---

## 10. Final decision

The best objective recommendation is **not** the five-benchmark set of CyberSecEval 4, HarmBench, Cybench, 3CB, and CyberGym as originally proposed. That set has useful ingredients but overstates CyberSecEval 4’s MCP coverage, understates its size and cost, treats HarmBench as natively integrated when it is not, labels Cybench as non-saturated when it is now near the frontier ceiling, overstates CyberGym’s task count and patching scope, and gives too much governance weight to the small public 3CB set.

The strongest August 2026 enterprise standard is:

1. **CyberSecEval 4** for broad cyber safety, secure-code, and false-refusal measurement.
2. **Cyber-adapted StrongREJECT** for systematic direct jailbreak resistance.
3. **AgentHarm plus benign controls** for harmful multi-step tool use.
4. **AgentDojo** for indirect prompt injection in connected agents.
5. **CodeIPI** for coding-agent supply-chain and repository injection.
6. **CVE-Bench** for realistic web exploitation.
7. **CyberGym-300 quarterly and full CyberGym annually** for vulnerability reproduction at scale.
8. **Cybench pass@1** for external comparability only.
9. **b3** for broad regression testing.
10. **ExploitGym or SEC-bench Pro** for annual frontier-risk assessment.
11. **A private rotating organization-specific set** to address contamination and actual enterprise attack paths.

This design is Inspect-first, grounded in what current frontier developers are reporting, resistant to benchmark saturation, and aligned with the actual governance decision: not simply whether a model is “good at cybersecurity,” but whether a particular model, scaffold, tool configuration, and control environment can be enabled at an acceptable level of risk.

