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
expected={'cyse4_multilingual_prompt_injection','cyse4_mitre','cyse4_mitre_frr',
          'cyse4_instruct','agentdojo'}
assert set(checks)==expected, f'registry drift: {set(checks) ^ expected}'
# Both judged checks must advertise that they need one, or an upstream default takes over.
assert checks['cyse4_mitre']['needs_judge']
assert checks['cyse4_multilingual_prompt_injection']['needs_judge']
# Directions must not have collapsed to one value (a classic copy-paste error).
assert len({c['direction'] for c in checks.values()})==2
" 2>/dev/null; then
    pass "5 benchmarks registered with judge requirements and mixed directions"
else
    fail "check registry" "$CHECKS_OUT"
fi

POLICY_OUT=$(curl -sf --max-time 15 "$BACKEND/api/policy" 2>&1)
if echo "$POLICY_OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['content_hash'], 'policy must be content-hashed'
assert d['composite_is_display_only'] is True
assert len(d['llm_gates'])==5, d['llm_gates']
assert d['thresholds_are_calibrated'] is False, 'placeholders must be labelled as such'
" 2>/dev/null; then
    pass "policy exposes 5 gates, content hash, and honest calibration status"
else
    fail "policy endpoint" "$POLICY_OUT"
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
gates=d['gate_outcomes']
assert len(gates)==5, f'expected 5 gate outcomes, got {len(gates)}'
scored=[g for g in gates if g['raw_value'] is not None]
assert len(scored)==5, f'benchmarks without a score: {[g[\"check_id\"] for g in gates if g[\"raw_value\"] is None]}'
assert d['decision'] in ('auto_approve','needs_deep_testing','error'), d['decision']
# Criterion 1.9: provenance fields must be populated on the run.
assert d['judge_model'], 'judge model not recorded'
assert d['policy_hash'], 'policy hash not recorded'
# Criterion 1.4: ungated extras recorded but never turned into gates.
extras=[s for s in d['scores'] if not s['gated']]
assert extras, 'no ungated metrics captured - extras should be stored for inspection'
assert all(s['threshold'] is None for s in extras), 'an ungated metric was given a threshold'
# Criterion 1.5: composite present but flagged display-only.
assert d['composite_is_display_only'] is True
print('  decision:', d['decision'])
print('  composite (display only):', d['composite_score'])
for g in gates:
    print(f\"    {'pass' if g['passed'] else 'FAIL'}  {g['check_id']}: {g['reason']}\")
" 2>&1 | tee /tmp/e2e-run-detail.txt | grep -q "decision:"; then
        pass "all 5 benchmarks scored, decision emitted, extras ungated"
        sed -n '2,20p' /tmp/e2e-run-detail.txt
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
        pass "leaderboard reports the run with a 5-gate denominator"
    else
        fail "leaderboard" "$LB_OUT"
    fi
else
    fail "create run" "$RUN_CREATE"
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
for needle in "Foundation model" "MCP server" "Agent skill" "reachable" "$SUBJECT_MODEL"; do
    echo "$HOME_HTML" | grep -q "$needle" || MISSING="$MISSING '$needle'"
done
if [ -z "$MISSING" ]; then
    pass "landing page shows all three asset classes and live gateway state"
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
