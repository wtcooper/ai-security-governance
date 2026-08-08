#!/usr/bin/env bash
# Measure our detection against the vendor eval corpora.
#
# Clones the labelled corpora from the Cisco scanner repos (they ship in the GitHub repos, not
# the PyPI packages) and runs OUR pipeline over them — our scanner invocation, our parsing,
# our severity mapping, our policy gate. We are not grading the scanners; we are grading the
# whole path, because a scanner finding we fail to parse is a miss for governance purposes.
#
# All analyzer traffic goes to the local gateway model, so a run costs $0.
#
# Usage:
#   scripts/calibrate.sh                 # 1 malicious MCP sample per category + all skills
#   scripts/calibrate.sh --full          # all 141 MCP samples (slow: a model call per file)
#   scripts/calibrate.sh --skill-only    # skills only (fast)
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/backend"

PER_CATEGORY=1
CORPUS_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --full) PER_CATEGORY=0 ;;                       # 0 means the whole corpus
        --skill-only) CORPUS_ARGS+=(--corpus skill) ;;
        --mcp-only) CORPUS_ARGS+=(--corpus mcp) ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

export GATEWAY_BASE_URL="${GATEWAY_BASE_URL:-http://localhost:4001/v1}"
export GATEWAY_API_KEY="${GATEWAY_API_KEY:-sk-local}"

if ! curl -sf --max-time 5 "${GATEWAY_BASE_URL%/v1}/health/readiness" >/dev/null 2>&1; then
    echo "Gateway not reachable at $GATEWAY_BASE_URL"
    echo "Start it with:  docker compose up -d gateway   (or bash gateway/start_proxy.sh)"
    exit 1
fi

OUT="${OUT:-$REPO_ROOT/data/calibration/calibration-$(date +%Y%m%d-%H%M%S).json}"
mkdir -p "$(dirname "$OUT")"

echo "Running calibration (analyzer model via $GATEWAY_BASE_URL, \$0 spend)..."
echo "The malicious MCP corpus is sampled unless --full is passed; the sample size is"
echo "recorded in the report so a sampled run is never mistaken for a full one."
echo

uv run python -m app.engines.calibration \
    --mcp-per-category "$PER_CATEGORY" \
    "${CORPUS_ARGS[@]}" \
    --out "$OUT"
