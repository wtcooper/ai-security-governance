# ai-security-governance

Self-service application to manage security-focused evaluations and governance thresholds
for approved organizational use of AI assets (models, MCP servers, agent skills).

## What problem this solves

We have no defined testing bar for onboarding new AI assets, so every new foundation model,
MCP server, or agent skill gets an ad-hoc judgement call.

This is the tool used **after** terms/legal review has already established that an asset
can't be waved through. Its only job is to answer one security question: *does this asset
clear our security thresholds (auto-approve), or does it need formal deep testing?*

Scope is strictly security testing criteria. Harmful-content and toxicity evaluation belong
to compliance — the separation of duties is deliberate, so nothing here scores for harm.

Two rules shape the whole design:

1. **Harvest before compute.** If a benchmark result or a model scan is already published,
   pull it rather than burning our own compute. Every score records its provenance
   (`published` / `harvested` / `self_run`) and a source URL.
2. **The gate is deterministic.** Thresholds live in a versioned `policy.yaml`, one gate per
   benchmark on that benchmark's own headline metric. No LLM decides approval.

## Status

**All phases built and verified** against a real stack via `scripts/e2e.sh`, with every
model call going to local Ollama models so a full acceptance run costs $0.

| Phase | Scope | State |
|---|---|---|
| 0 | Compose stack, LiteLLM gateway, preflight, model discovery | ✅ |
| 1 | LLM path: 5 CyberSecEval-4/AgentDojo gates, judge integrity, leaderboard | ✅ |
| 2 | Open-weight supply-chain scan (5 Hugging Face scanners) | ✅ |
| 3 | MCP server path (`mcp-scanner`, full analyzer sweep) | ✅ |
| 4 | Agent skill path (`skill-scanner`, full analyzer sweep) | ✅ |
| 5 | Policy-as-data, published-score ingestion, severity stats | ✅ |

**One thing is deliberately not done: the thresholds are not calibrated.** They are
structurally correct placeholders. Calibrating them requires runs against models whose
behaviour the org actually cares about, and local models cannot stand in for that. It is one
funded run away, and it changes `policy.yaml` only — the mechanism is built and tested.

### What each asset class is judged on

| Asset | Evaluation | Gate |
|---|---|---|
| Foundation model | 5 CyberSecEval-4 / AgentDojo benchmarks via Inspect AI | one threshold per benchmark, on that benchmark's own headline metric |
| Open weights | 5 Hugging Face scanners, harvested not recomputed | any file any scanner calls unsafe blocks; "not scanned" ≠ safe |
| MCP server | full `mcp-scanner` sweep of cloned source | severity rule, **advisory** in v1 |
| Agent skill | full `skill-scanner` sweep | severity rule + the scanner's own `is_safe`, **advisory** in v1 |

For MCP servers and skills, **the scanner is the evaluation.** No benchmark scores a specific
server or skill — MCP-Bench, MCP-Universe, MCPSecBench and MCP-SafetyBench all measure how a
*client model* behaves when handed servers. And because scanner findings have no fixed
denominator (a count tracks how much code there is, not how dangerous it is), the gate is a
severity rule rather than a score: normalising findings to 0–100 and thresholding that would
be inventing precision. Both start in advisory mode, which can withhold approval but never
grant it, because there is no false-positive baseline yet.

## Quick start

```bash
brew install colima docker docker-compose
colima start --cpus 4 --memory 8 --disk 60 --vm-type vz

cp env.example .env        # optional — see "No keys required" below
docker compose up --build
```

| Service | URL | Notes |
|---|---|---|
| Frontend | http://localhost:3000 | |
| Backend | http://localhost:8000/docs | OpenAPI browser |
| Gateway | http://localhost:4001/health/readiness | 4001, not 4000 — see below |

Verify the stack:

