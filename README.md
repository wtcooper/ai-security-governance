# ai-security-governance

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
2. **The gate is deterministic.** Thresholds live in `policy.yaml`, one per benchmark, each with
   an explicit direction. No model decides an approval.

## What it evaluates

| Asset | Evaluation | Gate |
|---|---|---|
| **Foundation model** | 5 CyberSecEval-4 / AgentDojo benchmarks via [Inspect AI](https://inspect.aisi.org.uk) | one threshold per benchmark, on that benchmark's own headline metric |
| **Open weights** | 5 Hugging Face scanners (protectAI, ClamAV, picklescan, VirusTotal, JFrog), harvested not recomputed | any file any scanner calls unsafe blocks; *not scanned* ≠ safe |
| **MCP server** | full [`mcp-scanner`](https://github.com/cisco-ai-defense/mcp-scanner) sweep of cloned source | severity rule, advisory by default |
| **Agent skill** | full [`skill-scanner`](https://github.com/cisco-ai-defense/skill-scanner) sweep | severity rule + the scanner's own verdict, advisory by default |

The LLM suite is deliberately all pure-API — no Docker sandboxes — so a governance run takes
minutes and can be repeated cheaply.

For MCP servers and skills, **the scanner is the evaluation.** No benchmark scores a specific
server or skill: MCP-Bench, MCP-Universe, MCPSecBench and MCP-SafetyBench all measure how a
*client model* behaves when handed servers. And because scanner findings have no fixed
denominator — a finding count tracks how much code there is, not how dangerous it is — the gate
is a severity rule rather than a score.

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

Governance thresholds live in `backend/policy/policy.yaml`. It is content-hashed into every run,
so editing a threshold never silently rewrites the meaning of a past decision.

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

An automated security review of the codebase found **two MEDIUM issues, both real, both since
fixed** with regression tests. Both were containment failures rather than crashes, which is the
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
- **SSRF via IP encodings** — decimal, octal, short-form, IPv4-mapped IPv6 and NAT64 forms are
  normalised by resolution before the check and blocked.
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

### What this does not establish

- Recall is measured on one sample per MCP threat category, not all 141 servers.
- The false-positive denominators are 2 and 4. Enough to show the skill rule discriminates and
  that the MCP rule does not yet; nowhere near enough to justify auto-approval.
- The corpora are the scanner vendor's own, so they are likely favourable to their detections.
- No third-party penetration test.

## Known limitations

Worth reading before trusting a result:

- **Thresholds are not calibrated.** They are structurally correct placeholders. Calibrating them
  needs runs against models whose behaviour you actually care about; local models can't stand in.
  It is a `policy.yaml` edit, not a code change.
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
- **Docker eval tier** — `cyse2_interpreter_abuse`, `cyse2_vulnerability_exploit`, `cybench`,
  `cve_bench` and AgentDojo's sandbox suites, for the deep-testing path.
- **Antares as an extra source analyzer.** Cisco's open-weight vulnerability-localisation models
  are cheap and run locally; note their model card rules them out as a general judge.
- **Re-run a stored decision under a new policy** from the UI, so a threshold change can be
  reviewed against history before it is adopted.
- **Postgres + Alembic** for multi-user deployments.
- **CI workflow** running the pure-logic suite on every push.
- **Export a decision record** (PDF or signed JSON) for attaching to a ticket.

## Contributing

Issues and pull requests welcome. Please run `cd backend && uv run pytest` and
`cd frontend && npm run build` before opening a PR. If you touch scoring or gating, add a test —
those invariants are the point of the project.

## License

MIT — see [LICENSE](LICENSE).
