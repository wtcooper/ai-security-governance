"""Zip upload for MCP servers and skills that are not in a git repository."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.engines.source import MAX_ARCHIVE_BYTES

router = APIRouter(tags=["uploads"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


class UploadResponse(BaseModel):
    # Pass this back as a run's `identifier`. It is a server-side path, never a client-chosen
    # one, so a submission cannot name a location outside the upload directory.
    identifier: str
    filename: str
    size_bytes: int


@router.post("/uploads", response_model=UploadResponse, status_code=201)
async def upload_archive(
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="Zip archive of the MCP server or skill")],
) -> UploadResponse:
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="only .zip archives are accepted")

    uploads = settings.workspace_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    # The stored name is derived from a counter, not from the client's filename: a filename is
    # attacker-controlled and must never determine a write path.
    index = len(list(uploads.glob("upload-*.zip"))) + 1
    destination = uploads / f"upload-{index}.zip"

    written = 0
    with destination.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_ARCHIVE_BYTES:
                handle.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"archive exceeds the {MAX_ARCHIVE_BYTES / 1e6:.0f} MB limit "
                        "(checked while streaming, so an oversized upload is not buffered)"
                    ),
                )
            handle.write(chunk)

    return UploadResponse(
        identifier=str(destination), filename=file.filename or destination.name, size_bytes=written
    )
