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
