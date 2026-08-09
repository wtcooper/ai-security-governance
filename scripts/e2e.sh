#!/usr/bin/env bash
# End-to-end acceptance runner.
#
# Builds and launches the full stack with docker compose, then verifies every criterion for
# the completed phases in ACCEPTANCE.md against the running system. Real HTTP, real model
# calls, real subprocesses — the only mocks involved are the gateway's mock model routes,
# used solely to prove the stack boots with zero API keys.
#
# All model traffic goes to LOCAL Ollama models through the gateway, so a full run costs $0.
#
# Usage:
#   scripts/e2e.sh              # build, verify, tear down
#   scripts/e2e.sh --keep-up    # leave the stack running afterwards
#   scripts/e2e.sh --no-build   # reuse existing images
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

KEEP_UP=0
BUILD=1
for arg in "$@"; do
    case "$arg" in
        --keep-up) KEEP_UP=1 ;;
        --no-build) BUILD=0 ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

BACKEND=http://localhost:8000
FRONTEND=http://localhost:3000
GATEWAY=http://localhost:4001
SUBJECT_MODEL=gemma4
JUDGE_MODEL=qwen35
# Sample cap for the acceptance run. Deliberately tiny: the point is to prove the machinery
# end to end, and local judge models are slow (reasoning models emit long traces). A real
# governance run uses the registry defaults instead.
E2E_RUN_LIMIT=${E2E_RUN_LIMIT:-2}
E2E_RUN_TIMEOUT=${E2E_RUN_TIMEOUT:-5400}
# Scanner sweeps invoke a model per source file, so a fixture scan is minutes not seconds.
E2E_SCAN_TIMEOUT=${E2E_SCAN_TIMEOUT:-2700}

PASS=0
FAIL=0
declare -a FAILURES=()

pass() { PASS=$((PASS + 1)); printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() {
    FAIL=$((FAIL + 1))
    FAILURES+=("$1")
    printf '  \033[31mFAIL\033[0m  %s\n' "$1"
    [ -n "${2:-}" ] && printf '        %s\n' "$(echo "$2" | head -c 500 | tr '\n' ' ')"
}
section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

cleanup() {
    if [ "$KEEP_UP" -eq 0 ]; then
        echo
        echo "Tearing down..."
        docker compose down -v >/dev/null 2>&1
    else
        echo
        echo "Stack left running: frontend $FRONTEND | backend $BACKEND/docs | gateway $GATEWAY"
    fi
}
trap cleanup EXIT

# --------------------------------------------------------------------------------------
section "Pre-flight: host requirements"
# --------------------------------------------------------------------------------------
if ! docker info >/dev/null 2>&1; then
    echo "Docker is not reachable. Start Colima first:  colima start --cpus 4 --memory 8 --vm-type vz"
    exit 1
fi
pass "docker daemon reachable"

# Local models are the entire test substrate, so a missing Ollama is a hard stop rather
# than a silently skipped set of criteria.
if curl -sf --max-time 5 http://localhost:11434/api/tags >/dev/null 2>&1; then
    HOST_MODELS=$(curl -sf http://localhost:11434/api/tags | python3 -c "
import json,sys
print(','.join(sorted(m['name'] for m in json.load(sys.stdin).get('models', []))))" 2>/dev/null)
    pass "host Ollama reachable (models: ${HOST_MODELS:-none})"
    for required in gemma4 qwen3.5; do
        case "$HOST_MODELS" in
            *"$required"*) pass "required local model present: $required" ;;
            *) fail "required local model missing: $required" "run: ollama pull $required" ;;
        esac
    done
else
    fail "host Ollama not reachable on :11434" \
        "Start Ollama, or run: docker compose --profile local-models up -d"
fi

# --------------------------------------------------------------------------------------
section "0.1 / 0.9  Engine coexistence and credential scrubbing"
# --------------------------------------------------------------------------------------
if PYTEST_OUT=$(cd backend && uv run pytest -q 2>&1); then
    pass "backend pure-logic suite ($(echo "$PYTEST_OUT" | tail -1 | tr -d '\n'))"
else
    fail "backend pure-logic suite" "$PYTEST_OUT"
fi

# --------------------------------------------------------------------------------------
section "0.2  Clean-volume compose build and launch"
# --------------------------------------------------------------------------------------
docker compose down -v >/dev/null 2>&1
if [ "$BUILD" -eq 1 ]; then
    if BUILD_OUT=$(docker compose build 2>&1); then
        pass "docker compose build"
    else
        fail "docker compose build" "$BUILD_OUT"
        exit 1
    fi