```bash
curl -s localhost:8000/api/gateway/status          # gateway reachable?
curl -s localhost:8000/api/models                 # aliases available to submit
curl -s -X POST localhost:8000/api/preflight \
  -H 'Content-Type: application/json' \
  -d '{"model":"mock-target-compliant","judge_model":"mock-judge"}'
```

### No keys required

The gateway ships mock model routes (`mock-target-compliant`, `mock-target-refusal`,
`mock-target-policy-block`, `mock-judge`) implemented as custom LiteLLM providers. A clean
checkout with an empty `.env` boots and passes preflight with **no API key of any kind**.
Mocks prove wiring only — a run records which judge graded it, so a `mock-judge` run can
never be mistaken for a real evaluation.

### Compose is on port 4001

LiteLLM's conventional port is 4000, which is commonly already taken by another project's
gateway. Silently colliding with one is worse than using a neighbouring port, so the
container listens on 4000 internally and publishes to **4001** on the host.

## Everything speaks OpenAI-compatible

The hard requirement: **never assume a direct provider API key.** Any endpoint that accepts
an OpenAI-format base URL and bearer key must work out of the box, and no benchmark may
assume a particular provider's credentials.

The backend knows exactly two things about reaching a model:

```
GATEWAY_BASE_URL=http://gateway:4000/v1
GATEWAY_API_KEY=sk-local
```

Point those at a work LiteLLM instance, a local vLLM server, or `api.openai.com` directly
and nothing else changes. A direct provider key is *supported*, never *assumed*.

One gateway config drives all three compute engines — the env var names are each engine's
own, but they carry the same base-URL-plus-key pair:

| Engine | Base URL | Key | Model |
|---|---|---|---|
| Inspect AI | `GATEWAY_BASE_URL` | `GATEWAY_API_KEY` | `openai-api/gateway/<alias>` |
| mcp-scanner | `MCP_SCANNER_LLM_BASE_URL` | `MCP_SCANNER_LLM_API_KEY` | `MCP_SCANNER_LLM_MODEL` |
| skill-scanner | `SKILL_SCANNER_LLM_BASE_URL` | `SKILL_SCANNER_LLM_API_KEY` | `SKILL_SCANNER_LLM_MODEL` |

Two safeguards keep this true rather than aspirational:

- **The UI offers a dropdown of gateway aliases, never a free-text model field**, so a
  provider-native model string cannot be typed into a run.
- **Preflight runs a real completion for the subject *and* the judge before any run
  starts**, and returns the upstream error body verbatim on failure. Judge routing is the
  more common breakage: `inspect_evals` tasks default their graders to hardcoded
  `openai/gpt-4o-mini`, which goes straight to api.openai.com.

## Model aliases

Configured in `gateway/litellm_config.yaml`. Add upstreams there; the app needs no changes.

| Alias | Upstream | Role |
|---|---|---|
| `gemma4`, `gemma4-e2b` | local Ollama | **default subject** — free |
| `qwen35` | local Ollama | **default judge** — free |
| `gpt-5.6-luna` | OpenAI | calibration judge ($0.20/$1.20 per M tokens) |
| `gemini-3.5-flash-lite` | Google AI Studio | fallback calibration judge ($0.30/$2.50 per M) |
| `mock-target-*`, `mock-judge` | in-process mocks | zero-key boot proof only |

Defaults are local so development and the whole test suite cost nothing. Hosted models are
opt-in via `DEFAULT_JUDGE_MODEL` and only needed for Phase 5 threshold calibration.

> `gpt-5.6-luna` currently returns `RateLimitError: You have no credits remaining` — the
> OpenAI account needs credits before it can be used as a judge. Nothing depends on it
> today.

> **Alias rule:** no slashes or colons. Inspect parses model strings as
> `openai-api/<provider>/<model>` and splits on `/`, so `gemma4:e2b` is aliased to
> `gemma4-e2b`. The real name stays in `litellm_params.model`.

### Local models

