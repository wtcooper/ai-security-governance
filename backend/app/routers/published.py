"""Ingesting published benchmark scores from a vendor system card.

"Harvest before compute" only pays off if getting a published number into the catalog is
easy. There is no machine-readable source for these, so this is a two-step flow:

    POST /api/published-scores/extract   -> LLM reads a URL, proposes candidates
    POST /api/published-scores           -> a human confirms, and only then is it saved

The confirmation step is not ceremony. An extracted number that lands unreviewed in a
governance record could auto-approve a model that was never measured, and the extraction is
being done by a model reading prose. So the endpoint proposes; a person decides.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.engines import safe_fetch
from app.engines.harvest_catalog import load_catalog
from app.engines.registry import LLM_CHECKS

router = APIRouter(tags=["published-scores"])

SettingsDep = Annotated[Settings, Depends(get_settings)]

EXTRACTION_PROMPT = """You are reading a vendor model card or paper to find published
CYBERSECURITY benchmark results.

Only report a number if the document states it explicitly. Do NOT estimate, infer, or
convert between different benchmarks. If nothing relevant is present, return an empty list.

Benchmarks of interest (use these exact check_id values):
{checks}

Return ONLY valid JSON of this shape, with no commentary:
{{"candidates": [
  {{"model": "<model name as written>",
   "check_id": "<one of the check_ids above>",
   "metric": "<metric name>",
   "value": <number as a 0-1 rate; divide by 100 if the document gives a percentage>,
   "quote": "<the exact sentence you took it from>"}}
]}}

Document:
---
{document}
---"""


class ExtractRequest(BaseModel):
    url: str
    model: str | None = Field(default=None, description="Gateway alias to do the extraction")


class Candidate(BaseModel):
    model: str
    check_id: str
    metric: str
    value: float
    quote: str | None = None
    # False when the check_id is not one we gate on, or the value is out of range. Surfaced
    # rather than silently dropped so a reviewer can see what the model tried to claim.
    valid: bool = True
    problem: str | None = None


class ExtractResponse(BaseModel):
    url: str
    extraction_model: str
    candidates: list[Candidate]
    note: str


class SaveRequest(BaseModel):
    model: str
    check_id: str
    metric: str
    value: float
    source_url: str
    captured: str | None = None
    note: str | None = None


@router.get("/published-scores")
def list_published(settings: SettingsDep) -> list[dict[str, Any]]:
    catalog = _catalog_path(settings)
    return [
        {
            "model": entry.model,
            "check_id": entry.check_id,
            "metric": entry.metric,
            "value": entry.value,
            "source_url": entry.source_url,
            "captured": entry.captured,
            "note": entry.note,
        }
        for entry in load_catalog(catalog)
    ]


@router.post("/published-scores/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest, settings: SettingsDep) -> ExtractResponse:
    model = request.model or settings.scanner_model

    # Validated and fetched through safe_fetch: the URL comes from the client, so an
    # unguarded server-side GET would let this endpoint reach instance metadata, the model
    # gateway, or this API itself.
    try:
        page_text = await safe_fetch.fetch_text(request.url)
    except safe_fetch.UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"could not fetch {request.url}: {exc}") from exc

    document = _to_text(page_text)[:24_000]
    prompt = EXTRACTION_PROMPT.format(
        checks="\n".join(f"- {c.id} (metric: {c.metric_name})" for c in LLM_CHECKS),
        document=document,
    )

    try:
        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(
                f"{settings.gateway_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.gateway_api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise HTTPException(status_code=502, detail=f"extraction call failed: {exc}") from exc

    candidates = [_validate(item) for item in _parse_candidates(content)]

    return ExtractResponse(
        url=request.url,
        extraction_model=model,
        candidates=candidates,
        note=(
            "Nothing here is saved yet. These are proposals from a model reading prose — "
            "confirm each against the quoted sentence before POSTing it to "
            "/api/published-scores."
        ),
    )


@router.post("/published-scores", status_code=201)
def save_published(request: SaveRequest, settings: SettingsDep) -> dict[str, Any]:
    known = {check.id for check in LLM_CHECKS}
    if request.check_id not in known:
        raise HTTPException(
            status_code=400,
            detail=f"unknown check_id {request.check_id!r}; known: {sorted(known)}",
        )
    if not 0.0 <= request.value <= 1.0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"value {request.value} is outside 0-1. Scores are stored as rates; divide a "
                "percentage by 100 before saving."
            ),
        )

    catalog = _catalog_path(settings)
    data = yaml.safe_load(catalog.read_text()) if catalog.exists() else {}
    data = data or {}
    scores = data.get("scores") or []
    scores.append(
        {
            "model": request.model,
            "check_id": request.check_id,
            "metric": request.metric,
            "value": request.value,
            "source_url": request.source_url,
            "captured": request.captured,
            "note": request.note,
        }
    )
    data["scores"] = scores
    catalog.write_text(yaml.safe_dump(data, sort_keys=False))
    load_catalog.cache_clear()
    return {"saved": True, "total_entries": len(scores)}


def _catalog_path(settings: Settings):
    return settings.policy_path.parent.parent / "catalog" / "published_scores.yaml"


def _to_text(html: str) -> str:
    """Crude tag stripping. Good enough to feed a model, and avoids another dependency."""
    import re

    without_scripts = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", without_scripts)
    return re.sub(r"\s+", " ", text).strip()


def _parse_candidates(content: str) -> list[dict[str, Any]]:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        return json.loads(content[start : end + 1]).get("candidates") or []
    except (json.JSONDecodeError, AttributeError):
        return []


def _validate(item: dict[str, Any]) -> Candidate:
    known = {check.id for check in LLM_CHECKS}
    problems = []
    check_id = str(item.get("check_id", ""))
    if check_id not in known:
        problems.append(f"check_id {check_id!r} is not a gated benchmark")
    try:
        value = float(item.get("value"))
    except (TypeError, ValueError):
        value = -1.0
        problems.append("value is not a number")
    if not 0.0 <= value <= 1.0:
        problems.append(f"value {value} is outside 0-1")

    return Candidate(
        model=str(item.get("model", "")),
        check_id=check_id,
        metric=str(item.get("metric", "")),
        value=value,
        quote=item.get("quote"),
        valid=not problems,
        problem="; ".join(problems) or None,
    )
