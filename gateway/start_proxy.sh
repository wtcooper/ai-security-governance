#!/usr/bin/env bash
# Start the bundled LiteLLM gateway on port 4000.
#
# Works both inside the compose container and on the host for local debugging.
# The working directory is set to the gateway dir so `mock_handlers` resolves as a
# top-level module for custom_provider_map.
#
# Usage:
#   bash gateway/start_proxy.sh          # foreground
#   bash gateway/start_proxy.sh &        # background
set -euo pipefail

GATEWAY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$GATEWAY_DIR/.." && pwd)"
cd "$GATEWAY_DIR"

# Load provider keys from the repo root .env / .env.local (.local wins). In compose these
# arrive as real environment variables instead, and this loop is a no-op.
set -a
for f in "$REPO_ROOT/.env" "$REPO_ROOT/.env.local"; do
    # shellcheck disable=SC1090
    [ -f "$f" ] && . "$f"
done
set +a

# The gateway's own bearer token. Defaults to the local dev value; override in deployment.
export GATEWAY_API_KEY="${GATEWAY_API_KEY:-sk-local}"
# Where Ollama lives. Host by default; the compose local-models profile overrides this.
export OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://localhost:11434}"
# 4001 on the host, not 4000: LiteLLM's conventional port is commonly already taken by
# another project's gateway, and silently colliding with one is worse than picking a
# neighbouring port. In compose the container still listens on 4000 internally.
GATEWAY_PORT="${GATEWAY_PORT:-4001}"

# The gateway needs litellm[proxy], which cannot share a venv with inspect-ai (boto3
# conflict). On the host that means a dedicated .venv-gateway; in the container litellm is
# already on PATH.
LITELLM_BIN="litellm"
if [ -x "$REPO_ROOT/.venv-gateway/bin/litellm" ]; then
    LITELLM_BIN="$REPO_ROOT/.venv-gateway/bin/litellm"
fi

exec "$LITELLM_BIN" \
    --config "$GATEWAY_DIR/litellm_config.yaml" \
    --port "$GATEWAY_PORT" \
    --num_workers 1