Ollama runs on the **host** by default; Colima maps `host.docker.internal`. If that mapping
misbehaves, run Ollama in-cluster instead:

```bash
docker compose --profile local-models up
docker compose exec ollama ollama pull gemma4
```

## Architecture

```
compose.yaml
  gateway   :4001->4000   LiteLLM — the single OpenAI-compatible surface
  backend   :8000         FastAPI + Inspect AI + inspect-evals + both Cisco scanners
  frontend  :3000         Next.js App Router
  ollama    :11434        optional, profile: local-models
```

SQLite lives on the `appdata` volume alongside eval logs, scanner reports, and per-run
clone workspaces. All DB access goes through SQLModel, so swapping in a hosted Postgres is a
connection-string change rather than a rewrite.

### Why the gateway is a separate image

`litellm[proxy]` requires `boto3>=1.43.1`, while `inspect-ai` requires `aioboto3>=13.0.0`,
whose current release caps `boto3<1.40.62`. They cannot share a virtualenv. The plain
`litellm` **library** coexists fine, which is why the Cisco scanners (which use it as a
library) install into the same venv as Inspect — one backend image, one venv.

`backend/tests/test_engine_coexistence.py` asserts this arrangement, so if the upstream
constraints change, a test tells us rather than a confusing runtime failure.

### Known upstream pins

Both are in `gateway/requirements.txt` with the reasoning inline:

- `litellm[proxy]>=1.85.1,<2` — **security.** Versions 1.82.7 and 1.82.8 were malicious
  (TeamPCP PyPI compromise, 2026-03-24) and shipped a `.pth` payload that executed on every
  Python process start. Safe ranges are `<=1.82.6` or `>=1.83.0`. The backend carries the
  same floor because litellm arrives there transitively via the scanners.
- `fastapi<0.140.7` — **compatibility.** litellm 1.95.0 declares `fastapi<1.0,>=0.136.3`,
  but that ceiling is wrong: fastapi removed
  `fastapi.dependencies.utils.get_flat_dependant`, which litellm's management endpoints
  import at startup, so the proxy dies before binding a port. Bisected boundary: present
  through 0.140.6, gone from 0.140.7. The backend is unaffected and tracks current fastapi.

## Testing

Success criteria for every part of the build are written down as checkable gates in
[ACCEPTANCE.md](ACCEPTANCE.md), and `scripts/e2e.sh` executes them against a real stack:

```bash
scripts/e2e.sh              # build, launch, verify all criteria, tear down
scripts/e2e.sh --keep-up    # leave the stack running afterwards
scripts/e2e.sh --no-build   # reuse existing images
```

Four rules keep this honest:

1. **End-to-end over unit.** Criteria are satisfied by real HTTP against a running stack,
   real model calls, and real subprocesses. Unit tests cover only pure logic (credential
   scrubbing, score normalization, gate arithmetic) where a real round trip proves nothing
   extra.
2. **No mocked model call backs a correctness claim.** The gateway's mock routes prove
   exactly one thing — that the stack boots and passes preflight with zero API keys.
3. **Local models only.** Every gate runs against host Ollama (`gemma4`, `qwen35`) through
   the gateway. `gpt-5.6-luna` and `gemini-3.5-flash-lite` are reserved for Phase 5
   threshold calibration and are never touched by the suite. **A full run costs $0.**
4. **Judged paths are actually judged.** Any criterion involving a grader routes the judge
   through the gateway too, so judge misrouting can't hide behind a passing subject.

The two criteria that matter most are 0.7 and 0.8: Inspect AI running a real eval through
the gateway, and a real *model-graded* eval routing its judge through the same gateway. The
path exercised is backend container → gateway container → host Ollama, with every provider
credential stripped from the eval subprocess. You can run them directly:

```bash
curl -s -X POST localhost:8000/api/selftest/inspect \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemma4","judge_model":"qwen35","include_judge":true}'
```

