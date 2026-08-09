"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db, session_scope
from app.routers import (
    benchmarks,
    evaluations,
    policies,
    policy,
    preflight,
    published,
    runs,
    selftest,
    uploads,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.jobs import close_orphaned_runs
    from app.scoring.policy import seed_policies

    init_db()
    with session_scope() as session:
        seed_policies(session, get_settings().policy_dir)
        close_orphaned_runs(session)
    yield


app = FastAPI(
    title="AI Security Governance",
    description=(
        "Security evaluation and governance thresholds for AI assets "
        "(foundation models, MCP servers, agent skills)."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Local-only for now; the frontend runs on a different port in dev and in compose.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(preflight.router, prefix="/api")
app.include_router(selftest.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(evaluations.router, prefix="/api")
app.include_router(policy.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(published.router, prefix="/api")
app.include_router(policies.router, prefix="/api")
app.include_router(benchmarks.router, prefix="/api")


@app.get("/api/health", tags=["health"])
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "gateway_base_url": settings.gateway_base_url,
        "default_judge_model": settings.default_judge_model,
    }
