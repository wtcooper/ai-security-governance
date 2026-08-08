"""Gateway health and model discovery."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.engines import gateway

router = APIRouter(tags=["gateway"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


class PreflightRequest(BaseModel):
    model: str
    # Judge routing is the more common breakage (task defaults point at provider-native
    # models), so it gets checked in the same round trip.
    judge_model: str | None = None


class PreflightCheck(BaseModel):
    role: str
    model: str
    ok: bool
    detail: str
    latency_ms: int | None = None
    upstream_error: str | None = None


class PreflightResponse(BaseModel):
    ok: bool
    base_url: str
    checks: list[PreflightCheck]


class GatewayStatus(BaseModel):
    ok: bool
    base_url: str
    detail: str


@router.get("/gateway/status", response_model=GatewayStatus)
async def gateway_status(settings: SettingsDep) -> GatewayStatus:
    ok, detail = await gateway.readiness(settings)
    return GatewayStatus(ok=ok, base_url=settings.gateway_base_url, detail=detail)


@router.get("/models", response_model=list[str])
async def models(settings: SettingsDep) -> list[str]:
    """Gateway aliases available to submit. The UI renders these as a dropdown."""
    try:
        return await gateway.list_models(settings)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Could not list models from {settings.gateway_base_url}: {exc}. "
                "Is the gateway running?"
            ),
        ) from exc


@router.post("/preflight", response_model=PreflightResponse)
async def run_preflight(request: PreflightRequest, settings: SettingsDep) -> PreflightResponse:
    """Prove subject and judge routing with real completions before spending on a run."""
    targets = [("subject", request.model)]
    judge = request.judge_model or settings.default_judge_model
    if judge != request.model:
        targets.append(("judge", judge))

    checks: list[PreflightCheck] = []
    for role, alias in targets:
        result = await gateway.preflight(settings, alias)
        checks.append(
            PreflightCheck(
                role=role,
                model=alias,
                ok=result.ok,
                detail=result.detail,
                latency_ms=result.latency_ms,
                upstream_error=result.upstream_error,
            )
        )

    return PreflightResponse(
        ok=all(check.ok for check in checks),
        base_url=settings.gateway_base_url,
        checks=checks,
    )
