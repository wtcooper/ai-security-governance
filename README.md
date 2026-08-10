# AI Security Governance Toolkit

Self-service security evaluation and governance thresholds for AI assets — foundation models,
MCP servers, and agent skills.

Submit an asset, get a decision: **pass**, or **requires review**. Every result is
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
| **MCP server** | full [`mcp-scanner`](https://github.com/cisco-ai-defense/mcp-scanner) sweep of cloned source or an uploaded zip | severity rule: a finding at a blocking severity requires review |
| **Agent skill** | full [`skill-scanner`](https://github.com/cisco-ai-defense/skill-scanner) sweep of cloned source or an uploaded zip | severity rule plus the scanner's own verdict |

The model suite **as shipped** is all pure-API or in-memory simulation — no Docker sandboxes —
so a governance run is repeatable and costs a bounded, visible number of model calls.

Sandboxed benchmarks are a deliberate design decision rather than a closed door. **CVE-Bench**
and **CyberGym** measure offensive capability, need Docker and human supervision, and answer a
different question: high capability is not a failure, it is a signal that should tighten access
and authorization. They belong to a **supervised tier beside the gate** that tiers risk, never
to the automatic pass/requires-review decision. Adding one is a code change rather than a policy
checkbox — `Check.needs_sandbox` is hardcoded `False` today and a test asserts it for every
registered benchmark, so enabling a sandboxed tier is a deliberate, reviewable act. One category
stays out at every tier regardless: benchmarks that ask a model to *develop working exploits*.

**→ [docs/BENCHMARKS.md](docs/BENCHMARKS.md#the-sandbox-tier-and-one-hard-exclusion)** for what
a sandbox tier would cost, which benchmarks are candidates, and why the exploit-development
category is excluded outright.

## Quick start

Requires Docker with Compose **v2.20.2 or newer** (`docker compose version`). On macOS,
[Colima](https://github.com/abiosoft/colima) works well:

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

A clean checkout with an empty `.env` boots and passes preflight with **no API key of any
kind**, so you can see the app work before deciding anything about models.

### How it fits together

Three services, each independently buildable so an organisation can take any one of them:

| Service | Role |
|---|---|
| **frontend** | Next.js. Submit an asset, read decisions, edit policy. |
| **backend** | FastAPI. Runs the benchmarks (Inspect AI) and the scanners, evaluates the policy, records decisions in SQLite. |
| **gateway** | LiteLLM. The single OpenAI-compatible endpoint every compute engine talks to. Separate container by necessity — see [the gateway doc](docs/GATEWAY.md#why-the-gateway-is-a-separate-container). Skip it entirely if you already have one — see [Using your own gateway](#using-your-own-gateway). |

Benchmarks run in a **subprocess with every provider credential stripped**, so a task whose
grader defaults to a hardcoded provider model fails loudly instead of silently billing someone.
Nothing submitted for scanning is ever executed.

## Configuration

Two things need configuring: **the models** (which the app only ever sees as gateway aliases)
and **the policy** (which decides what runs and what passes). The policy is the more important
one, and the one most people underestimate.

### What you can configure in a policy

Each asset class has its own policy, stored in the database as **immutable versions**. Every
edit creates a new version, the newest version governs new runs, and each run records the
version and content hash that governed it — so changing a threshold never rewrites the meaning
of a past decision. Edit them on the **Policies** page; there is no YAML to hand-write.

**AI model policy**

| Setting | What it controls |
|---|---|
| **Which benchmarks are in the suite** | A checkbox per benchmark. One not in the suite does not run and costs nothing. Metric and direction are not editable — they are facts about the benchmark, pinned to the registry. |
| **Threshold** per benchmark | The value its headline metric must clear. This is where human judgement belongs. |
| **Samples** per benchmark | How many test cases run. Presets — **Quick** (25), **Good** (100, the default), **Full** (whole datasets) — show the resulting test and model-call totals before you commit. Any gate can also be overridden individually, or pinned to a fixed **core set** of sample ids for exact repeatability. |
| **Composite weight** per benchmark | Orders the evaluations table. Never gates anything. |
| **Judge model** and **max unresolved-verdict rate** | The grader, and the point above which its output is untrustworthy and the run is voided rather than made lenient. |
| **Open-weight supply chain** | Whether an unsafe weight file blocks, and whether an unscanned repository counts as passing (it should not). |

**MCP server and agent skill policies**

| Setting | What it controls |
|---|---|
| **Blocking severities** | Which finding severities mean the submission requires review. This is the judgement call — there is no second decision mode on top of it. Note that `mcp-scanner` has no CRITICAL: HIGH is the top of its scale and is what blocks there, while `skill-scanner` does emit CRITICAL. |
| **Trust the scanner verdict** | Whether the scanner's own overall verdict is honoured rather than re-derived. |
| **Files examined per scan** | Assessment coverage. The behavioral analyzer makes one model call per file, so this trades coverage against wall clock. Exceeding it **warns and reports exactly what was left out** — it never fails the submission. |
| **Severity roll-up** | Weights used to order the evaluations table. Never gates. |

Invalid policy content is rejected with a specific error and creates no version — including a
metric that disagrees with what the benchmark actually reports, which has caused a real bug here
before.

### Models

The app speaks **OpenAI-compatible base URL + API key** and nothing else:

```
GATEWAY_BASE_URL=http://gateway:4000/v1
GATEWAY_API_KEY=sk-local
```

Point those at the bundled LiteLLM container, a corporate LiteLLM instance, a local vLLM
server, or a provider directly. The app only ever sees **aliases**, so swapping the model behind
one is a gateway change nothing else notices.

`gateway/litellm_config.yaml` ships as a **working example, not a recommendation** — a couple of
small local models plus mock routes so a clean checkout runs. Replace it with your own. Two
roles need filling: a **subject** (the model under evaluation) and a **judge** (which must
follow a grading rubric on security content without refusing it).

**→ [docs/GATEWAY.md](docs/GATEWAY.md)** covers setup, onboarding a local Ollama model,
onboarding an API-based model, the alias rule, and how to prove a route works before spending a
run on it.

### Using your own gateway

If you already have a LiteLLM instance (or any OpenAI-compatible endpoint), run the frontend
and backend locally and point them at it. Put the URL, the token and the three model aliases
in `.env`:

```bash
GATEWAY_BASE_URL=https://litellm.your-company.com/v1
GATEWAY_API_KEY=sk-...            # your gateway's key
DEFAULT_SUBJECT_MODEL=<alias>     # aliases as your gateway names them —
DEFAULT_JUDGE_MODEL=<alias>       # the bundled defaults do not exist there
SCANNER_MODEL=<alias>
```

Then start with the external-gateway overlay, which skips the bundled LiteLLM container:

```bash
docker compose -f compose.yaml -f compose.external-gateway.yaml up --build
```

Four things worth knowing:

- **The URL needs its `/v1` suffix**, and from inside Docker a gateway on your own machine is
  `http://host.docker.internal:4000/v1` — `localhost` there means the container.
- **The submit form lists whatever your gateway returns from `/v1/models`**, so you do not
  register aliases anywhere in this app. The three settings above only choose the defaults.
- **No provider keys are needed in `.env`.** They belong to your gateway. `OPENAI_API_KEY` and
  friends are read by the bundled container only, which is no longer running.
- **The header's gateway light polls `/health/readiness`** on the same host. LiteLLM serves it;
  a bare vLLM or provider endpoint may not, so the light can read unreachable while runs work
  fine. What actually protects a run is the preflight — a real completion against the chosen
  model before any evaluation starts.

### Environment

Every setting lives in the root `.env`. Docker Compose reads that file automatically and
passes these through to the backend container; the app reads no other configuration file.
`env.example` documents all of them.

| Variable | Purpose |
|---|---|
| `GATEWAY_BASE_URL` | OpenAI-compatible endpoint. Defaults to the bundled gateway |
| `GATEWAY_API_KEY` | bearer token for the above |
| `DEFAULT_SUBJECT_MODEL` | pre-selected model in the submit form. Deliberately local, so a mis-click cannot start a billed run |
| `DEFAULT_JUDGE_MODEL` | grader for the judged benchmarks |
| `SCANNER_MODEL` | analyzer the MCP/skill scanners use, one call per source file |
| `OLLAMA_API_BASE` | where the **bundled** gateway finds local models |
| provider keys | read by the **bundled gateway only**, never by the app. Which ones depends entirely on your gateway config |

The three model variables take **gateway aliases**, not provider-native model strings.

## What gets measured

Seven benchmarks for AI models, one per risk dimension — chosen by dimension rather than
reputation, with none counted twice:

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

Sample counts, thresholds and which benchmarks are in the suite all come from the policy.

**→ [docs/BENCHMARKS.md](docs/BENCHMARKS.md)** for why each one earns its place, measured
per-benchmark cost, what was assessed and deliberately left out, the Docker sandbox tier, and
the one category excluded on safety grounds.

For **MCP servers and agent skills** there is no benchmark: no published benchmark can score an
artifact someone submits, so the scanner is the evaluation and the gate is a severity rule.
Finding counts track how much code there is rather than how dangerous it is, which is why a
0–100 score over them would be invented precision.

Which severities block is a policy setting like any other, and tuning it is the one judgement
call these two classes need. A severity earns its place in the rule when its presence genuinely
distinguishes submissions; one that fires on nearly everything sends every asset to review
regardless of merit, which is the same as having no rule. `GET /api/stats/severity` returns
finding counts by analyzer and severity across all recorded runs as the evidence for that call.

## Testing

```bash
cd backend && uv run pytest      # pure-logic invariants
scripts/e2e.sh                   # builds, launches, verifies against a running stack
```

The end-to-end suite makes **real** model calls through the gateway to local models, so a full
run costs nothing. Success criteria are written down as checkable gates in
[docs/specs/ACCEPTANCE.md](docs/specs/ACCEPTANCE.md).

## Safety of the tool itself

A governance tool that could be compromised by the artifacts it inspects would be worse than no
tool. Submitted code is **never executed**:

- `git clone --depth 1`, hooks disabled, no submodules, no build step — read only.
- Zip uploads stream with a size cap and reject traversal, symlinks and bombs.
- Non-URL submissions must resolve inside an allowlisted directory.
- `mcp-scanner`'s `stdio`/`remote` modes *launch* the server under test, so they are off by
  default.

**→ [docs/SECURITY_TESTING.md](docs/SECURITY_TESTING.md)** — this tool reviewed against those
claims with Claude Code's `security-review` skill and the `claude-security` multi-agent plugin,
including the findings, the detection-calibration numbers, and what that evidence does *not*
establish.

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
- **The scanner severity rules are barely calibrated.** The false-positive baseline is thin —
  3 benign MCP servers and 4 safe skills in the vendor corpora, and one of those benign servers
  was flagged HIGH. Expect MCP in particular to send passable servers to review until
  `block_on` is tuned against real submissions. Treat a *pass* from a scanner class as weaker
  evidence than a pass from the benchmark suite.
- **Assessment coverage is capped, and the cap is a policy setting.** The behavioral analyzer
  makes one model call per source file, so `max_source_files` (default 200) bounds a scan.
  Anything beyond it is reported as a finding whose severity reflects how much went unexamined
  — never as a clean result. The rule throughout is that a limit reducing what gets assessed
  belongs in the policy, and a limit protecting the host belongs in code and must fail closed.
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

- **Calibrate the thresholds** against a funded run of models the org actually uses, and tune
  the scanner `block_on` rules once a benign corpus exists.
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

## Documentation

| Document | What is in it |
|---|---|
| [docs/GATEWAY.md](docs/GATEWAY.md) | Gateway setup, onboarding a local or API-based model, the alias rule |
| [docs/BENCHMARKS.md](docs/BENCHMARKS.md) | Why each benchmark earns its place, measured cost, what was excluded and why |
| [docs/SECURITY_TESTING.md](docs/SECURITY_TESTING.md) | This tool reviewed with Claude Code's `security-review` skill and the `claude-security` plugin |
| [docs/specs/ACCEPTANCE.md](docs/specs/ACCEPTANCE.md) | Checkable success criteria per phase, executed by `scripts/e2e.sh` |
| [docs/specs/IMPLEMENTATION_PLAN.md](docs/specs/IMPLEMENTATION_PLAN.md) | The build plan and what each phase actually established |
| [docs/research/](docs/research/) | Benchmark landscape research the suite was chosen from |

## Contributing

Issues and pull requests welcome. Please run `cd backend && uv run pytest` and
`cd frontend && npm run build` before opening a PR. If you touch scoring or gating, add a test —
those invariants are the point of the project.

## License

MIT — see [LICENSE](LICENSE).
