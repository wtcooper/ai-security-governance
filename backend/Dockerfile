# Backend: FastAPI + all compute engines in one venv.
#
# Inspect AI, inspect-evals, mcp-scanner and skill-scanner coexist here — verified by
# tests/test_engine_coexistence.py. Only litellm[proxy] has to live elsewhere (it needs
# boto3>=1.43.1, which inspect-ai's aioboto3 dependency caps below), which is why the
# gateway is a separate image.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# git: cloning submitted MCP/skill repos for static analysis.
# libmagic1: file-type detection used by the scanners.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Dependency layer first so app edits do not trigger a full reinstall.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY policy ./policy
COPY catalog ./catalog

ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/srv/data \
    POLICY_PATH=/srv/policy/policy.yaml

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
