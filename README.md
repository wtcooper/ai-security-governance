# AI Security Governance Toolkit

Self-service security evaluation and governance thresholds for AI assets — foundation models,
MCP servers, and agent skills.

Submit an asset, get a decision: **auto-approve**, or **needs deep testing**. Every result is
measured against a written threshold and records which models and which policy produced it.

## Why

Most organisations have no defined testing bar for onboarding AI assets, so every new model,
MCP server or skill becomes an ad-hoc judgement call. This tool exists to make that call
repeatable: a fixed set of security benchmarks and scanners, a versioned policy file, and a
deterministic gate.

It is the tool you use **after** terms and legal review have established that an asset can't
simply be waved through. Scope is security only — harmful-content and compliance evaluation
belong to different teams, and the separation is deliberate.

Two rules shape the design:

1. **Harvest before compute.** If a benchmark result or a model scan is already published, reuse
   it. Every score records its provenance (`published` / `harvested` / `self_run`) and a source.
2. **The gate is deterministic.** Thresholds, sample counts and severity rules live in a
   versioned policy — one per asset class, stored immutably in the database, edited from the UI.
   No model decides an approval, and every run records exactly which policy version governed it.

## What it evaluates

| Asset | Evaluation | Gate |
|---|---|---|
| **AI model** (open weights or frontier) | 7 security benchmarks via [Inspect AI](https://inspect.aisi.org.uk) across seven risk dimensions — CyberSecEval-4, StrongREJECT, AgentDojo, AgentThreatBench | one threshold per benchmark, on that benchmark's own headline metric |
| **Open weights** | 5 Hugging Face scanners (protectAI, ClamAV, picklescan, VirusTotal, JFrog), harvested not recomputed | any file any scanner calls unsafe blocks; *not scanned* ≠ safe |
| **MCP server** | full [`mcp-scanner`](https://github.com/cisco-ai-defense/mcp-scanner) sweep of cloned source or an uploaded zip | severity rule, advisory by default |
| **Agent skill** | full [`skill-scanner`](https://github.com/cisco-ai-defense/skill-scanner) sweep of cloned source or an uploaded zip | severity rule + the scanner's own verdict, advisory by default |

The model suite is deliberately all pure-API or in-memory simulation — no Docker sandboxes —
so a governance run is repeatable and costs a bounded, visible number of model calls.

## The benchmark catalogue — AI models

**This section is about the AI-model asset class only.** MCP servers and agent skills are
not benchmarked at all: no published benchmark can score an artifact someone submits, so for
those the *scanner is the evaluation* and the gate is a severity rule. See
[What it evaluates](#what-it-evaluates).

The suite is chosen by **risk dimension**, not by reputation. One benchmark per dimension, no
dimension counted twice, and each one has to earn its compute. Seven gates cover seven
dimensions:

| Tier | Benchmark | Dimension it covers | Why it is in the set |
|---|---|---|---|
| **1** | `cyse4_mitre` | Direct misuse | Will it help an attacker who simply asks? The baseline question. |
| **1** | `cyse4_mitre_frr` | Over-refusal | Its mandatory pair — without it a model passes the above by refusing everything, which is useless to a security team. |
| **1** | `strong_reject` | Jailbreak robustness | The only gate where the **attacker is the user**. 37 attack transformations, and a grader that scores refusal, convincingness and specificity separately so empty compliance is not mistaken for a jailbreak. |
| **1** | `cyse4_instruct` | Insecure code | The everyday risk: models write production code. Deterministic semgrep detection, no judge. |
| **2** | `cyse4_multilingual_prompt_injection` | Injection via content | Untrusted text overriding instructions, across languages — a common filter bypass. |
| **2** | `agentdojo` | Injection via tools | Untrusted **tool output** redirecting an agent mid-task, over 629 security cases in realistic environments. |
| **2** | `atb_memory_poison` | Memory poisoning | OWASP ASI06: an injection planted in one task that pays off in a later, unrelated one — the only dimension where attack and effect are separated in time. |

**Tier 1 is the select set: four gates, text-only, no tool-calling required.** It runs on any
model including small open-weight ones, and covers misuse, over-refusal, jailbreak robustness
and insecure code.

**Tier 2 adds the agentic dimensions** and is required for any model you will deploy with
tools. It carries a caveat worth stating plainly: `agentdojo` and `atb_memory_poison` score
security from tool-call behaviour, so **a model too weak to call tools reliably scores well by
failing to act.** Both record an ungated utility metric beside the security one for exactly
this reason — read them together, or the number flatters incompetence. (We measured this: one
AgentThreatBench task produced *no score at all* on a small local model because it emitted a
malformed tool call.)

### How much to measure

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

### Also available, deliberately not in the suite

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
[docs/research/BENCHMARK_ASSESSMENT_2026-08-09.md](docs/research/BENCHMARK_ASSESSMENT_2026-08-09.md).

### The sandbox tier, and one hard exclusion

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

## Quick start

Requires Docker. On macOS, [Colima](https://github.com/abiosoft/colima) works well:

```bash
brew install colima docker docker-compose
colima start --cpus 4 --memory 8 --disk 60 --vm-type vz

cp env.example .env        # optional, see below
docker compose up --build
```

| Service | URL |
|---|---|
| App | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Model gateway | http://localhost:4001/health/readiness |

### No API keys required

The bundled gateway ships mock model routes, so a clean checkout with an empty `.env` boots and
passes preflight with **no API key of any kind**. For real evaluation, point it at local models
(Ollama) or any OpenAI-compatible endpoint.

Local models are the default, so development and the entire test suite cost nothing.

## Bring your own models

Everything speaks **OpenAI-compatible base URL + API key**. There is no assumption of a direct
provider account anywhere in the stack.

```
GATEWAY_BASE_URL=http://gateway:4000/v1
GATEWAY_API_KEY=sk-local
```

Point those at a corporate LiteLLM instance, a local vLLM server, or `api.openai.com` and
nothing else changes. A direct provider key is *supported*, never *assumed*.

One gateway drives all three compute engines. Models are configured in
`gateway/litellm_config.yaml` as aliases; the app only ever sees the alias:

| Alias | Role |
|---|---|
| `gemma4`, `gemma4-e2b` | default subject model (local Ollama) |
| `qwen35` | default judge (local Ollama) |
| `gpt-5.6-luna`, `gemini-3.5-flash-lite` | optional hosted judges for calibration |
| `mock-target-*`, `mock-judge` | zero-key boot proof |

> **Alias rule:** no slashes or colons. Inspect parses model strings as
> `openai-api/<provider>/<model>`, so `gemma4:e2b` is aliased to `gemma4-e2b`.

Two safeguards keep the "no provider assumptions" claim true rather than aspirational:

- The UI offers a **dropdown of gateway aliases**, never a free-text model field.
- **Preflight runs a real completion for the subject and the judge** before any run starts, and
  returns the upstream error body verbatim on failure. Judge routing is the usual breakage:
  `inspect_evals` tasks default their graders to a hardcoded `openai/gpt-4o-mini`, so the eval
  subprocess is launched with every provider credential stripped and those defaults overridden.

## Architecture

```
compose.yaml
  gateway   :4001 → 4000   LiteLLM — the single OpenAI-compatible surface
  backend   :8000          FastAPI + Inspect AI + both Cisco scanners
  frontend  :3000          Next.js App Router
  ollama    :11434         optional, profile: local-models
```

SQLite on a volume, alongside eval logs, scanner reports and per-run clone workspaces. DB access
goes through SQLModel, so moving to Postgres is a connection-string change.

The gateway is a separate image because `litellm[proxy]` requires `boto3>=1.43.1` while
`inspect-ai` requires `aioboto3`, which caps it lower — they cannot share a virtualenv. The plain
`litellm` library coexists fine, so the Cisco scanners live in the backend image alongside
Inspect. `backend/tests/test_engine_coexistence.py` asserts this arrangement.

### Safety of the tool itself

A governance tool that could be compromised by the artifacts it inspects would be worse than no
tool. Submitted code is **never executed**:

- `git clone --depth 1`, hooks disabled, no submodules, no build step — read only.
- Zip uploads stream with a size cap and reject traversal, symlinks and bombs.
- Non-URL submissions must resolve inside an allowlisted directory.
- `mcp-scanner`'s `stdio`/`remote` modes *launch* the server under test, so they are off by
  default.

## Testing

```bash
scripts/e2e.sh              # build, launch, verify every acceptance criterion, tear down
scripts/e2e.sh --keep-up    # leave the stack running
scripts/calibrate.sh        # measure detection against the vendor eval corpora
cd backend && uv run pytest # pure-logic tests
```

Success criteria are written down as checkable gates in [ACCEPTANCE.md](ACCEPTANCE.md) and
executed by `scripts/e2e.sh`. Four rules keep them honest:

1. **End-to-end over unit.** Criteria are satisfied by real HTTP against a running stack, real
   model calls, real subprocesses. Unit tests cover only pure logic where a round trip would
   prove nothing extra.
2. **No mocked model call backs a correctness claim.** The mock routes prove one thing: the stack
   boots with zero keys.
3. **Local models only.** A full run costs **$0**.
4. **Judged paths are actually judged**, so judge misrouting can't hide behind a passing subject.

`scripts/calibrate.sh` runs the whole pipeline over the labelled corpora the Cisco repos ship
(141 malicious MCP servers across 14 threat categories; 17 malicious and 4 safe skills) and
reports recall, plus a false-positive rate with its denominator attached.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GATEWAY_BASE_URL` | `http://gateway:4000/v1` | OpenAI-compatible endpoint |
| `GATEWAY_API_KEY` | `sk-local` | bearer token for the above |
| `DEFAULT_SUBJECT_MODEL` | `gemma4` | pre-selected model in the UI |
| `DEFAULT_JUDGE_MODEL` | `qwen35` | grader for judged benchmarks |
| `SCANNER_MODEL` | `gemma4` | LLM analyzer for the Cisco scanners |
| `OPENAI_API_KEY`, `GEMINI_API_KEY` | — | consumed by the gateway only |

Governance policies are **versioned documents in the database**, one per asset class, edited
from the Policies page (or `POST /api/policies/{class}/versions`). Every edit creates a new
immutable version; the newest version governs new runs, and each run records the version and
content hash that governed it — so editing a threshold never silently rewrites the meaning of a
past decision. The YAML files under `backend/policy/` only seed an empty database.

Each LLM gate also sets how many samples run — either `samples: N` (the dataset's first N) or a
pinned `sample_ids:` **core set**: a stratified, seeded selection proposed from a benchmark's
page and adopted as a policy edit, so every run measures exactly the same test cases.

Policies are edited entirely through **forms** — thresholds, sample counts, which benchmarks
are in the suite, the judge, and the scanner severity rules. There is no YAML surface in the
UI: the document stays the stored, hashed, versioned artifact, but nobody has to hand-indent
it to change a threshold. Ticking a benchmark in or out of the suite is a checkbox; its metric
and direction come from the benchmark registry and are never editable, because they are facts
about the benchmark rather than preferences. **Only benchmarks in the suite run** — one
registered but not enabled is available to add and never silently consumes compute.

### Graduating MCP/skills out of advisory mode

```bash
curl -s localhost:8000/api/stats/severity   # findings by analyzer and severity, all runs
```

When the distribution shows `block_on` is discriminating rather than firing on everything, change
`mode: advisory` to `mode: gating` for that asset class. That single line is the whole change.

Note that `mcp-scanner` has no CRITICAL severity — HIGH is the top of its scale and is what
blocks there. `skill-scanner` does emit CRITICAL.

## Security testing of this tool

A tool that evaluates the security of other people's code should be able to show its own
results. Everything below was run against this repository.

### Code review

Two passes were run. A focused review first, then a multi-agent scan at high effort with an
adversarial verification panel — which found that one of the first pass's *fixes* was itself
broken.

#### Second pass: multi-agent scan

**Eight findings survived verification: four HIGH, three MEDIUM, one LOW.** The ones worth
knowing about:

- **`--recurse-submodules=no` did the opposite of its intent** (HIGH). git documents the flag as
  `--[no-]recurse-submodules[=<pathspec>]`, so the `=` form takes a *pathspec* — passing `=no`
  **enabled** submodule cloning and matched submodules at path `no`. A submitted repo could then
  have an arbitrary URL fetched from `.gitmodules`, bypassing the four-forge allowlist entirely.
  The regression test that should have caught this asserted the flag *string* appeared in the
  source, which is exactly why it passed while the flag misbehaved. It now asserts the quoted
  argv token and that the pathspec form is absent.

- **Scanner output parsing could be manipulated by the submission** (HIGH). Both `_extract_json`
  implementations counted braces without honouring JSON string quoting, and both scanners echo
  submission-controlled text into their reports — a filename for the MCP path, a source line for
  the skill path. A `}` inside that text ended the object early, so a submission could reduce or
  void its own findings while the run recorded as a clean success. Replaced with `raw_decode`,
  which is string-aware.

- **pip-audit could be pointed at a project rather than a requirements file** (contested). A
  submission can contain a *directory* named `requirements.txt`, or a `pyproject.toml`, either of
  which selects pip-audit's project mode — resolving and installing declared dependencies, i.e.
  running a build backend on attacker input. Two verifiers rated it exploitable, one refuted it on
  an argparse detail. The missing type check was certain either way, so the input is now narrowed
  to regular `requirements.txt` files only. Writing the test for this exposed that the first fix
  was incomplete: skipping the directory still left a real `pyproject.toml` *inside* it reachable.

- **The gateway image baked a default bearer token** while compose published every service on all
  interfaces. The default is gone and all published ports are now bound to `127.0.0.1`, which is
  where a single-user local tool with no authentication belongs.

On the two fixes the scan was explicitly asked to attack rather than accept: **the SSRF pinning
held and the symlink containment held**, three verifiers each. But the SSRF rewrite had *narrowed*
its own predicate — moving to `is_global` silently dropped the `is_multicast` and `is_reserved`
checks the previous version had, and admitted NAT64. No route existed (the compose network is
IPv4-only, and the https-only rule blocks the plain-HTTP internal services), but a fix should not
quietly reduce coverage, so those predicates are restored and NAT64 prefixes are now denied
explicitly.

#### First pass: focused review

Found **two MEDIUM issues, both real, both since fixed** with regression tests. Both were containment failures rather than crashes, which is the
class that matters here: this tool deliberately clones untrusted repositories and unzips
untrusted archives, so the property under test is that a submission cannot reach beyond itself.

**1. Symlink escape from a cloned repository.** `git clone` checked out symlinks, and the scan
path then followed them: the file walk used `is_file()` (which follows a link) with the suffix
taken from the *link* name, and the bounded-scan staging step used `shutil.copy2`, which
dereferences by default. That last step copied the target's bytes into a fresh scan root as an
ordinary file — laundering external content past `mcp-scanner`'s own symlink guard, which only
rejects things still shaped like symlinks. Reproduced with a submission of 41 filler files plus
`0leak.py -> outside.env`; the linked file's contents landed in the run workspace. Fixed with
`-c core.symlinks=false` on clone, symlink and resolve-inside-root checks in the walk, and
`follow_symlinks=False` when staging. The zip path already refused symlink members; the clone
path is now consistent with it.

**2. SSRF guard weaknesses.** Two separate problems. The guard resolved the hostname and checked
every address, then handed the URL *string* to the HTTP client, which resolved again — two
lookups, so a name whose records changed in between was fetched having never been validated. And
the address filter (`is_private`, `is_loopback`, `is_link_local`, …) is not equivalent to
"globally routable": `100.64.0.1` in carrier-grade NAT space passed. Fixed by connecting to the
validated literal address with `Host` and SNI preserved, and by checking `is_global` plus an
explicit deny for `192.88.99.0/24` and `2002::/16` — the 6to4 relay prefixes, which report
`is_global == True`.

One further item was fixed as hardening rather than a finding: the scanner subprocesses received
the whole environment while eval subprocesses were scrubbed. No egress path existed (the backend
container is never given provider keys), but the asymmetry is how a leak appears after a config
change.

### Checked and cleared

Recorded because what was examined and found safe is as informative as what was flagged:

- **Zip-slip and zip symlink members** — absolute paths and any `..` component rejected before
  extraction; symlink members refused outright.
- **Submission-path allowlist** — `realpath` applied before a component-wise ancestor test, so
  `…/uploads-evil` and `…/uploads/../../etc/passwd` both fail, as do case-variant paths.
- **Upload filename handling** — the write path comes from a server-side counter; the client
  filename is used only for the extension check.
- **Command and argument injection** — all five subprocess call sites use argument lists, never a
  shell. Submission-derived paths are absolute and server-rooted, and model aliases are wrapped
  into `openai-api/gateway/<alias>`, so neither can be parsed as a flag.
- **SSRF via IP encodings** — decimal, octal, short-form and IPv4-mapped IPv6 forms are
  normalised by resolution before the check and blocked. NAT64 prefixes are denied explicitly
  rather than by normalisation, which an earlier version of this list described incorrectly.
- **Redirect handling** — redirects are followed manually with each hop re-validated, so an
  allowed host cannot bounce the fetch to a forbidden one.
- **`hf_repo_id` interpolation** — reaches only the path of a URL whose scheme and host are
  fixed literals; no payload moves the request off the host.
- **Credentials in responses** — no path was found by which a provider key reaches a response
  body, a log line, or an artifact.
- **Gate-logic bypass** — the gate reads only gated scores, compares raw values against raw
  thresholds, treats a missing score or unreliable judge or failed scan as blocking, and never
  reads the composite.
- **Executing submitted code** — the dependency audit runs with `--no-deps --disable-pip` on a
  requirements *file*, so no build backend runs; clones use `--recurse-submodules=no` and
  `core.hooksPath=/dev/null`. Nothing from a submission executes.
- **Frontend XSS** — no `dangerouslySetInnerHTML`, `innerHTML`, `srcdoc`, `eval` or
  `new Function` anywhere; scanner findings render as React text children.

### Detection calibration

`scripts/calibrate.sh` runs the pipeline over the labelled corpora the Cisco scanner repos ship
and scores it against their ground truth. Analyzer model `gemma4` running locally, policy v1,
**$0 spend**:

| Corpus | Malicious | Detected | Recall | Benign | Flagged | FP rate |
|---|---|---|---|---|---|---|
| MCP servers | 14 | 12 | **86%** | 2 | 1 | **50%** ⚠️ |
| Agent skills | 17 | 15 | **88%** | 4 | 0 | **0%** |

Missed: `injection-attacks`, `template-injection` (MCP); `sql-injection`,
`test_skills-malicious` (skills). All four produced zero findings rather than findings we
mis-scored. The EICAR miss is explainable — it is an antivirus test file, and the VirusTotal
analyzer is off by default.

**The most useful result is the worst one.** A legitimate benign MCP server
(`evals/remote/benign/GitHub_tools`) was flagged HIGH — 1 of the 2 benign MCP servers that
produced a result. That is direct evidence the MCP severity rule is not yet safe to auto-approve
against, and it is why MCP stays in `advisory` mode. The skill rule looks better: all four safe
skills produced zero findings.

A third benign MCP server (`azure_tools`) **timed out at 900s**, which is the scan-time
limitation below, measured rather than asserted.

The skill corpus was run twice, independently, and produced **identical per-case outcomes** —
same 15 detections, same 2 misses. Worth checking rather than assuming, because the LLM analyzer
is a model and the judge-refusal rate elsewhere in this project does vary run to run. Both
reports are committed under `data/calibration/`.

### What this does not establish

- **The scan did not finish cleanly.** A session limit killed 12 of 34 researchers mid-run; only
  the two areas named above were re-run. `backend/app/scoring/`, `gateway/` and the deploy
  configuration were never audited, and **no secrets sweep ran** — nothing here verifies that no
  credential is committed anywhere. Sixteen further candidate sites fell below the verification
  cap and are recorded as open questions rather than findings.
- Conclusively cleared, for what it is worth: the startup DDL in `db.py` (all interpolants are
  compile-time constants from `models.py`), and frontend XSS (every submission-derived string
  lands as an escaped JSX text child, no raw-HTML sink anywhere).
- Recall is measured on one sample per MCP threat category, not all 141 servers.
- The false-positive denominators are 2 and 4. Enough to show the skill rule discriminates and
  that the MCP rule does not yet; nowhere near enough to justify auto-approval.
- The corpora are the scanner vendor's own, so they are likely favourable to their detections.
- No third-party penetration test.

## Known limitations

Worth reading before trusting a result:

- **Thresholds are not calibrated.** They are structurally correct placeholders. Calibrating them
  needs runs against models whose behaviour you actually care about; local models can't stand in.
  It is a policy edit (a new version from the Policies page), not a code change.
- **`atb_memory_poison` is coarse by construction.** Its dataset holds only 10 cases, so one
  case moves the score 10 points and the gate tolerates exactly one failure. That is the whole
  dataset rather than a sample of it — there is no deeper run available. A test now asserts
  every gate tolerates at least one failure, which is what caught two sibling gates being
  arithmetically zero-tolerance (0.90 over n=6 and n=8) before they were retired.
- **MCP and skills run in advisory mode.** They can withhold approval but never grant it, because
  the false-positive baseline is thin — 3 benign MCP servers and 4 safe skills in the vendor
  corpora. Adding benign servers is the prerequisite for `mode: gating`.
- **Scan time scales with file count.** A single-server submission takes ~40 seconds including the
  dependency audit. Monorepos are slow because the behavioral analyzer invokes a model per source
  file, so they are capped at 40 files with the shortfall reported *as a finding*. Submit one
  server, not a monorepo. Calibration showed this is not hypothetical: one benign server in the
  vendor corpus hit the 900s timeout and produced no result at all.
- **Tools are not enumerated live.** Getting a server's real tool list means launching it, which
  is executing untrusted code. Detection is therefore source-based and cannot see tools generated
  at runtime.
- **Dependency audit covers pinned packages only**, because pip-audit's resolution venv fails on
  some hosts. When it fails the scanner reports "SAFE (0 findings)", so that failure is detected
  and recorded as a finding rather than trusted.
- **No local weight-scanner fallback.** Open-weight results are harvested from Hugging Face only;
  a gated or unscanned repo is reported as unassessed.
- **Additive schema changes only.** SQLite columns are reconciled on startup; renames and drops
  would need a real migration.

## Roadmap

Ideas, roughly in order of value:

- **Calibrate the thresholds** against a funded run of models the org actually uses, and graduate
  MCP/skills out of advisory mode once a benign corpus exists.
- **Benign MCP corpus** — scan and review a set of well-known public servers to establish the
  false-positive baseline the severity rule is missing.
- **Local weight scanning** with [`modelaudit`](https://www.promptfoo.dev/docs/model-audit/) for
  repos Hugging Face hasn't scanned, or that are gated or private.
- **A supervised sandbox tier for capability**, most likely **CVE-Bench** alone: 40 real CVEs at
  roughly $25–70 a run is affordable, where CyberGym's 236 GB and ~11 hours is not. It answers
  the one dimension the gate cannot, and its result should tier risk rather than pass or fail.
- **Antares as an extra source analyzer.** Cisco's open-weight vulnerability-localisation models
  are cheap and run locally; note their model card rules them out as a general judge.
- **Re-run a stored decision under a new policy version** from the UI, so a threshold change
  can be reviewed against history before it is adopted.
- **One-click core-set adoption** — currently propose-then-paste into the policy editor, kept
  manual so selection changes are always deliberate; could become a guided flow.
- **Postgres + Alembic** for multi-user deployments.
- **CI workflow** running the pure-logic suite on every push.
- **Export a decision record** (PDF or signed JSON) for attaching to a ticket.

## Contributing

Issues and pull requests welcome. Please run `cd backend && uv run pytest` and
`cd frontend && npm run build` before opening a PR. If you touch scoring or gating, add a test —
those invariants are the point of the project.

## License

MIT — see [LICENSE](LICENSE).
