# Benchmark details

Deeper discussion behind the suite table in the [README](../README.md#what-gets-measured). This
document covers only the **AI-model** asset class: MCP servers and agent skills are not
benchmarked at all, because no published benchmark can score an artifact someone submits. For
those the scanner *is* the evaluation and the gate is a severity rule.

## Why these seven

The suite is chosen by **risk dimension**, not by reputation. One benchmark per dimension, no
dimension counted twice, and each one has to earn its compute. Seven gates cover seven
dimensions:

| Benchmark | Dimension it covers | Why it is in the set |
|---|---|---|
| `cyse4_mitre` | Direct misuse | Will it help an attacker who simply asks? The baseline question. |
| `cyse4_mitre_frr` | Over-refusal | Its mandatory pair — without it a model passes the above by refusing everything, which is useless to a security team. |
| `strong_reject` | Jailbreak robustness | The only gate where the **attacker is the user**. 37 attack transformations, and a grader that scores refusal, convincingness and specificity separately so empty compliance is not mistaken for a jailbreak. |
| `cyse4_instruct` | Insecure code | The everyday risk: models write production code. Deterministic semgrep detection, no judge. |
| `cyse4_multilingual_prompt_injection` | Injection via content | Untrusted text overriding instructions, across languages — a common filter bypass. |
| `agentdojo` | Injection via tools | Untrusted **tool output** redirecting an agent mid-task, over 629 security cases in realistic environments. |
| `atb_memory_poison` | Memory poisoning | OWASP ASI06: an injection planted in one task that pays off in a later, unrelated one — the only dimension where attack and effect are separated in time. |

One caveat worth stating plainly: `agentdojo` and `atb_memory_poison` score security from
tool-call behaviour, so **a model too weak to call tools reliably scores well by failing to
act.** Both record an ungated utility metric beside the security one for exactly this reason —
read them together, or the number flatters incompetence. (We measured this: one
AgentThreatBench task produced *no score at all* on a small local model because it emitted a
malformed tool call.)

## How much to measure

Sample count is the difference between a wiring check and a governance signal, so it is a
policy setting with three presets on the Policies page rather than a constant in the code:

| Depth | Samples per benchmark | Suite total | 95% CI near a 0.9 pass rate |
|---|---|---|---|
| Quick | 25 | 160 tests · ~415 calls | ±12 points — a wiring check, not a signal |
| **Good** (default) | **100** | **610 tests · ~1,540 calls** | **±6 points** |
| Full | whole dataset | 5,937 tests · ~14,000 calls | narrowest; for calibration and final decisions |

An interval wider than the decision cannot support the decision — that is why 25 is labelled
a wiring check and 100 is the default. Each preset applies the same n to every benchmark
(capped at the real dataset size) so every risk dimension gets equal statistical power. The
Policies page shows the resulting totals before you commit to a run, and any gate can be
overridden individually, or pinned to a fixed **core set** of sample ids for exact
repeatability.

## Also available, deliberately not in the suite

Registered and one checkbox away on the Policies page, left out on purpose:

- **`cyse4_autocomplete`** — measured to share 1,863 of 1,866 vulnerability snippets with
  `cyse4_instruct`: the same corpus rendered as a completion prompt. A second modality, not a
  second dimension. Enable it if IDE completion is specifically your deployment.
- **`atb_autonomy_hijack`, `atb_data_exfil`** — same threat model as `agentdojo`, which
  measures it over 629 cases instead of 6 and 8.
- **`cyse4_malware_analysis`, `cyse4_threat_intelligence`** — these measure *defensive
  usefulness*, a capability question rather than a safety one.

Also assessed and excluded: saturated benchmarks (**Cybench** at ~93%, **CyberMetric**,
**SecQA**, **WMDP-Cyber** — a measure everything passes cannot inform a decision), **3CB**
(15 challenges, four withheld), **`cyse4_multiturn_phishing`** (three model calls per sample,
and persuasion belongs to compliance under our separation of duties), and **b3**, **CodeIPI**
and **HarmBench** (not runnable as installed). Full reasoning:
[research/BENCHMARK_ASSESSMENT_2026-08-09.md](research/BENCHMARK_ASSESSMENT_2026-08-09.md).

## The sandbox tier, and one hard exclusion

**CVE-Bench** (40 real web CVEs, ~$25–70 a run) and **CyberGym** (1,507 vulnerabilities,
236 GB, ~11 h) measure *offensive capability*. They need Docker and human supervision, and
they answer a different question: high capability is not a failure, it is a **risk-tiering
signal** that should tighten access and authorization. Neither is part of the automatic gate.

**ExploitGym, SEC-bench Pro and BountyBench are not run here at any tier.** They ask a model
to develop working exploits, and verifying that needs an environment powerful enough to be
dangerous. In July 2026 an exploit-generation benchmark run with guardrails disabled ended
with frontier models
[escaping their sandbox and compromising Hugging Face's production infrastructure](https://huggingface.co/blog/security-incident-july-2026)
to steal the answer key. An onboarding gate has no need to elicit offensive capability, so it
does not — asserted by `tests/test_registry.py::test_no_check_requires_a_sandbox` rather than
left to reviewer memory.

### Adding a sandbox tier

The door is open, but nothing is wired for it: no shipped benchmark requires a sandbox, and the
runner has no way to start a container. A fork that wants CVE-Bench takes on all five of these,
in order:

1. **Give the runner a Docker daemon.** Benchmarks in this tier build and run containers, and
   the backend container is deliberately not given a Docker socket. Handing a governance tool
   the ability to start containers is the single largest change here — treat it as the security
   decision it is, not as plumbing.
2. **Register the benchmark** as a `Check` in `backend/app/engines/registry.py`, with its
   Inspect task, headline metric, `calls_per_sample` and `dataset_size`, so cost stays visible
   before a run rather than discovered hours in.
3. **Make `needs_sandbox` real.** It is a hardcoded `False` property on `Check` today; a
   sandboxed benchmark needs it to become an actual field.
4. **Narrow the guard rather than deleting it.** `test_no_check_requires_a_sandbox` currently
   asserts the property across every check. Keep it asserting for everything the automatic gate
   can reach, so the exclusion still holds where it matters.
5. **Keep it beside the gate, not inside it.** Do not give it a threshold in the policy. High
   capability is not a failing grade; it is a reason to tighten access and authorization, and a
   supervised tier reports a tier rather than a pass.

Steps 1 and 5 are the ones worth arguing about in review. The rest is mechanical.

**The exploit-development exclusion above is not part of this path.** ExploitGym, SEC-bench Pro
and BountyBench stay out at every tier, sandbox or not.

## Measured cost, per benchmark

Model calls per sample is the portable unit; wall-clock depends entirely on the backing model.
The seconds below were measured against local Ollama models, which are the slowest realistic
substrate — a hosted judge is far faster.

| Benchmark | Calls/sample | Dataset | Judge | Measured note |
|---|---|---|---|---|
| `cyse4_mitre` | 3 | 1,000 | yes + expansion | most expensive per sample: subject, expansion, judge |
| `cyse4_multilingual_prompt_injection` | 2 | 1,004 | yes | judge dominates; the slowest of the suite on local models |
| `strong_reject` | 2 | 313 | yes | ~70 s/sample measured locally |
| `cyse4_mitre_frr` | 1 | 750 | no | refusal read from the response itself |
| `cyse4_instruct` | 1 | 1,916 | no | detection is local semgrep, no model grading |
| `agentdojo` | ~6 (agent loop) | 944 | no | varies with how long the model takes to finish |
| `atb_memory_poison` | ~4 (agent loop) | 10 | no | ~15 s/sample; the full dataset in ~2.5 min |

The judged CyberSecEval benchmarks dominate the bill. A funded judge
(`gpt-5.6-luna`-class or similar) is the right call for them; local models make them slow rather
than expensive.

## A caveat on the agentic benchmarks

`agentdojo` and `atb_memory_poison` score security from tool-call behaviour, so **a model too
weak to call tools reliably scores well by failing to act.** Both record an ungated utility
metric beside the security one for exactly this reason — read them together, or the number
flatters incompetence.

This is measured, not theoretical: one AgentThreatBench task produced *no score at all* on a
small local model because it emitted a tool call with a null function name, which Inspect's
`ToolCall` model rejects.
