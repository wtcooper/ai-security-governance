"""Talking to the configured OpenAI-compatible gateway.

This module is the only place that knows how to reach a model over HTTP, and it only ever
uses the two things we require of any endpoint: a base URL and a bearer key.

`preflight` exists because the historical failure mode here was discovering a broken model
route halfway through an expensive eval. Every run is gated on a real round-trip first, and
failures return the upstream error body verbatim rather than a sanitised summary — when a
gateway rejects a model you need to see exactly what it said.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import Settings


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    detail: str
    model: str | None = None
    latency_ms: int | None = None
    # Verbatim upstream body on failure; None on success.
    upstream_error: str | None = None


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.gateway_api_key}",
        "Content-Type": "application/json",
    }


async def list_models(settings: Settings) -> list[str]:
    """Gateway aliases, for the submit-form dropdown.

    The UI offers only these. A user cannot type a provider-native model string into a run,
    which is what keeps the "no direct provider assumptions" rule true at the edges.
    """
    url = f"{settings.gateway_base_url.rstrip('/')}/models"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, headers=_headers(settings))
        response.raise_for_status()
        payload = response.json()
    aliases = [entry["id"] for entry in payload.get("data", []) if entry.get("id")]
    return sorted(aliases)


async def readiness(settings: Settings) -> tuple[bool, str]:
    """Gateway process health, independent of any particular model route."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(settings.gateway_health_url)
        return response.is_success, f"HTTP {response.status_code}: {response.text[:400]}"
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def preflight(settings: Settings, model: str, timeout: float = 120.0) -> PreflightResult:
    """Perform a real chat completion so a run never starts against a broken route."""
    url = f"{settings.gateway_base_url.rstrip('/')}/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
        "max_tokens": 16,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=_headers(settings), json=body)
    except httpx.HTTPError as exc:
        return PreflightResult(
            ok=False,
            detail=f"Could not reach the gateway at {settings.gateway_base_url}",
            model=model,
            upstream_error=f"{type(exc).__name__}: {exc}",
        )

    latency_ms = int(response.elapsed.total_seconds() * 1000)

    if not response.is_success:
        return PreflightResult(
            ok=False,
            detail=f"Gateway rejected model {model!r} with HTTP {response.status_code}",
            model=model,
            latency_ms=latency_ms,
            upstream_error=response.text[:4000],
        )

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        return PreflightResult(
            ok=False,
            detail=f"Gateway returned a non-OpenAI-shaped response for {model!r}",
            model=model,
            latency_ms=latency_ms,
            upstream_error=f"{type(exc).__name__}: {exc}; body={response.text[:2000]}",
        )

    return PreflightResult(
        ok=True,
        detail=f"Model {model!r} responded: {str(content).strip()[:120]!r}",
        model=model,
        latency_ms=latency_ms,
    )