Or run the eval child standalone, outside the app, to debug gateway wiring in isolation:

```bash
cd backend
GATEWAY_BASE_URL=http://localhost:4001/v1 GATEWAY_API_KEY=sk-local \
  uv run python -m app.engines.inspect_child \
    --task gateway_judge_selftest \
    --model openai-api/gateway/gemma4 \
    --judge-model openai-api/gateway/qwen35 \
    --log-dir /tmp/inspect-logs
```

## Development

```bash
# Backend
cd backend && uv sync && uv run pytest
GATEWAY_BASE_URL=http://localhost:4001/v1 GATEWAY_API_KEY=sk-local \
  uv run uvicorn app.main:app --reload --port 8000

# Gateway on the host (needs its own venv — see the boto3 conflict above)
uv venv .venv-gateway --python 3.12
uv pip install --python .venv-gateway -r gateway/requirements.txt
bash gateway/start_proxy.sh

# Frontend
cd frontend && npm install && npm run dev
```

## Operating it

### Calibrating the thresholds

`backend/policy/policy.yaml` is the gate; the code only evaluates it. Every run records the
policy version and a content hash, so a threshold edited next month does not silently rewrite
the meaning of a decision made today.

To calibrate: point `DEFAULT_JUDGE_MODEL` at a hosted judge, run 2–3 models you have already
approved, and adjust thresholds until those models come back `auto_approve`. Nothing else
changes — a test asserts that a stored run re-decides differently when only the YAML changes.

### Graduating MCP/skill from advisory to gating

Both scanner-backed classes ship as `mode: advisory`, which can withhold approval but never
grant it. That is deliberate: without a false-positive baseline, an untuned severity rule
cannot be trusted to approve anything.

```bash
curl -s localhost:8000/api/stats/severity   # findings by analyzer and severity, all runs
```

When the distribution shows that `block_on` is discriminating rather than firing on
everything, change `mode: advisory` to `mode: gating` for that asset class. That single line
is the whole change.

Bear in mind `mcp-scanner` has no CRITICAL severity — HIGH is the top of its scale, so HIGH is
what actually blocks there. `skill-scanner` does emit CRITICAL.

### Adding a published score

```bash
curl -s -X POST localhost:8000/api/published-scores/extract \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://.../system-card"}'      # proposes candidates, saves nothing
```

Review each candidate against its quoted sentence, then POST the ones you believe to
`/api/published-scores`. The confirmation step is not ceremony: an unreviewed number
extracted by a model reading prose could auto-approve a model that was never measured.

### Known limitations, stated plainly

- **Thresholds are uncalibrated placeholders.** See above.
- **MCP/skill scans are slow.** The behavioral analyzer runs a model per source file. A
  monorepo is capped at 40 files and the shortfall is reported as a finding — a scan that
  silently covered part of a tree reads exactly like a scan that found nothing. Submit the
  individual server directory rather than a monorepo.
- **Tools are not enumerated live.** Getting a server's real tool list means launching it,
  which is executing untrusted code. Detection therefore comes from source analysis and
  cannot see tools generated at runtime.
- **Dependency audit covers pinned packages only.** pip-audit's resolution venv aborts on
  some hosts, and when it fails the scanner reports "SAFE (0 findings)". We detect that and
  record it as a finding instead, running the audit with `--no-deps --disable-pip`.
- **No Docker eval tier.** `cyse2_interpreter_abuse`, `cyse2_vulnerability_exploit`,
  `cybench`, `cve_bench` and AgentDojo's sandbox suites need Docker-in-Docker. The five
  shipped benchmarks are all pure-API by design.

## Deployment

Not deployed anywhere — local only. Each component builds independently, so an organisation
can take any one of them and run it their own way.

Swapping SQLite for a hosted database is the one change most deployments will want: all DB
access goes through SQLModel, so it is a connection-string change in `app/config.py` rather
than a rewrite.