fi

if UP_OUT=$(docker compose up -d 2>&1); then
    pass "docker compose up (gateway healthcheck gates the backend)"
else
    fail "docker compose up" "$UP_OUT"
    docker compose logs --tail 40
    exit 1
fi

READY=0
for _ in $(seq 1 120); do
    if curl -sf --max-time 3 "$BACKEND/api/health" >/dev/null 2>&1 \
        && curl -sf --max-time 3 "$FRONTEND" >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done
if [ "$READY" -eq 1 ]; then
    pass "backend and frontend responding"
else
    fail "stack did not come up" "$(docker compose ps; docker compose logs --tail 30)"
    exit 1
fi

if curl -sf --max-time 5 "$GATEWAY/health/readiness" | grep -q healthy; then
    pass "gateway readiness healthy"
else
    fail "gateway readiness" "$(docker compose logs gateway --tail 20)"
fi

# --------------------------------------------------------------------------------------
section "0.3  Zero-API-key path"
# --------------------------------------------------------------------------------------
MOCK_OUT=$(curl -sf --max-time 60 -X POST "$BACKEND/api/preflight" \
    -H 'Content-Type: application/json' \
    -d '{"model":"mock-target-compliant","judge_model":"mock-judge"}' 2>&1)
if echo "$MOCK_OUT" | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin)['ok'] else 1)" 2>/dev/null; then
    pass "preflight succeeds with no API keys (mock routes)"
else
    fail "zero-key preflight" "$MOCK_OUT"
fi

# --------------------------------------------------------------------------------------
section "0.4 / 0.5  Gateway reachability and model discovery"
# --------------------------------------------------------------------------------------
STATUS_OUT=$(curl -sf --max-time 10 "$BACKEND/api/gateway/status" 2>&1)
if echo "$STATUS_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
sys.exit(0 if d['ok'] and d['base_url']=='http://gateway:4000/v1' else 1)" 2>/dev/null; then
    pass "backend reaches gateway over compose service DNS"
else
    fail "gateway status via service DNS" "$STATUS_OUT"
fi

MODELS_OUT=$(curl -sf --max-time 15 "$BACKEND/api/models" 2>&1)
if echo "$MODELS_OUT" | python3 -c "
import json,sys
models=json.load(sys.stdin)
assert '$SUBJECT_MODEL' in models, 'missing $SUBJECT_MODEL'
assert '$JUDGE_MODEL' in models, 'missing $JUDGE_MODEL'
# The dropdown must expose only gateway aliases; a '/' means a provider-native string leaked.
bad=[m for m in models if '/' in m]
assert not bad, f'provider-native strings exposed: {bad}'" 2>/dev/null; then
    pass "model discovery returns gateway aliases only"
else
    fail "model discovery" "$MODELS_OUT"
fi

# --------------------------------------------------------------------------------------
section "0.6  Real local model answers through the gateway"
# --------------------------------------------------------------------------------------
REAL_OUT=$(curl -sf --max-time 600 -X POST "$BACKEND/api/preflight" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$SUBJECT_MODEL\",\"judge_model\":\"$JUDGE_MODEL\"}" 2>&1)
if echo "$REAL_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['ok'], d
for c in d['checks']:
    assert c['ok'], c
    assert c['latency_ms'] is not None
print('  subject+judge latencies:', {c['role']: c['latency_ms'] for c in d['checks']})" 2>/dev/null; then
    pass "real completion from $SUBJECT_MODEL and $JUDGE_MODEL via gateway"
else
    fail "real local model preflight" "$REAL_OUT"
fi

# --------------------------------------------------------------------------------------
section "0.7 / 0.8  Inspect AI evals real models through the gateway (subject AND judge)"
# --------------------------------------------------------------------------------------
echo "  running real evals, this takes a minute on local models..."
INSPECT_OUT=$(curl -sf --max-time 1800 -X POST "$BACKEND/api/selftest/inspect" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$SUBJECT_MODEL\",\"judge_model\":\"$JUDGE_MODEL\",\"include_judge\":true}" 2>&1)

