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
    """Note the assertion: SKILL.md is at the SCAN ROOT, not one level down.

    This test previously asserted `acquired.path / "skill" / "SKILL.md"`, encoding the bug it
    should have caught — the scan root pointed at a directory containing only a directory, so
    the scanner found no manifest and rejected a well-formed skill.
    """
    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("skill/SKILL.md", "# a skill")
        zf.writestr("skill/run.py", "print('hi')")

    acquired = extract_zip(archive, tmp_path / "dest")
    assert (acquired.path / "SKILL.md").read_text() == "# a skill"
    assert (acquired.path / "run.py").is_file()


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


# --- single-root archives (the shape `zip -r` produces) -----------------------------------


def _zip_from(tmp_path, files: dict[str, str], name: str = "a.zip"):
    import zipfile

    archive = tmp_path / name
    with zipfile.ZipFile(archive, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return archive


def test_a_single_top_level_directory_is_stripped(tmp_path):
    """The bug this fixes: `zip -r skill.zip skill/` nests everything one level down.

    Pointing the scanner at the extraction root then finds one subdirectory and no manifest,
    and a perfectly well-formed submission fails with "no markdown found". A git clone puts
    contents at the root, which is why repositories worked and uploads did not.
    """
    archive = _zip_from(
        tmp_path,
        {
            "skill-creator/SKILL.md": "# a skill\n",
            "skill-creator/scripts/run.py": "x = 1\n",
        },
    )
    acquired = extract_zip(archive, tmp_path / "ws")
    assert (acquired.path / "SKILL.md").is_file(), "the manifest must be at the scan root"
    assert (acquired.path / "scripts" / "run.py").is_file()


def test_content_already_at_the_root_is_left_alone(tmp_path):
    """An archive with real content at its root must not be second-guessed."""
    archive = _zip_from(tmp_path, {"SKILL.md": "# a skill\n", "run.py": "x = 1\n"})
    acquired = extract_zip(archive, tmp_path / "ws")
    assert (acquired.path / "SKILL.md").is_file()
    assert acquired.path.name == "src"


def test_two_top_level_entries_are_left_alone(tmp_path):
    """Ambiguity is not resolved by guessing: two entries means the root is the root."""
    archive = _zip_from(tmp_path, {"one/SKILL.md": "a", "two/SKILL.md": "b"})
    acquired = extract_zip(archive, tmp_path / "ws")
    assert acquired.path.name == "src"
    assert {p.name for p in acquired.path.iterdir()} == {"one", "two"}


def test_macos_metadata_does_not_defeat_stripping(tmp_path):
    """Mac-made archives almost always carry __MACOSX beside the real folder."""
    archive = _zip_from(
        tmp_path,
        {"skill/SKILL.md": "# a skill\n", "__MACOSX/._SKILL.md": "resource fork"},
    )
    acquired = extract_zip(archive, tmp_path / "ws")
    assert (acquired.path / "SKILL.md").is_file()


def test_a_root_dotfile_prevents_stripping_so_nothing_is_hidden(tmp_path):
    """Dotfiles are counted, so content at the root can never be silently skipped.

    If `.env` were ignored for counting, this archive would be scanned as `skill/` alone and
    the root file would never be read — a way to hide content from the scanner.
    """
    archive = _zip_from(tmp_path, {"skill/SKILL.md": "# a", ".env": "SECRET=1"})
    acquired = extract_zip(archive, tmp_path / "ws")
    assert acquired.path.name == "src"
    assert (acquired.path / ".env").is_file()


def test_stripping_stops_at_a_symlinked_directory(tmp_path):
    """Descent must not follow a link out of the workspace."""
    ws = tmp_path / "ws"
    target = ws / "src"
    target.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("sensitive")
    (target / "only").symlink_to(outside, target_is_directory=True)

    from app.engines.source import _strip_single_root

    assert _strip_single_root(target) == target
