# Acceptance criteria

Explicit, checkable success criteria for each part of the build. A phase is **done** only
when every criterion below it passes via `scripts/e2e.sh` against a stack launched with
`docker compose up --build`.

## Testing rules

1. **End-to-end over unit.** The criteria below are satisfied by real requests to a running
   stack — real HTTP, real model calls, real subprocesses. Unit tests exist only for pure
   logic (score normalization, gate arithmetic, path traversal rejection) where a real
   round trip would prove nothing extra.
2. **No mocked model calls in an acceptance gate.** Mock model *routes* exist in the gateway
   and are used for exactly one thing: proving the stack boots with zero API keys. No
   correctness claim rests on them.
3. **Local models only.** Every gate runs against host Ollama (`gemma4`, `gemma4-e2b`,
   `qwen35`) through the gateway. Hosted models (`gpt-5.6-luna`,
   `gemini-3.5-flash-lite`) are reserved for Phase 5 threshold calibration and are never
   touched by the test suite. Running the full suite must cost $0.
4. **Judged paths must actually be judged.** Any criterion involving a grader routes the
   judge through the gateway too, so judge misrouting cannot hide behind a passing subject.

Run everything:

```bash
scripts/e2e.sh              # builds, launches, verifies, reports
scripts/e2e.sh --keep-up    # leave the stack running afterwards
```

---

## Phase 0 — Infrastructure and model routing ✅

| # | Criterion | How it is verified |
|---|---|---|
| 0.1 | All four compute engines import in one process at safe versions | `pytest tests/test_engine_coexistence.py` — asserts `inspect_ai`, `inspect_evals`, `mcpscanner`, `skill_scanner` co-import, litellm ≥1.83.0 and not 1.82.7/1.82.8, and that `litellm[proxy]` has not leaked in (boto3 <1.43.1) |
| 0.2 | `docker compose up --build` reaches a healthy stack from a clean volume | `docker compose down -v` then `up --build`; gateway healthcheck passes, backend and frontend respond |
| 0.3 | Stack boots and passes preflight with **zero API keys** | `POST /api/preflight` with `mock-target-compliant` + `mock-judge` returns `ok: true` |
| 0.4 | Backend reaches the gateway over compose service DNS | `GET /api/gateway/status` → `ok: true`, `base_url: http://gateway:4000/v1` |
| 0.5 | Model discovery returns gateway aliases for the UI dropdown | `GET /api/models` contains `gemma4`, `qwen35`, and no provider-native model strings |
| 0.6 | **A real local model answers through the gateway** | `POST /api/preflight` with `gemma4` → `ok: true` with a non-empty completion |
| 0.7 | **Inspect AI runs a real eval through the gateway to a local model** | `POST /api/selftest/inspect` → `gateway_selftest` status `success`, `includes.accuracy` present |
| 0.8 | **Inspect AI routes a real judge through the same gateway** | same call → `gateway_judge_selftest` status `success`, `model_graded_qa.accuracy` present, judge token usage non-zero |
| 0.9 | Provider credentials cannot reach an eval | `pytest tests/test_env_scrubbing.py` — `build_child_env` strips `OPENAI_API_KEY` etc. and sets only `GATEWAY_*` |
| 0.10 | Preflight failure returns the upstream error body verbatim | `POST /api/preflight` with an unroutable alias → `ok: false` and a populated `upstream_error` |
| 0.11 | Frontend renders live gateway state | `GET :3000` returns 200 containing the three asset-class cards and `reachable` |
| 0.12 | A fresh clone builds (no untracked files required) | `git checkout-index` into a temp dir, then `docker build ./backend` |

## Phase 1 — LLM path

| # | Criterion | How it is verified |
|---|---|---|
| 1.1 | Every registered check declares a judge task-arg; registration fails otherwise | unit test over the check registry |
| 1.2 | Each of the 5 benchmarks runs to `success` against `gemma4` at a small `--limit`, judge on `qwen35` | real eval per check through `/api/runs` |
| 1.3 | Metric keys in `registry.py` match what the scorers actually emit | asserted against the live eval output, not documentation |
| 1.4 | One gate per benchmark; no sub-dimension is ever thresholded | unit test: `gated=false` scores are excluded from gate evaluation |
| 1.5 | Composite score is displayed but never gates | unit test: changing composite alone cannot change the decision |
| 1.6 | A missing required check yields `NEEDS_DEEP_TESTING`, never `AUTO_APPROVE` | unit test on `gates.py` |
| 1.7 | Judge refusals are counted as unresolved, never as passes | fixture of refusal responses through the real scorer path |
| 1.8 | `judge_refusal_rate` over policy limit ⇒ run `ERROR / judge unreliable`, no decision emitted | real run with a deliberately refusing judge |
| 1.9 | Run detail page shows subject model, judge model, refusal rate, and per-score provenance | HTTP fetch of the rendered page |