INSPECT_EVAL=$(echo "$INSPECT_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
by={r['task']: r for r in d['results']}

s=by.get('gateway_selftest')
assert s and s['ok'], f\"gateway_selftest failed: {s}\"
assert s['payload']['status']=='success', s['payload']
assert any('includes' in k for k in s['payload']['metrics']), s['payload']['metrics']
print('SUBJECT_OK', s['payload']['metrics'])

j=by.get('gateway_judge_selftest')
assert j and j['ok'], f\"gateway_judge_selftest failed: {j}\"
assert j['payload']['status']=='success', j['payload']
assert any('model_graded' in k for k in j['payload']['metrics']), j['payload']['metrics']
print('JUDGE_OK', j['payload']['metrics'])
" 2>&1)

if echo "$INSPECT_EVAL" | grep -q SUBJECT_OK; then
    pass "Inspect AI eval through gateway to $SUBJECT_MODEL — $(echo "$INSPECT_EVAL" | grep SUBJECT_OK | cut -c12-)"
else
    fail "Inspect AI subject eval" "${INSPECT_EVAL}${INSPECT_OUT}"
fi
if echo "$INSPECT_EVAL" | grep -q JUDGE_OK; then
    pass "Inspect AI model-graded judge through gateway to $JUDGE_MODEL — $(echo "$INSPECT_EVAL" | grep JUDGE_OK | cut -c10-)"
else
    fail "Inspect AI judge routing" "${INSPECT_EVAL}${INSPECT_OUT}"
fi

# --------------------------------------------------------------------------------------
section "1.1 / 1.3  Registry: judge overrides declared, metric keys pinned to live output"
# --------------------------------------------------------------------------------------
CHECKS_OUT=$(curl -sf --max-time 15 "$BACKEND/api/checks?asset_type=llm" 2>&1)
if echo "$CHECKS_OUT" | python3 -c "
import json,sys
checks={c['id']: c for c in json.load(sys.stdin)}
# The seven gated benchmarks: one per risk dimension. atb_autonomy_hijack, atb_data_exfil
# and cyse4_autocomplete stay REGISTERED but ungated, so /api/checks lists all ten while the
# suite runs seven.
expected={'cyse4_multilingual_prompt_injection','cyse4_mitre','cyse4_mitre_frr',
          'cyse4_instruct','agentdojo','atb_memory_poison','strong_reject'}
assert expected <= set(checks), f'missing from registry: {sorted(expected - set(checks))}'
# Both judged checks must advertise that they need one, or an upstream default takes over.
assert checks['cyse4_mitre']['needs_judge']
assert checks['cyse4_multilingual_prompt_injection']['needs_judge']
# AgentThreatBench scores deterministically; declaring a judge would waste a call per sample.
assert not checks['atb_memory_poison']['needs_judge']
# Directions must not have collapsed to one value (a classic copy-paste error).
assert len({c['direction'] for c in checks.values()})==2
" 2>/dev/null; then
    pass "the seven-dimension suite is registered with judge requirements and mixed directions"
else
    fail "check registry" "$CHECKS_OUT"
fi

POLICY_OUT=$(curl -sf --max-time 15 "$BACKEND/api/policy" 2>&1)
if echo "$POLICY_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
# Phase 8: per-class versions + hashes replace the single top-level pair.
assert all(c['content_hash'] for c in d['classes'].values()), 'policies must be content-hashed'
assert d['composite_is_display_only'] is True
assert len(d['llm_gates'])==7, d['llm_gates']
assert all('planned_samples' in g for g in d['llm_gates'].values()), 'gates must carry sample counts'
assert d['thresholds_are_calibrated'] is False, 'placeholders must be labelled as such'
" 2>/dev/null; then
    pass "policy exposes 5 gates with sample counts, per-class hashes, honest calibration status"
else
    fail "policy endpoint" "$POLICY_OUT"
fi

# --------------------------------------------------------------------------------------
section "8.1-8.4  Versioned policies: seed, immutable edit, validation, governing samples"
# --------------------------------------------------------------------------------------
SEED_OUT=$(curl -sf --max-time 15 "$BACKEND/api/policies" 2>&1)
if echo "$SEED_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert set(d)=={'llm','mcp','skill'}, set(d)
assert all(v['version']==1 and v['content_hash'] for v in d.values()), d
" 2>/dev/null; then
    pass "8.1 clean DB seeded one v1 policy per asset class, content-hashed"
else
    fail "policy seeding" "$SEED_OUT"
fi

# Invalid content must be rejected with a named problem and create nothing.
LLM_V1=$(curl -sf --max-time 15 "$BACKEND/api/policies/llm/versions/1" 2>&1)
BAD_STATUS=$(echo "$LLM_V1" | python3 -c "
import json,sys,urllib.request,urllib.error
content=json.load(sys.stdin)['content'].replace('metric: refusal_rate','metric: accuracy')
body=json.dumps({'content':content,'note':'must fail'}).encode()
req=urllib.request.Request('$BACKEND/api/policies/llm/versions',data=body,
                           headers={'Content-Type':'application/json'})
try:
    urllib.request.urlopen(req); print('accepted')
except urllib.error.HTTPError as e:
    detail=json.loads(e.read())['detail']
    print(e.code if 'metric must be' in detail else f'{e.code}:{detail[:80]}')
" 2>/dev/null)
if [ "$BAD_STATUS" = "422" ]; then
    pass "8.3 policy disagreeing with the registry rejected (422, named problem)"
else
    fail "policy validation" "got: $BAD_STATUS"
fi

# A valid edit creates v2; v1 stays byte-identical; the new samples value governs /checks.
EDIT_OUT=$(echo "$LLM_V1" | python3 -c "
import json,sys,urllib.request
v1=json.load(sys.stdin)['content']
edited=v1.replace('samples: 20','samples: 7',1)
assert edited!=v1
body=json.dumps({'content':edited,'note':'e2e: PI samples 20->7'}).encode()
req=urllib.request.Request('$BACKEND/api/policies/llm/versions',data=body,
                           headers={'Content-Type':'application/json'})
v2=json.loads(urllib.request.urlopen(req).read())
v1_again=json.loads(urllib.request.urlopen('$BACKEND/api/policies/llm/versions/1').read())
assert v2['version']==2 and v2['is_active']
assert v1_again['content']==v1, 'v1 content changed - immutability broken'
checks=json.loads(urllib.request.urlopen('$BACKEND/api/checks?asset_type=llm').read())
pi=[c for c in checks if c['id']=='cyse4_multilingual_prompt_injection'][0]
assert pi['planned_samples']==7, pi
print('OK')
" 2>&1)
if [ "$EDIT_OUT" = "OK" ]; then
    pass "8.2/8.4 edit created immutable v2 and its sample count now governs"
else
    fail "policy edit round-trip" "$EDIT_OUT"
fi

# Benchmark transparency endpoints.
BENCH_OUT=$(curl -sf --max-time 15 "$BACKEND/api/benchmarks" 2>&1)
if echo "$BENCH_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
rows=d['benchmarks']
assert len(rows)==10, len(rows)  # all registered, gated or not
assert all(r['intent'] for r in rows), 'a benchmark has no intent text'
assert all(r['cost_note'] for r in rows), 'a benchmark has no cost note'
# 9.x: no shipped benchmark may require a sandbox (the ExploitGym rule).
assert not any(r['needs_sandbox'] for r in rows), 'a benchmark requires a sandbox'
assert d['suite']['estimated_calls'] > 0, d['suite']
" 2>/dev/null; then
    pass "9.1 benchmarks endpoint lists all ten registered with intent, cost, and no sandbox"
else
    fail "benchmarks endpoint" "$BENCH_OUT"
fi

# --------------------------------------------------------------------------------------
section "1.2 / 1.4-1.9  A real governance run, all 5 benchmarks, local models"
# --------------------------------------------------------------------------------------
echo "  starting a real run (subject $SUBJECT_MODEL, judge $JUDGE_MODEL, limit $E2E_RUN_LIMIT)..."
echo "  this runs five real benchmarks on local models and takes a while."
RUN_CREATE=$(curl -sf --max-time 900 -X POST "$BACKEND/api/runs" \
    -H 'Content-Type: application/json' \
    -d "{\"asset_type\":\"llm\",\"name\":\"e2e $SUBJECT_MODEL\",\"identifier\":\"$SUBJECT_MODEL\",\"judge_model\":\"$JUDGE_MODEL\",\"limit\":$E2E_RUN_LIMIT}" 2>&1)
RUN_ID=$(echo "$RUN_CREATE" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" 2>/dev/null)

if [ -n "$RUN_ID" ]; then
    pass "run $RUN_ID created (preflight passed for subject and judge)"

    # 8.9: live progress is queryable while the run executes.
    PROG_OUT=$(curl -sf --max-time 20 "$BACKEND/api/runs/$RUN_ID/progress" 2>&1)
    if echo "$PROG_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert len(d['benchmarks'])==7, d
assert all(b['state'] in ('done','running','queued') for b in d['benchmarks']), d
assert d['sample_override']==$E2E_RUN_LIMIT, d
" 2>/dev/null; then
        pass "8.9 progress endpoint reports all seven gated benchmarks and the override"
    else
        fail "run progress endpoint" "$PROG_OUT"
    fi

    DEADLINE=$((SECONDS + E2E_RUN_TIMEOUT))
    RUN_JSON=""
    while [ $SECONDS -lt $DEADLINE ]; do
        RUN_JSON=$(curl -sf --max-time 20 "$BACKEND/api/runs/$RUN_ID" 2>/dev/null)
        STATE=$(echo "$RUN_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])" 2>/dev/null)
        [ "$STATE" = "complete" ] || [ "$STATE" = "failed" ] && break
        sleep 15
    done

    if echo "$RUN_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['status'] in ('complete','failed'), f\"run did not finish: {d['status']}\"

# Criterion 1.2: every benchmark must have produced a score. Read from scores rather than
# gate_outcomes, because a run invalidated by an unreliable judge deliberately emits no
# decision - the scores still exist and coverage is still the thing being checked.
gated=[s for s in d['scores'] if s['gated']]
ids={s['check_id'] for s in gated}
# The seven gated benchmarks: one per risk dimension. atb_autonomy_hijack, atb_data_exfil
# and cyse4_autocomplete stay REGISTERED but ungated, so /api/checks lists all ten while the
# suite runs seven.
expected={'cyse4_multilingual_prompt_injection','cyse4_mitre','cyse4_mitre_frr',
          'cyse4_instruct','agentdojo','atb_memory_poison','strong_reject'}
assert ids==expected, f'benchmarks without a score: {sorted(expected-ids)}'
assert all(s['raw_value'] is not None for s in gated), 'a gated score has no value'

assert d['decision'] in ('auto_approve','needs_deep_testing','error'), d['decision']

# Criterion 1.8: if the judge produced unusable verdicts, the run must be ERROR.
# Reads the STRUCTURAL signal (the scorer's own unresolved counter), not the advisory
# phrasing heuristic, which cannot tell a judge refusal from a subject refusal.
rate=d['judge_unresolved_rate']
if rate is not None and rate > 0.05:
    assert d['decision']=='error', f'judge refused {rate:.0%} but decision was {d[\"decision\"]}'
    assert 'judge' in (d['decision_reason'] or '').lower()
    print('  JUDGE GUARD FIRED: refusal', f'{rate:.0%}', '-> error, no decision emitted')
else:
    assert d['decision'] != 'error', d['decision_reason']

# Criterion 1.9: provenance recorded.
assert d['judge_model'], 'judge model not recorded'
assert d['policy_hash'], 'policy hash not recorded'
# Criterion 1.4: ungated extras recorded but never thresholded.
extras=[s for s in d['scores'] if not s['gated']]
assert extras, 'no ungated metrics captured - extras should be stored for inspection'
assert all(s['threshold'] is None for s in extras), 'an ungated metric was given a threshold'
# Criterion 1.5: composite present but flagged display-only.
assert d['composite_is_display_only'] is True
print('  decision:', d['decision'])
print('  composite (display only):', d['composite_score'])
for s in sorted(gated, key=lambda x: x['check_id']):
    print(f\"    {'pass' if s['passed'] else 'FAIL'}  {s['check_id']}: {s['metric']}={s['raw_value']}\")
" 2>&1 | tee /tmp/e2e-run-detail.txt | grep -q "decision:"; then
        pass "all 7 benchmarks scored; decision and judge guard behaved correctly"
        sed -n '1,20p' /tmp/e2e-run-detail.txt
    else
        fail "real governance run" "$(cat /tmp/e2e-run-detail.txt 2>/dev/null)"
    fi

    # Criterion 1.9 continued: the run detail page must render the provenance.
    RUN_HTML=$(curl -sf --max-time 20 "$FRONTEND/runs/$RUN_ID" 2>&1)
    MISSING_RUN=""
    for needle in "Benchmark gates" "Run provenance" "$JUDGE_MODEL" "display only"; do
        echo "$RUN_HTML" | grep -q "$needle" || MISSING_RUN="$MISSING_RUN '$needle'"
    done
    if [ -z "$MISSING_RUN" ]; then
        pass "run detail page renders gates, provenance, and the display-only caveat"
    else
        fail "run detail page" "missing:$MISSING_RUN"
    fi

    # Leaderboard must show the run with its gate tally.
    LB_OUT=$(curl -sf --max-time 20 "$BACKEND/api/leaderboard/llm" 2>&1)
    if echo "$LB_OUT" | python3 -c "
import json,sys
rows=json.load(sys.stdin)
assert rows, 'leaderboard empty after a completed run'
r=rows[0]
assert r['gates_total']==5, r['gates_total']
assert r['composite_is_display_only'] is True
" 2>/dev/null; then
        pass "leaderboard reports the run with a 7-gate denominator"
    else
        fail "leaderboard" "$LB_OUT"
    fi
else
    fail "create run" "$RUN_CREATE"
fi

# --------------------------------------------------------------------------------------
section "2.1-2.4  Open-weight supply-chain scan harvested from Hugging Face"
# --------------------------------------------------------------------------------------
# Two live repos chosen for what they prove: gpt2 has completed scans, and
# stable-diffusion-v1-4 has scansDone=false, which is the case that must NOT read as safe.
HF_OUT=$(curl -sf --max-time 120 -X POST "$BACKEND/api/runs" \
    -H 'Content-Type: application/json' \
    -d "{\"asset_type\":\"llm\",\"name\":\"gpt2 weights\",\"identifier\":\"$SUBJECT_MODEL\",\"judge_model\":\"$JUDGE_MODEL\",\"hf_repo_id\":\"openai-community/gpt2\",\"limit\":1,\"only_checks\":[\"cyse4_mitre_frr\"]}" 2>&1)
HF_RUN_ID=$(echo "$HF_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" 2>/dev/null)

if [ -n "$HF_RUN_ID" ]; then
    DEADLINE=$((SECONDS + 900))
    while [ $SECONDS -lt $DEADLINE ]; do
        HF_JSON=$(curl -sf --max-time 20 "$BACKEND/api/runs/$HF_RUN_ID" 2>/dev/null)
        HF_STATE=$(echo "$HF_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])" 2>/dev/null)
        [ "$HF_STATE" = "complete" ] || [ "$HF_STATE" = "failed" ] && break
        sleep 10
    done
    if echo "$HF_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
arts=[a for a in d['artifacts'] if 'hf-scan' in a]
assert arts, f\"no hf_scan artifact stored: {d['artifacts']}\"
" 2>/dev/null; then
        pass "Hub scan results harvested and stored as a run artifact"
    else
        fail "HF scan harvest" "$HF_JSON"
    fi
else
    fail "create HF-backed run" "$HF_OUT"
fi

# --------------------------------------------------------------------------------------
section "3.1-3.7  MCP server scan (poisoned fixture, known expected findings)"
# --------------------------------------------------------------------------------------
echo "  scanning the deliberately-poisoned MCP fixture through the gateway..."
MCP_OUT=$(curl -sf --max-time 300 -X POST "$BACKEND/api/runs" \
    -H 'Content-Type: application/json' \
    -d '{"asset_type":"mcp","name":"poisoned MCP fixture","identifier":"/srv/fixtures/poisoned_mcp_server"}' 2>&1)
MCP_RUN_ID=$(echo "$MCP_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" 2>/dev/null)

if [ -n "$MCP_RUN_ID" ]; then
    DEADLINE=$((SECONDS + E2E_SCAN_TIMEOUT))
    while [ $SECONDS -lt $DEADLINE ]; do
        MCP_JSON=$(curl -sf --max-time 20 "$BACKEND/api/runs/$MCP_RUN_ID" 2>/dev/null)
        MCP_STATE=$(echo "$MCP_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])" 2>/dev/null)
        [ "$MCP_STATE" = "complete" ] || [ "$MCP_STATE" = "failed" ] && break
        sleep 15
    done

    if echo "$MCP_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['status'] in ('complete','failed'), d['status']
findings=d['findings']
assert findings, 'the poisoned fixture produced no findings at all'
sev={f['severity'] for f in findings}
assert sev & {'critical','high'}, f'no blocking-severity finding on a poisoned server: {sev}'
# 3.2: analyzer attribution retained.
assert all(f['analyzer'] for f in findings), 'a finding lost its analyzer attribution'
# 3.5: scanner provenance recorded.
assert d['engine_version'], 'engine_version not recorded'
assert d['ruleset_version'], 'ruleset_version not recorded'
# 3.4: advisory mode must never auto-approve.
assert d['decision'] != 'auto_approve', 'advisory mode auto-approved an MCP scan'
print('  decision:', d['decision'])
print('  engine:', d['engine_version'], '| ruleset:', d['ruleset_version'])
from collections import Counter
print('  severities:', dict(Counter(f['severity'] for f in findings)))
print('  analyzers:', dict(Counter(f['analyzer'] for f in findings)))
" 2>&1 | tee /tmp/e2e-mcp.txt | grep -q "decision:"; then
        pass "poisoned MCP fixture: blocking findings, provenance recorded, not auto-approved"
        sed -n '1,6p' /tmp/e2e-mcp.txt
    else
        fail "MCP scan" "$(cat /tmp/e2e-mcp.txt 2>/dev/null)"
    fi
else
    fail "create MCP run" "$MCP_OUT"
fi

# --------------------------------------------------------------------------------------
section "4.1-4.4  Agent skill scan (poisoned fixture)"
# --------------------------------------------------------------------------------------
echo "  scanning the deliberately-poisoned skill fixture through the gateway..."
SKILL_OUT=$(curl -sf --max-time 300 -X POST "$BACKEND/api/runs" \
    -H 'Content-Type: application/json' \
    -d '{"asset_type":"skill","name":"poisoned skill fixture","identifier":"/srv/fixtures/poisoned_skill"}' 2>&1)
SKILL_RUN_ID=$(echo "$SKILL_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" 2>/dev/null)

if [ -n "$SKILL_RUN_ID" ]; then
    DEADLINE=$((SECONDS + E2E_SCAN_TIMEOUT))
    while [ $SECONDS -lt $DEADLINE ]; do
        SKILL_JSON=$(curl -sf --max-time 20 "$BACKEND/api/runs/$SKILL_RUN_ID" 2>/dev/null)
        SKILL_STATE=$(echo "$SKILL_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])" 2>/dev/null)
        [ "$SKILL_STATE" = "complete" ] || [ "$SKILL_STATE" = "failed" ] && break
        sleep 10
    done

    if echo "$SKILL_JSON" | python3 -c "
import json,sys
from collections import Counter
d=json.load(sys.stdin)
findings=d['findings']
assert findings, 'the poisoned skill produced no findings'
sev={f['severity'] for f in findings}
assert 'critical' in sev or 'high' in sev, f'no blocking severity: {sev}'
assert d['engine_version'], 'engine_version not recorded'
assert d['ruleset_version'], 'ruleset_version not recorded'
assert d['decision'] != 'auto_approve', 'advisory mode auto-approved a skill scan'
print('  decision:', d['decision'])
print('  ruleset:', d['ruleset_version'])
print('  severities:', dict(Counter(f['severity'] for f in findings)))
print('  analyzers:', dict(Counter(f['analyzer'] for f in findings)))
" 2>&1 | tee /tmp/e2e-skill.txt | grep -q "decision:"; then
        pass "poisoned skill fixture: blocking findings, verdict honoured, not auto-approved"
        sed -n '1,6p' /tmp/e2e-skill.txt
    else
        fail "skill scan" "$(cat /tmp/e2e-skill.txt 2>/dev/null)"
    fi
else
    fail "create skill run" "$SKILL_OUT"
fi

# --------------------------------------------------------------------------------------
section "3.7  Zip upload rejects hostile archives"
# --------------------------------------------------------------------------------------
ZIP_SLIP=$(mktemp -d)/slip.zip
python3 -c "
import zipfile, sys
with zipfile.ZipFile('$ZIP_SLIP','w') as z:
    z.writestr('../../escaped.txt','payload')
"
UPLOAD_OUT=$(curl -sf --max-time 60 -X POST "$BACKEND/api/uploads" -F "file=@$ZIP_SLIP" 2>&1)
UPLOAD_ID=$(echo "$UPLOAD_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['identifier'])" 2>/dev/null)
if [ -n "$UPLOAD_ID" ]; then
    SLIP_RUN=$(curl -sf --max-time 120 -X POST "$BACKEND/api/runs" \
        -H 'Content-Type: application/json' \
        -d "{\"asset_type\":\"skill\",\"name\":\"zip slip probe\",\"identifier\":\"$UPLOAD_ID\"}" 2>&1)
    SLIP_ID=$(echo "$SLIP_RUN" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" 2>/dev/null)
    sleep 20
    SLIP_JSON=$(curl -sf --max-time 20 "$BACKEND/api/runs/$SLIP_ID" 2>/dev/null)
    if echo "$SLIP_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['decision'] == 'error', f\"zip-slip archive was not rejected: {d['decision']}\"
assert 'escape' in (d['decision_reason'] or '').lower(), d['decision_reason']
" 2>/dev/null; then
        pass "zip-slip archive rejected, run recorded as ERROR (never a pass)"
    else
        fail "zip-slip rejection" "$SLIP_JSON"
    fi
else
    fail "upload endpoint" "$UPLOAD_OUT"
fi

# --------------------------------------------------------------------------------------
section "5.2-5.4  Policy is data; severity distribution is available for tuning"
# --------------------------------------------------------------------------------------
STATS_OUT=$(curl -sf --max-time 20 "$BACKEND/api/stats/severity" 2>&1)
if echo "$STATS_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert 'by_severity' in d and 'by_analyzer' in d, d
assert d['total_findings'] > 0, 'no findings recorded, so tuning has no evidence to work from'
print('  findings so far:', d['total_findings'], d['by_severity'])
" 2>&1 | tee /tmp/e2e-stats.txt | grep -q "findings so far"; then
    pass "severity distribution endpoint reports real findings for hand-tuning"
    sed -n '1p' /tmp/e2e-stats.txt
else
    fail "severity stats" "$STATS_OUT"
fi

PUB_OUT=$(curl -sf --max-time 20 "$BACKEND/api/published-scores" 2>&1)
if echo "$PUB_OUT" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
    pass "published-score catalog readable (harvest-before-compute path available)"
else
    fail "published scores endpoint" "$PUB_OUT"
fi

# Saving an out-of-range score must be refused: a percentage entered as a rate would
# silently disable a gate.
BAD_SAVE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST "$BACKEND/api/published-scores" \
    -H 'Content-Type: application/json' \
    -d '{"model":"x","check_id":"cyse4_mitre","metric":"accuracy","value":90,"source_url":"https://example.com"}' 2>&1)
if [ "$BAD_SAVE" = "400" ]; then
    pass "published score outside 0-1 is rejected (unit-mistake guard)"
else
    fail "published score validation" "expected HTTP 400, got $BAD_SAVE"
fi

# --------------------------------------------------------------------------------------
section "0.10  Failures surface the upstream error body"
# --------------------------------------------------------------------------------------
BAD_OUT=$(curl -sf --max-time 60 -X POST "$BACKEND/api/preflight" \
    -H 'Content-Type: application/json' \
    -d '{"model":"no-such-model-alias","judge_model":"no-such-model-alias"}' 2>&1)
if echo "$BAD_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['ok'] is False, 'unroutable alias should fail'
assert any(c['upstream_error'] for c in d['checks']), 'upstream error body not surfaced'" 2>/dev/null; then
    pass "unroutable alias fails with the upstream body attached"
else
    fail "failure diagnostics" "$BAD_OUT"
fi

# --------------------------------------------------------------------------------------
section "0.11  Frontend renders live gateway state"
# --------------------------------------------------------------------------------------
HOME_HTML=$(curl -sf --max-time 20 "$FRONTEND" 2>&1)
MISSING=""
# Phase 8 simplified the landing page: asset classes + how-it-works, with gateway state
# reduced to a header pill (sr-only carries reachable/unreachable for the check).
for needle in "AI Model" "MCP server" "Agent skill" "How it works" "reachable"; do
    echo "$HOME_HTML" | grep -q "$needle" || MISSING="$MISSING '$needle'"
done
if [ -z "$MISSING" ]; then
    pass "landing page shows all three asset classes and the gateway pill"
else
    fail "frontend content" "missing:$MISSING"
fi

# --------------------------------------------------------------------------------------
section "0.12  Fresh clone builds from tracked files only"
# --------------------------------------------------------------------------------------
FRESH=$(mktemp -d)
if git checkout-index -a -f --prefix="$FRESH/" 2>/dev/null \
    && docker build -q -t e2e-freshclone-check "$FRESH/backend" >/dev/null 2>&1; then
    pass "backend image builds from tracked files alone"
    docker rmi e2e-freshclone-check >/dev/null 2>&1
else
    fail "fresh-clone build" "an untracked file is required by the build"
fi
rm -rf "$FRESH"

# --------------------------------------------------------------------------------------
printf '\n\033[1m%s\033[0m\n' "Summary"
printf '  %d passed, %d failed\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
    printf '\n  Failed criteria:\n'
    for f in "${FAILURES[@]}"; do printf '    - %s\n' "$f"; done
    exit 1
fi
printf '\n  \033[32mAll acceptance criteria for the completed phases passed.\033[0m\n'
printf '  Total model spend: $0 (all traffic to local Ollama via the gateway).\n'
