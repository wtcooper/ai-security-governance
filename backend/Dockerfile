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
# Deliberately-malicious fixtures used by the acceptance suite to prove the scanners detect
# what they claim to. Never executed — the scanners read source. They ship in the image so a
# deployment can verify its own detection without network access to a sample repo.
COPY tests/fixtures ./fixtures

ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/srv/data \
    POLICY_PATH=/srv/policy/policy.yaml \
    # Must match the COPY above. This is also one of the two roots a non-URL submission is
    # allowed to point at, so a wrong value here would make the fixtures unscannable rather
    # than merely misplaced.
    FIXTURES_DIR=/srv/fixtures

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
