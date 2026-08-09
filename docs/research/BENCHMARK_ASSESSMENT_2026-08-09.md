# Benchmark portfolio assessment — 9 August 2026

Assessment of `AI_Cybersecurity_Benchmark_Standard_August_2026.md` against **what the
installed `inspect_evals` can actually run**, and against this tool's two hard constraints:

1. **No sandbox-requiring benchmarks in the automatic gate** (the ExploitGym rule).
2. **Open-weight subject models must be able to produce the measurement** — otherwise a
   score is an artifact of the model's incompetence rather than its security.

Every fact below was probed in-container, not read from the document. Where the document
and the installed package disagree, the package wins.

## Corrections to the research document

| Document claim | Verified reality |
|---|---|
| CodeIPI — "Native", *required* for coding agents | **Not installed.** No `codeipi` / `code_ipi` module exists in the installed catalog. Would need porting. |
| b3 — "Native as `b3`" | Module present, but **building the task raises `ImportError: rouge_score is not installed`** (needs the `b3` extra). Not runnable as shipped. |
| CyberSecEval 4 multi-turn phishing — "100 samples" | The installed task yields **856 samples**. The document's 7,883 total is exactly 756 low as a result (856 − 100). |
| HarmBench — "not in the catalog" | **Correct.** Absent, as stated. |
| CVE-Bench / CyberGym / Cybench / 3CB — native | **Correct**, all present — and all sandbox-requiring, so all belong to a deep-testing tier rather than the gate. |

## Verified properties of every candidate

Probed: module presence, sandbox code, tool definitions, judge arguments, dataset size,
metric keys. `tools` means the package defines tools and scores `tool_calls` — i.e. the
subject must be a competent tool-caller for the number to mean anything.

| Candidate | Installed | Sandbox | Extra models | Tools | n | Open-weight viable |
|---|---|---|---|---|---|---|
| `strong_reject` | yes | none | 1 judge | no | 313 | **yes** |
| `cyse4_autocomplete` | yes | none | **none** | no | 1916 | **yes** |
| `cyse4_malware_analysis` | yes | none | none | no | 609 | yes (60 MB download) |
| `cyse4_threat_intelligence` | yes | none | none | no | 588 | fragile — see below |
| `cyse4_multiturn_phishing` | yes | none | **2** (victim + judge) | no | 856 | yes but costly |
| `agentharm` / `agentharm_benign` | yes | none | **2** (refusal + semantic judge) | **160 tools** | 176 + 176 | **marginal** |
| `b3` | module only | none | — | — | 630 | blocked on `rouge_score` |
| `codeipi` | **no** | — | — | — | — | needs porting |
| `cve_bench`, `cybergym`, `cybench`, `threecb` | yes | **required** | — | — | — | deep-testing tier only |
| `exploitgym`, `sec_bench`, `bountybench` | no | required | — | — | — | excluded (see the ExploitGym rule) |

Live-measured: `strong_reject` at limit 2 took **139s** (~70s/sample) on local
`gemma4` + `qwen35`, metrics `strong_reject_scorer.jailbreak_rate` and
`strong_reject_scorer.strong_reject_metric`. `jailbreak_rate` is lower-is-better.

`cyse4_threat_intelligence` caveat: building it downloads ~60 MB, then tries to fetch PDFs
from `web.archive.org` (which timed out here) and convert them with **poppler**, which is
not in the backend image. It fell back to text and still produced 588 samples, but the path
is network-dependent and partially broken as shipped. It exposes `modality='text'` to skip
image conversion — that is the only configuration worth considering.

## Recommendation

### Add now — real gap, works on open weights

**1. StrongREJECT (`strong_reject`).** The clear winner and the document's strongest call.
It fills a gap I had not previously named: **every injection test we run is indirect** —
untrusted text (`cyse4_multilingual_prompt_injection`), tool output (AgentDojo, ATB). None
measures **direct jailbreak robustness**: an adversarial user attacking the model itself
across 37 attack transformations. Its grader is specifically designed to separate actionable
harmful assistance from empty compliance, which is the failure mode a naive refusal check
gets wrong. No tools, so an open-weight subject can produce a real number; the judge can be
hosted independently. Gate on `jailbreak_rate`, lower-is-better.

**2. `cyse4_autocomplete`.** Cheapest genuine addition in the catalog: **no judge at all**,
1 call per sample, deterministic detection, 1,916 samples. We already gate `cyse4_instruct`
(insecure code when *instructed*); autocomplete measures insecure code during *completion*,
which is how models are actually used in an IDE. Same family, same scoring, different and
arguably more common risk surface.

### Add with an explicit caveat

**3. AgentHarm + AgentHarm Benign.** Genuinely distinct from everything we have: in
AgentDojo and ATB the *data* is malicious and the user is legitimate; in AgentHarm the
**user** is malicious and asks the agent to complete harmful multi-step work with real
tools. Worth adding — but it defines 160 tools and scores `tool_calls`, so it carries the
same defect we already measured: `atb_data_exfil` produced *no score* on gemma4 because the
model emitted a malformed tool call. A weak open-weight subject will score perfectly by
failing to act. The benign companion is exactly the control for that, so **both must be
added together or neither**, with benign utility recorded ungated beside the harmful rate.

### Record, do not gate

**4. `cyse4_malware_analysis`** (and optionally `cyse4_threat_intelligence` at
`modality='text'`). These measure **defensive usefulness** — can the model reason over
malware reports and threat intel — which is a different governance question from "is this
safe to onboard". They answer "is it good enough to rely on for SOC work". Useful as
recorded capability context; thresholding them would gate on capability rather than safety.

### Do not add

- **`cyse4_multiturn_phishing`** — 3 model calls per sample (subject + victim + judge) over
  856 samples makes it the most expensive item in the family, and persuasion/social
  engineering sits closer to harmful-content than to security, which this tool explicitly
  leaves to compliance. Skipped on scope, not just cost.
- **b3** — blocked on an uninstalled extra, and the document itself calls it a
  "supplemental regression suite", not a gate. A 194k-attack corpus is regression testing.
- **CodeIPI** — not installed; revisit if it lands in the catalog. Would be valuable for
  coding agents.
- **Everything sandbox-requiring** — unchanged position.

## Two structural observations from the document worth acting on separately

**Risk tiering, not a binary.** §7.4 separates *safeguards* from *capability* and tiers the
outcome: strong safeguards + high capability → enable under a restricted tier with tighter
logging, egress control and human authorization, rather than a plain pass. Our model is
binary (auto-approve / deep testing) and cannot express that. This is the most interesting
idea in the document and it is a roadmap item, not a benchmark: it needs capability
measurements that all require sandboxes.

**What we already satisfy.** §7.2's "freeze the full experimental specification" is largely
already true here: model snapshot, judge, policy version + content hash, and exact sample ids
are all recorded per run. §7.5's private rotating task set is **not** something we have, and
is a legitimate gap — public benchmarks are contaminated by construction.

**One caution the document raises that applies to us directly:** it reports Anthropic
reviewing 141,000+ cyber-evaluation runs after network misconfiguration let evaluation agents
reach real external systems. Our benchmarks are pure-API or in-memory by policy, which is
what keeps us out of that failure class — worth keeping as the stated reason the rule exists.
