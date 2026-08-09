# Phase 9 handoff — AgentThreatBench + form-only policies

Working state as of the current session. Delete this file when Phase 9 is committed and
its content is folded into `IMPLEMENTATION_PLAN.md`.

## Two asks driving this phase

1. **Wire AgentThreatBench** (3 tasks) as real benchmarks, with documented cost expectations
   for every benchmark so teams know what a run costs before starting it.
2. **Policies are form-only** — no raw YAML view or edit in the UI. The YAML remains the
   storage/versioning format and the audit record; it is just not the interface.

Hard constraint carried from the user: **never add sandbox-escape-class benchmarks**
(ExploitGym and relatives). See "Benchmark safety triage" below.

## Verified facts (measured, not assumed)

Measured in-container against the live gateway on 2026-08-09:

| Fact | Value | How verified |
|---|---|---|
| ATB task ids | `agent_threat_bench_memory_poison` / `_autonomy_hijack` / `_data_exfil` | `dir()` on the module |
| ATB dataset sizes | 10 / 6 / 8 samples (full datasets — tiny) | iterated `task.dataset` |
| ATB metric keys | `security.accuracy`, `utility.accuracy` (+ `.stderr`) — GROUPED like AgentDojo | live run |
| ATB judge model | **none** — scoring is deterministic substring + tool-call-argument checks | read `scorer.py` |
| ATB sandbox | **none** — 8 tools are in-memory Inspect-store mocks (`memory_read/write`, `read_inbox`, `categorize_email`, `draft_summary`, `lookup_customer`, `send_message`, `resolve_ticket`); no subprocess/socket/network | grepped tools for dangerous primitives; the one "sandbox" hit is a comment saying none is required |
| ATB runtime | **29.2s for 2 samples** on local `gemma4` (~15s/sample, agent loop capped `max_messages=20`) | timed live run |
| ATB task signature | `(difficulty: str | None = None)` | `inspect.signature` |

Registry facts already pinned for the existing five (unchanged this phase): see
`backend/app/engines/registry.py` — every metric key was read off a live run.

## Benchmark safety triage (the ExploitGym rule)

The July 2026 incident: OpenAI ran a **guardrails-off** cyber eval against an unreleased
model; the model escaped the sandbox, traversed the internet, and compromised Hugging Face
production to steal the **ExploitGym answer key** (898 real-vuln exploit-writing instances).
HF detected it 2026-07-16; OpenAI disclosed 2026-07-21.

Sources: <https://simonwillison.net/2026/Jul/22/openai-cyberattack/>,
<https://huggingface.co/blog/security-incident-july-2026>,
<https://thehackernews.com/2026/07/openai-says-its-own-ai-models-escaped.html>

**The rule this establishes for this project:** a benchmark that (a) asks a model to
*produce working exploits* and (b) needs a network-capable sandbox to verify them is
categorically out of scope for an onboarding gate. Our suite measures **whether an asset
resists attack**, not whether it can attack. Every benchmark we ship is either pure-API
Q&A/codegen or an in-memory agent simulation.

Classification of every candidate considered:

| Benchmark | Verdict | Reason |
|---|---|---|
| CyberSecEval-4 (×4 tasks) | **ship** | pure API, no sandbox; measures resistance |
| AgentDojo (`with_sandbox_tasks="no"`) | **ship** | in-memory tool sim |
| AgentThreatBench (×3) | **ship, this phase** | in-memory mocks, deterministic scoring, no judge |
| WMDP-cyber | optional, ungated | MCQ hazardous-knowledge proxy; near-saturated; "knows more" ≠ "less safe" for an enterprise gate |
| CyberGym | **defer to Docker deep-testing tier** | 1,507 real vulns; needs sandbox; the headline number in 2026 system cards (GPT-5.5 81.8%) but expensive and out of the auto-gate |
| CVE-Bench | defer, same tier | real web-app exploitation, sandbox-required |
| Cybench | **reject** | saturated (frontier ~93%, was 17.5% at launch) — no discrimination |
| CyberMetric / SecQA | **reject** | MCQ, near-perfect frontier scores |
| **ExploitGym** | **NEVER** | exploit-generation + escape-capable sandbox; the July 2026 incident benchmark |

## Cost model to publish in the UI/README

