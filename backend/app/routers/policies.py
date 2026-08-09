"""Versioned per-asset-class policies.

Versions are immutable: this router exposes list / read / create, and nothing else. There
is no update or delete, because a policy version that governed a recorded decision must
stay resolvable forever. "Editing" a policy means creating the next version; the newest
version is the one applied to new runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.models import AssetType
from app.scoring import policy as policy_store
from app.scoring import policy_form
from app.scoring.policy import PolicyValidationError

router = APIRouter(tags=["policies"])

SessionDep = Annotated[Session, Depends(get_session)]


class PolicyVersionMeta(BaseModel):
    asset_type: AssetType
    version: int
    content_hash: str
    note: str | None
    created_at: datetime
    is_active: bool


class PolicyVersionOut(PolicyVersionMeta):
    content: str


class CreateVersionRequest(BaseModel):
    content: str
    # Why this version exists. Optional but strongly encouraged — it is the only prose a
    # future reader gets next to a diff.
    note: str | None = None


@router.get("/policies", response_model=dict[str, PolicyVersionMeta])
def active_policies(session: SessionDep) -> dict[str, PolicyVersionMeta]:
    """The newest — i.e. governing — version of each asset class's policy."""
    out: dict[str, PolicyVersionMeta] = {}
    for asset_type in AssetType:
        row = policy_store.newest_version(session, asset_type)
        if row is None:
            raise HTTPException(status_code=503, detail="policies are not seeded yet")
        out[asset_type.value] = PolicyVersionMeta(
            asset_type=asset_type,
            version=row.version,
            content_hash=row.content_hash,
            note=row.note,
            created_at=row.created_at,
            is_active=True,
        )
    return out


@router.get("/policies/{asset_type}/versions", response_model=list[PolicyVersionMeta])
def list_versions(asset_type: AssetType, session: SessionDep) -> list[PolicyVersionMeta]:
    rows = policy_store.list_versions(session, asset_type)
    return [
        PolicyVersionMeta(
            asset_type=asset_type,
            version=row.version,
            content_hash=row.content_hash,
            note=row.note,
            created_at=row.created_at,
            is_active=(index == 0),
        )
        for index, row in enumerate(rows)
    ]


@router.get("/policies/{asset_type}/versions/{version}", response_model=PolicyVersionOut)
def get_version(asset_type: AssetType, version: int, session: SessionDep) -> PolicyVersionOut:
    row = policy_store.get_version(session, asset_type, version)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"no {asset_type.value} policy version {version}"
        )
    newest = policy_store.newest_version(session, asset_type)
    return PolicyVersionOut(
        asset_type=asset_type,
        version=row.version,
        content_hash=row.content_hash,
        note=row.note,
        created_at=row.created_at,
        is_active=(newest is not None and newest.version == row.version),
        content=row.content,
    )


@router.post("/policies/{asset_type}/versions", response_model=PolicyVersionOut, status_code=201)
def create_version(
    asset_type: AssetType, request: CreateVersionRequest, session: SessionDep
) -> PolicyVersionOut:
    """Validate and save the next version. Invalid content creates nothing."""
    try:
        row = policy_store.create_version(session, asset_type, request.content, request.note)
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PolicyVersionOut(
        asset_type=asset_type,
        version=row.version,
        content_hash=row.content_hash,
        note=row.note,
        created_at=row.created_at,
        is_active=True,
        content=row.content,
    )


@router.get("/policies/{asset_type}/form")
def form_values(
    asset_type: AssetType, session: SessionDep, version: int | None = None
) -> dict:
    """A version's key settings, shaped for the form editor.

    Defaults to the active version. Naming an older version renders its settings read-only,
    which is how a superseded policy stays inspectable now that there is no YAML view.
    """
    row = (
        policy_store.get_version(session, asset_type, version)
        if version is not None
        else policy_store.newest_version(session, asset_type)
    )
    if row is None:
        raise HTTPException(
            status_code=404 if version is not None else 503,
            detail=(
                f"no {asset_type.value} policy version {version}"
                if version is not None
                else "policies are not seeded yet"
            ),
        )
    return {
        "asset_type": asset_type.value,
        "version": row.version,
        "values": policy_form.current_form_values(asset_type, row.content),
    }


class LlmFormRequest(policy_form.LlmPolicyForm):
    note: str | None = None


class ScannerFormRequest(policy_form.ScannerPolicyForm):
    note: str | None = None


@router.post("/policies/llm/form", response_model=PolicyVersionOut, status_code=201)
def create_llm_version_from_form(
    request: LlmFormRequest, session: SessionDep
) -> PolicyVersionOut:
    """Apply a form edit to the active LLM policy and save it as the next version.

    The form updates the settings that are preferences (thresholds, sample counts, judge,
    weights); registry facts (metric, direction) and pinned core sets are not form fields.
    Comments in the document survive: the edit is a round-trip, not a regeneration.
    """
    return _create_from_form(session, AssetType.LLM, request)


@router.post("/policies/{asset_type}/form", response_model=PolicyVersionOut, status_code=201)
def create_scanner_version_from_form(
    asset_type: AssetType, request: ScannerFormRequest, session: SessionDep
) -> PolicyVersionOut:
    if asset_type is AssetType.LLM:
        # Routed above; reaching here means the payload did not match the LLM form.
        raise HTTPException(status_code=422, detail="LLM form payload malformed")
    return _create_from_form(session, asset_type, request)


def _create_from_form(session, asset_type: AssetType, request) -> PolicyVersionOut:
    current = policy_store.newest_version(session, asset_type)
    if current is None:
        raise HTTPException(status_code=503, detail="policies are not seeded yet")
    if asset_type is AssetType.LLM:
        content = policy_form.apply_llm_form(current.content, request)
    else:
        content = policy_form.apply_scanner_form(current.content, request)
    try:
        row = policy_store.create_version(session, asset_type, content, request.note)
    except PolicyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PolicyVersionOut(
        asset_type=asset_type,
        version=row.version,
        content_hash=row.content_hash,
        note=row.note,
        created_at=row.created_at,
        is_active=True,
        content=row.content,
    )
