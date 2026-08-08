"""Safely acquiring untrusted source.

Acceptance criteria 3.7 and part of 3.6. These are pure-logic tests because the attacks they
cover are about what the code refuses to do — a real clone of a benign repo would never
exercise them.
"""

from __future__ import annotations

import zipfile

import pytest

from app.engines.source import (
    MAX_MEMBERS,
    SourceError,
    extract_zip,
    validate_repo_url,
    workspace_for_run,
)


# --- repository URLs ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo",
        "https://gitlab.com/owner/repo.git",
        "https://codeberg.org/owner/repo",
    ],
)
def test_accepts_https_urls_on_known_forges(url):
    assert validate_repo_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "git://github.com/owner/repo",  # unauthenticated git protocol
        "ssh://git@github.com/owner/repo",  # would use local keys
        "file:///etc/passwd",  # reads the local filesystem
        "http://github.com/owner/repo",  # cleartext
        "https://evil.example.com/owner/repo",  # unknown host
        "https://github.com/",  # no repository path
    ],
)
def test_rejects_unsafe_or_unknown_repository_urls(url):
    with pytest.raises(SourceError):
        validate_repo_url(url)


# --- zip extraction ---------------------------------------------------------------------


def test_extracts_a_benign_archive(tmp_path):
    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("skill/SKILL.md", "# a skill")
        zf.writestr("skill/run.py", "print('hi')")

    acquired = extract_zip(archive, tmp_path / "dest")
    assert (acquired.path / "skill" / "SKILL.md").read_text() == "# a skill"


@pytest.mark.parametrize(
    "member",
    [
        "../escaped.txt",
        "../../etc/passwd",
        "nested/../../escaped.txt",
        "/absolute/path.txt",
    ],
)
def test_rejects_zip_slip_paths(tmp_path, member):
    """A crafted member path must not write outside the destination."""
    archive = tmp_path / "slip.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(member, "payload")

    with pytest.raises(SourceError, match="escapes the destination"):
        extract_zip(archive, tmp_path / "dest")

    assert not (tmp_path / "escaped.txt").exists()


def test_rejects_symlink_members(tmp_path):
    """A symlink member could redirect a later write outside the destination."""
    archive = tmp_path / "link.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0xA1FF) << 16  # symlink mode bits
        zf.writestr(info, "/etc/passwd")

    with pytest.raises(SourceError, match="symlink"):
        extract_zip(archive, tmp_path / "dest")


def test_rejects_zip_bombs_by_uncompressed_size(tmp_path):
    """Highly compressible content must be judged on its expanded size."""
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 600 MB of zeroes compresses to almost nothing but would fill the disk.
        zf.writestr("big.bin", b"\0" * (600 * 1024 * 1024))

    with pytest.raises(SourceError, match="expands to"):
        extract_zip(archive, tmp_path / "dest")


def test_rejects_archives_with_too_many_members(tmp_path):
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for index in range(MAX_MEMBERS + 1):
            zf.writestr(f"f{index}.txt", "x")

    with pytest.raises(SourceError, match="over the"):
        extract_zip(archive, tmp_path / "dest")


# --- workspaces -------------------------------------------------------------------------


def test_workspace_is_wiped_between_runs(tmp_path):
    first = workspace_for_run(tmp_path, 7)
    (first / "stale.txt").write_text("left over")

    second = workspace_for_run(tmp_path, 7)
    assert second == first
    assert not (second / "stale.txt").exists()