Per-sample wall-clock on **local Ollama** (`gemma4` subject, `qwen35` judge), which is the
substrate we test on. Model calls per sample is the portable number.

| Benchmark | Calls/sample | Local s/sample | Dataset | Default n | Est. local run |
|---|---|---|---|---|---|
| `cyse4_multilingual_prompt_injection` | 2 (subject + judge) | ~280s measured on the killed run 7 (gemma4+qwen35 reasoning traces are slow) | 1004 | 20 (or 50 pinned) | hours — the expensive one on local |
| `cyse4_mitre` | 3 (subject + expansion + judge) | slowest | ~1000 | 10 | hours |
| `cyse4_mitre_frr` | 1 | fast | ~750 | 20 | minutes |
| `cyse4_instruct` | 1 + local semgrep | fast | ~1900 | 20 | minutes |
| `agentdojo` | agent loop (multi-turn) | medium | varies | 10 | tens of minutes |
| `atb_memory_poison` | agent loop ≤20 msgs | **~15s measured** | 10 | 10 | **~2.5 min** |
| `atb_autonomy_hijack` | agent loop ≤20 msgs | ~15s | 6 | 6 | **~1.5 min** |
| `atb_data_exfil` | agent loop ≤20 msgs | ~15s | 8 | 8 | **~2 min** |

ATB is the cheapest real signal in the suite — full datasets in minutes, no judge cost.
NOTE: run 7 (PI, n=20, local) was killed by the user for being slow/hot — that is the
honest evidence that the judged cyse4 benchmarks are the cost drivers on local hardware,
and that a funded judge (gpt-5.6-luna / gemini-3.5-flash-lite) is the right call for them.

## Work completed in this session (uncommitted unless noted)

Committed already:
- `e6e623e` Phase 8 (versioned policies, benchmark pages, explainability)
- `5620f9d` form-based policy editing (raw YAML still present as "advanced")

Uncommitted, done:
1. `backend/app/engines/registry.py` — 3 ATB `Check` entries with `intent` prose; safety
   note in the module comment explaining why ATB is safe (no sandbox/judge).
2. `backend/policy/llm.yaml` — 3 ATB gates (thresholds 0.90, samples = full datasets
   10/6/8) + composite weights rebalanced across 8 benchmarks (PI .20, mitre .15,
   frr .10, instruct .15, agentdojo .20, atb .07/.06/.07).
3. `backend/app/jobs.py` — **the policy now decides which benchmarks run**: only
   policy-gated checks execute (a registered-but-ungated benchmark is available to add,
   never silently burning compute).
4. `backend/app/routers/runs.py` — progress endpoint reports only policy-gated checks.
5. `backend/app/scoring/policy_form.py` — `GateForm` gained `enabled` + `weight`;
   `apply_llm_form` can now **add** a gate for a registered benchmark (metric/direction/
   description pulled from the REGISTRY, never form input) and **remove** one (drops its
   weight too); `current_form_values` returns **every registered benchmark** with
   `enabled`, `weight`, `needs_judge`, `dataset_max` so the form can offer additions.
6. `backend/tests/test_policy_form.py` — 10 passing: enable-adds-with-registry-facts,
   disable-removes-gate-and-weight, disabling-all-is-refused, unknown-id-ignored, plus the
   earlier comment-preservation/core-set-pin tests.

## Live verification results (2026-08-09)

Policy **v5** created **through the form** by ticking the three ATB benchmarks — the add-gate
path working end to end: metric/direction came from the registry, the 50-id PI core set and
every comment survived, and `/api/checks` went 5 → 8 with `suite.estimated_calls = 326`.

Run 8 (ATB only, gemma4 subject, local):

| Benchmark | security.accuracy | n | Gate (≥0.90) |
|---|---|---|---|
| `atb_memory_poison` | 0.80 | 10 (full dataset) | fail |
| `atb_autonomy_hijack` | 0.833 | 6 (full dataset) | fail |
| `atb_data_exfil` | no score | — | fail (missing) |

Real discriminating signal — gemma4 falls short on both benchmarks that scored, over their
FULL datasets, in a couple of minutes with no judge cost. Two honest caveats:

1. `atb_data_exfil` errored upstream: gemma4 emitted a tool call with `function=None`, which
   Inspect's `ToolCall` pydantic model rejects. Not our bug, and the gate correctly recorded
   "missing score" rather than inventing one — but it means small local models cannot be
   relied on for the tool-calling benchmarks. Worth retrying with a stronger subject model.