## Phase 2 — Open-weight supply-chain scan

| # | Criterion | How it is verified |
|---|---|---|
| 2.1 | All five Hugging Face scanners are parsed per file | live call for a safetensors model and an older `pytorch_model.bin` model |
| 2.2 | `scansDone: false` is surfaced as "not scanned", never as "safe" | live call against a repo with incomplete scans |
| 2.3 | Any file with `status: unsafe` blocks | unit test on the gate |
| 2.4 | Raw scan JSON is stored as a run artifact | assert the artifact row and file exist |

## Phase 3 — MCP server path

| # | Criterion | How it is verified |
|---|---|---|
| 3.1 | A public MCP repo clones and scans end to end with the scanner LLM on the gateway | real run |
| 3.2 | The full analyzer set runs; findings retain `analyzer`, `severity`, `rule_id`, `file_path` | assert distinct analyzers present in findings |
| 3.3 | A deliberately poisoned tool description produces CRITICAL/HIGH findings | real run against a crafted fixture |
| 3.4 | Advisory mode never returns `AUTO_APPROVE`, even on a clean scan | real run against a benign repo |
| 3.5 | `engine_version` and `ruleset_version` are recorded on every run | assert both are non-null |
| 3.6 | Untrusted code is never executed: no `stdio`/`remote` launch unless explicitly opted in | unit test that the default path uses static/behavioral only |
| 3.7 | Zip upload rejects path traversal and oversize archives | unit test with a zip-slip archive |

## Phase 4 — Agent skill path

| # | Criterion | How it is verified |
|---|---|---|
| 4.1 | A public skill repo scans end to end with the scanner LLM on the gateway | real run |
| 4.2 | SARIF ingests; severity counts agree with the raw SARIF artifact | cross-check parsed rows against the stored file |
| 4.3 | The scanner's own `is_safe` verdict is honoured rather than re-derived | real run assertion |
| 4.4 | Advisory mode never returns `AUTO_APPROVE` | real run against a benign skill |

## Phase 6 — Detection calibration against the vendor corpora

Run with `scripts/calibrate.sh`. Measures **our whole path** (invocation → parsing → severity
mapping → policy gate) against the labelled corpora the Cisco repos ship. We are not grading
the scanners: a finding a scanner emits and we fail to parse is a miss for governance purposes.

| # | Criterion | How it is verified |
|---|---|---|
| 6.1 | Corpora clone and case discovery finds the expected counts | 144 MCP cases (141 malicious + 3 benign), 21 skill cases (17 malicious + 4 benign) |
| 6.2 | Labels come from the corpus, never inferred | `_expected.json` `expected_safe` plus the safe/malicious directory split |
| 6.3 | Recall reported per corpus with missed categories named | report `summary()` lists `per_category_misses` |
| 6.4 | FP rate reported **with its denominator** and flagged when thin | `fp_denominator_warning` set below 20 benign cases |
| 6.5 | `advisory_mode` excluded from blocking reasons | unit test — otherwise recall would measure the mode, not detection |
| 6.6 | Sampling is recorded, never silent | `sampling.cases_run` and a note that sampled recall is an estimate |

**Known limit:** FP denominators are 3 benign MCP servers and 4 safe skills. Enough to catch a
rule that fires on everything; not enough to justify auto-approval. MCP still needs benign
servers added before `gating`.

## Phase 7 — Frontend visual design

| # | Criterion | How it is verified |
|---|---|---|
| 7.1 | Light theme throughout, no dark-on-dark, no `prefers-color-scheme` reliance | rendered page inspection |
| 7.2 | Icons from `lucide-react`; no bespoke SVG paths in components | grep for `<path` / `<svg` in `app/**` |
| 7.3 | One consistent icon per asset class, decision state, and severity | shared maps, asserted by inspection |
| 7.4 | Decision, gate table and severity stay the highest-contrast elements | rendered page inspection |
| 7.5 | Colour is never the sole carrier of meaning — text labels accompany icons | rendered page inspection |
| 7.6 | `npm run build` clean and criteria 0.11 / 1.9 still pass | e2e suite |

## Phase 5 — Calibration and docs

| # | Criterion | How it is verified |
|---|---|---|
| 5.1 | 2–3 known-approved models land `AUTO_APPROVE` under shipped thresholds | calibration run (the one place hosted models are allowed) |
| 5.2 | Threshold changes require editing `policy.yaml` only, never code | change a threshold, re-decide a stored run, observe the flip |
| 5.3 | `policy_hash` is recorded per run so historical decisions stay interpretable | assert hash changes when policy changes |
| 5.4 | `GET /api/stats/severity` reports the distribution used to hand-tune `block_on` | live call |
| 5.5 | README documents Colima, compose, gateway config, Postgres swap, advisory→gating | review |
