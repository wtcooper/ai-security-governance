"""Zip upload for MCP servers and skills that are not in a git repository."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db import get_session
from app.engines.source import MAX_ARCHIVE_BYTES

router = APIRouter(tags=["uploads"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


def _count_source_files(archive) -> tuple[int, int]:
    """Count entries and scannable source files from the listing alone.

    Reading the central directory is cheap and touches no file contents, so this is safe to do
    on an untrusted archive: nothing is extracted and no member path is used as a path.
    """
    import zipfile

    from app.engines.mcp_scanner import SKIP_DIRS, SOURCE_SUFFIXES

    try:
        with zipfile.ZipFile(archive) as zf:
            names = [info.filename for info in zf.infolist() if not info.is_dir()]
    except (zipfile.BadZipFile, OSError):
        return 0, 0

    source = 0
    for name in names:
        parts = name.split("/")
        if SKIP_DIRS & set(parts):
            continue
        suffix = ("." + parts[-1].rsplit(".", 1)[-1].lower()) if "." in parts[-1] else ""
        if suffix in SOURCE_SUFFIXES:
            source += 1
    return len(names), source


class UploadResponse(BaseModel):
    # Pass this back as a run's `identifier`. It is a server-side path, never a client-chosen
    # one, so a submission cannot name a location outside the upload directory.
    identifier: str
    filename: str
    size_bytes: int
    # Counted from the archive listing without extracting anything, so the submitter learns the
    # size of what they just uploaded BEFORE a scan runs — and can be warned if it exceeds the
    # coverage setting rather than discovering the shortfall in the results.
    entry_count: int
    source_file_count: int
    # The policy's current coverage setting, and whether this upload exceeds it.
    max_source_files: int
    exceeds_coverage: bool


@router.post("/uploads", response_model=UploadResponse, status_code=201)
async def upload_archive(
    settings: SettingsDep,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="Zip archive of the MCP server or skill")],
    asset_type: str = "mcp",
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

    entries, source_files = _count_source_files(destination)

    from app.models import AssetType
    from app.scoring.policy import get_active_policy

    try:
        scanner = get_active_policy(session).scanner[AssetType(asset_type)]
        cap = scanner.max_source_files
    except Exception:  # noqa: BLE001 - an unseeded policy must not block an upload
        from app.engines.mcp_scanner import DEFAULT_MAX_SOURCE_FILES

        cap = DEFAULT_MAX_SOURCE_FILES

    return UploadResponse(
        identifier=str(destination),
        filename=file.filename or destination.name,
        size_bytes=written,
        entry_count=entries,
        source_file_count=source_files,
        max_source_files=cap,
        exceeds_coverage=source_files > cap,
    )