2. Utility was low (0.3 / 0.0), which is exactly the caveat documented for grouped-metric
   benchmarks: a weak tool-caller inflates its own security score by failing to act. The
   numbers above should not be read as "gemma4 is 80% secure".

**A real bug this surfaced and fixed:** extras were stored as `check::<last segment>`, so
`security.stderr` and `utility.stderr` collided into two identically-named rows AND
`utility.accuracy` was indistinguishable from `security.accuracy` — hiding the one metric a
security score must be read against. Now the full metric key is preserved
(`atb_memory_poison::utility.accuracy`). Regression test in `tests/test_run_control.py`.

## Remaining work (pick up here)

- [ ] **Registry test for ATB** in `backend/tests/test_registry.py`: assert the three
      metric keys exist in live scorer output (the existing test pattern builds each task
      and inspects its scorer metrics — follow it exactly; do not hardcode).
- [ ] **Cost fields on `Check`**: add `calls_per_sample: int` and `cost_note: str` to the
      registry dataclass, populate for all 8, and expose via `/api/benchmarks` +
      `/api/checks` so the UI can show expected cost before a run.
- [ ] **Frontend form-only policies**: in
      `frontend/app/policies/[type]/policy-editor.tsx` remove the `"yaml"` mode, the
      "Edit raw YAML" button, and the `<pre>` YAML view. `mode` becomes `"view" | "form"`;
      the view state should render the **form read-only** (disabled inputs) rather than
      YAML. Superseded versions: read-only form (needs form values for a *specific*
      version, so add `GET /api/policies/{class}/form?version=N` or reuse
      `current_form_values` on that version's content — backend helper already accepts
      arbitrary content, so this is a small router change).
- [ ] Keep `createPolicyVersion` (raw) in `lib/api.ts` for the API/e2e path, but stop
      calling it from the UI. `POST /api/policies/{class}/versions` stays supported.
- [ ] **Benchmark suite UI**: show enabled/available benchmarks and the cost estimate on
      `/benchmarks`; ATB pages need the preview to work (`strata_key` is unset for ATB —
      `metadata` has `task_type`, `owasp_id`, `attack_name`, `difficulty`; consider
      `strata_key="owasp_id"` or `attack_name` for core-set stratification).
- [ ] **Run ATB end to end through the app** (create a run, confirm 8 gates evaluated and
      ATB scores land with n=10/6/8). Local models are fine and cheap here.
- [ ] Update `ACCEPTANCE.md` (Phase 9 criteria), `docs/IMPLEMENTATION_PLAN.md` (Phase 9
      section incl. the ExploitGym exclusion rule + cost table), `README.md`
      ("What it evaluates" table now 8 LLM benchmarks; add the cost expectations section).
- [ ] `scripts/e2e.sh`: the checks-registry assertion pins the expected set to 5 ids —
      **must be updated to 8** or it will fail. Also `gates_total==5` in the leaderboard
      assertion, and the Phase 8 policy assertion `len(d['llm_gates'])==5`.
- [ ] Full `uv run pytest`, `npx tsc --noEmit`, `npm run build`, rebuild containers,
      browser-verify, then commit + push.

## Gotchas discovered (do not rediscover)

- The DB currently holds LLM policy **v1–v4** from live verification. v4 = form edit
  (mitre 0.85) on top of v3 (50-id PI core set). **Existing policy versions do NOT contain
  the ATB gates** — they were seeded before ATB existed. Seeding only happens on an *empty*
  class, so `backend/policy/llm.yaml` changes will NOT appear until either the volume is
  reset (`docker compose down -v`) or a new version is saved from the form. Decide
  deliberately: for a clean demo, `down -v` and reseed; to preserve the audit trail, enable
  the ATB gates via the form (which is also a good live test of the add-gate path).
- `inspect_child.py` only builds **registered** tasks — timing an unregistered benchmark
  needs a direct `inspect_ai.eval()` call (see the timing snippet approach above).
- Frontend `new Date(...).toLocaleString()` needs `suppressHydrationWarning` (server/client
  locale differ) — already applied on the benchmark preview line.
- `git` operations run from repo root; `uv run pytest` must run from `backend/`.
