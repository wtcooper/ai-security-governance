"""Acquiring submitted MCP server and skill source for static analysis.

This module handles untrusted input, so it is deliberately conservative:

* `git clone --depth 1 --no-single-branch=false`, no submodules, no hooks, no build step.
  We never run anything from the repository — only read it.
* Zip extraction validates every member path before writing, because a crafted archive can
  otherwise escape the destination directory ("zip slip") and overwrite files elsewhere.
* Size and file-count caps, so one submission cannot fill the disk.

A security governance tool that could be compromised by the artifacts it inspects would be
worse than no tool at all.
"""

from __future__ import annotations

import asyncio
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024  # 100 MB compressed
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # guards zip bombs
MAX_MEMBERS = 20_000

ALLOWED_GIT_HOSTS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "codeberg.org",
}


class SourceError(Exception):
    """Raised when a submission cannot be safely acquired."""


@dataclass(frozen=True)
class AcquiredSource:
    path: Path
    kind: str  # "git" | "zip"
    origin: str
    revision: str | None = None


def validate_repo_url(url: str) -> str:
    """Accept only https URLs on known forges.

    Refusing `git://`, `ssh://` and `file://` keeps a submission from reaching the local
    filesystem or an arbitrary port, and refusing unknown hosts keeps clone traffic
    predictable. Loosen the host list if your org self-hosts.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SourceError(f"repository URL must be https, got {parsed.scheme or 'no scheme'!r}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_GIT_HOSTS:
        raise SourceError(
            f"host {host!r} is not an allowed source forge. Allowed: "
            f"{', '.join(sorted(ALLOWED_GIT_HOSTS))}"
        )
    if not parsed.path.strip("/"):
        raise SourceError("repository URL has no path")
    return url


async def clone_repo(url: str, destination: Path, timeout: float = 300.0) -> AcquiredSource:
    """Shallow-clone a repository for read-only analysis."""
    validate_repo_url(url)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "src"
    if target.exists():
        shutil.rmtree(target)

    process = await asyncio.create_subprocess_exec(
        "git",
        "-c",
        "core.hooksPath=/dev/null",  # a cloned repo must never execute its own hooks
        "clone",
        "--depth",
        "1",
        "--no-tags",
        "--recurse-submodules=no",
        url,
        str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise SourceError(f"clone of {url} timed out after {timeout:.0f}s") from None

    if process.returncode != 0:
        raise SourceError(f"git clone failed: {stderr.decode()[-500:]}")

    revision = await _head_revision(target)
    return AcquiredSource(path=target, kind="git", origin=url, revision=revision)


async def _head_revision(repo: Path) -> str | None:
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        "rev-parse",
        "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    revision = stdout.decode().strip()
    return revision or None


def _is_safe_member(name: str) -> bool:
    """Reject absolute paths and any traversal outside the destination."""
    if name.startswith("/") or name.startswith("\\"):
        return False
    parts = Path(name).parts
    return ".." not in parts and not any(part.startswith("/") for part in parts)


def extract_zip(archive: Path, destination: Path) -> AcquiredSource:
    """Extract a zip safely: no traversal, no symlinks, no bombs."""
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise SourceError(
            f"archive is {archive.stat().st_size / 1e6:.0f} MB, over the "
            f"{MAX_ARCHIVE_BYTES / 1e6:.0f} MB limit"
        )

    target = destination / "src"
    target.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if len(members) > MAX_MEMBERS:
            raise SourceError(f"archive has {len(members)} members, over the {MAX_MEMBERS} limit")

        total = sum(m.file_size for m in members)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise SourceError(
                f"archive expands to {total / 1e6:.0f} MB, over the "
                f"{MAX_UNCOMPRESSED_BYTES / 1e6:.0f} MB limit"
            )

        for member in members:
            if not _is_safe_member(member.filename):
                raise SourceError(
                    f"archive member {member.filename!r} escapes the destination directory"
                )
            # 0xA000 marks a symlink; a symlink could redirect a later write outside target.
            if (member.external_attr >> 16) & 0xF000 == 0xA000:
                raise SourceError(f"archive member {member.filename!r} is a symlink")

        zf.extractall(target)

    return AcquiredSource(path=target, kind="zip", origin=archive.name)


def workspace_for_run(root: Path, run_id: int) -> Path:
    """A per-run directory, wiped if it already exists."""
    workspace = root / f"run-{run_id}"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace
