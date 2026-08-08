"""Two client-controlled inputs that could otherwise reach places they must not.

Both were flagged by an automated security review of the Phase 3-5 commit, and both were
real. They are worth guarding carefully in this project specifically: a security governance
tool that can be turned against its own network is worse than no tool.

1. `identifier` on a scanner run is a filesystem path. Unvalidated, a client could submit
   `/etc` or the app's SQLite file and read it back through the findings, because the
   scanners quote the source lines they flag.
2. `url` on the published-score extractor is fetched server-side. Unvalidated, it reaches
   cloud instance metadata, the model gateway, and this API itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engines.safe_fetch import UnsafeUrlError, validate_url
from app.engines.source import SourceError, resolve_submission_path


# --- submission paths --------------------------------------------------------------------


@pytest.fixture
def roots(tmp_path: Path) -> list[Path]:
    uploads = tmp_path / "uploads"
    fixtures = tmp_path / "fixtures"
    uploads.mkdir()
    fixtures.mkdir()
    return [uploads, fixtures]


def test_accepts_a_path_inside_an_allowed_root(roots):
    archive = roots[0] / "upload-1.zip"
    archive.write_bytes(b"PK\x03\x04")
    assert resolve_submission_path(str(archive), roots) == archive.resolve()


def test_accepts_a_directory_inside_an_allowed_root(roots):
    fixture = roots[1] / "poisoned_skill"
    fixture.mkdir()
    assert resolve_submission_path(str(fixture), roots) == fixture.resolve()


@pytest.mark.parametrize(
    "hostile",
    [
        "/etc",
        "/etc/passwd",
        "/",
        "../../../../etc/passwd",
    ],
)
def test_rejects_paths_outside_the_allowed_roots(roots, hostile):
    with pytest.raises(SourceError, match="must be an https repository URL"):
        resolve_submission_path(hostile, roots)


def test_rejects_traversal_that_starts_inside_an_allowed_root(roots):
    """`uploads/../../etc` must not pass just because it begins with an allowed prefix."""
    escape = str(roots[0] / ".." / ".." / "etc")
    with pytest.raises(SourceError):
        resolve_submission_path(escape, roots)


def test_rejects_a_symlink_pointing_out_of_an_allowed_root(roots, tmp_path):
    """A symlink inside uploads must not become a read primitive for the rest of the disk."""
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "creds.txt").write_text("sensitive")

    link = roots[0] / "sneaky"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(SourceError):
        resolve_submission_path(str(link), roots)


def test_rejects_a_nonexistent_path_inside_an_allowed_root(roots):
    with pytest.raises(SourceError, match="no such submission"):
        resolve_submission_path(str(roots[0] / "not-there.zip"), roots)


# --- server-side URL fetching -------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/card",  # cleartext
        "file:///etc/passwd",  # local filesystem
        "gopher://example.com/",  # protocol smuggling
        "ftp://example.com/x",
    ],
)
def test_rejects_non_https_schemes(url):
    with pytest.raises(UnsafeUrlError, match="must be https"):
        validate_url(url)


def test_rejects_url_without_a_host():
    with pytest.raises(UnsafeUrlError):
        validate_url("https:///no-host")


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",  # this API
        "https://localhost/",
        "https://169.254.169.254/latest/meta-data/",  # cloud instance metadata
        "https://10.0.0.5/",  # private
        "https://192.168.1.1/",
        "https://172.16.0.1/",
        "https://[::1]/",
        "https://0.0.0.0/",
    ],
)
def test_rejects_internal_and_metadata_addresses(url):
    with pytest.raises(UnsafeUrlError, match="private, loopback, or"):
        validate_url(url)


def test_rejects_a_hostname_that_resolves_to_loopback():
    """String checks are not enough — a public-looking name can resolve inward."""
    # localhost.localdomain and similar resolve to 127.0.0.1 on most systems; if the name
    # does not resolve at all the guard still refuses, which is the safe outcome either way.
    with pytest.raises(UnsafeUrlError):
        validate_url("https://localhost.localdomain/card")


def test_accepts_a_public_https_url():
    assert validate_url("https://huggingface.co/openai-community/gpt2") == (
        "https://huggingface.co/openai-community/gpt2"
    )
