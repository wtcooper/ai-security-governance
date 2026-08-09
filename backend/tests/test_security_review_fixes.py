"""Regressions for the findings of the security review of this codebase.

The tool clones untrusted repositories and unzips untrusted archives, so containment is the
property that matters most: content outside a submission must never be read as if it were part
of the submission. Each test below reproduces a specific way that failed.
"""

from __future__ import annotations

import ipaddress

import pytest

from app.engines.mcp_scanner import _bounded_target, _find_requirements, _source_files
from app.engines.safe_fetch import EXTRA_DENY, UnsafeUrlError, _require_public, validate_url


# --- Finding 1: symlink escape from a cloned repository ----------------------------------


def _tree_with_symlink(tmp_path, link_name: str = "0leak.py", filler: int = 41):
    """A submission that links to a file outside itself, plus enough filler to trip the cap."""
    outside = tmp_path / "outside.env"
    outside.write_text("SECRET=hunter2\n")

    root = tmp_path / "src"
    root.mkdir()
    (root / link_name).symlink_to(outside)
    for index in range(filler):
        (root / f"f{index}.py").write_text(f"x = {index}\n")
    return root, outside


def test_source_files_ignores_a_symlink_pointing_outside_the_root(tmp_path):
    """`is_file()` follows links and `suffix` comes from the link name, so both must be checked."""
    root, _ = _tree_with_symlink(tmp_path)
    selected = _source_files(root)
    assert not any(path.name == "0leak.py" for path in selected)
    # The genuine files are still picked up.
    assert len(selected) == 41


def test_staging_never_materialises_content_from_outside_the_root(tmp_path):
    """The original bug.

    `shutil.copy2` dereferences by default, so staging copied the TARGET's bytes into a fresh
    scan root as an ordinary file — laundering external content past the vendor scanner's own
    symlink guard, which only rejects things that still look like symlinks.
    """
    root, outside = _tree_with_symlink(tmp_path)
    staged, skipped = _bounded_target(root, cap=5)

    assert staged != root
    assert skipped > 0
    leaked = staged / "0leak.py"
    assert not leaked.exists(), "a symlinked file was staged into the scan root"
    # Nothing anywhere under the staged tree contains the outside content.
    for path in staged.rglob("*"):
        if path.is_file():
            assert outside.read_text().strip() not in path.read_text()


def test_a_symlinked_directory_does_not_smuggle_files_in(tmp_path):
    """A symlinked parent is not caught by a per-file symlink check alone."""
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    (outside_dir / "secret.py").write_text("TOKEN = 'leaked'\n")

    root = tmp_path / "src"
    root.mkdir()
    (root / "real.py").write_text("x = 1\n")
    (root / "vendored").symlink_to(outside_dir, target_is_directory=True)

    selected = _source_files(root)
    assert [path.name for path in selected] == ["real.py"]


def test_requirements_lookup_ignores_a_symlinked_manifest(tmp_path):
    """pip-audit reads the path it is given, so a symlinked manifest reads a host file."""
    outside = tmp_path / "hostfile"
    outside.write_text("requests==2.19.0\n")

    root = tmp_path / "src"
    root.mkdir()
    (root / "requirements.txt").symlink_to(outside)

    assert _find_requirements(root) is None


def test_a_real_manifest_inside_the_root_is_still_found(tmp_path):
    """The fix must not break the feature it protects."""
    root = tmp_path / "src"
    root.mkdir()
    (root / "requirements.txt").write_text("requests==2.19.0\n")

    found = _find_requirements(root)
    assert found is not None and found.name == "requirements.txt"


def test_clone_disables_symlink_checkout():
    """git must not write mode-120000 entries as real links in the first place."""
    import inspect

    from app.engines import source

    argv_source = inspect.getsource(source.clone_repo)
    assert "core.symlinks=false" in argv_source


def test_clone_disables_submodules_with_the_boolean_flag_not_the_pathspec_form():
    """The form of this flag matters, and a substring assertion missed it once already.

    git documents `--[no-]recurse-submodules[=<pathspec>]`, so `--recurse-submodules=no` is
    NOT a boolean — it enables submodule cloning and treats "no" as a pathspec. A submitted
    repository with a submodule at path `no` would then have an arbitrary URL fetched from
    .gitmodules, bypassing the forge allowlist entirely.

    The previous test asserted `"--recurse-submodules=no" in source`, which is exactly why it
    passed while the flag did the opposite of its intent.
    """
    import inspect

    from app.engines import source

    argv_source = inspect.getsource(source.clone_repo)
    # Match the quoted argv token, not prose: the docstring above legitimately names the
    # broken form, and asserting on raw text would trip over its own explanation.
    assert '"--no-recurse-submodules"' in argv_source
    assert '"--recurse-submodules=' not in argv_source, (
        "the =<pathspec> form ENABLES submodules; use the --no- boolean"
    )


@pytest.mark.parametrize(
    "payload,description",
    [
        ('{"scan_results": [{"tool_name": "eek}", "is_safe": false}], "n": 1}', "brace in a name"),
        ('{"a": "}}}}", "scan_results": [], "b": 2}', "several braces in a string"),
        ('{"a": "\\"}", "scan_results": [], "b": 3}', "escaped quote then brace"),
    ],
)
def test_json_extraction_is_not_fooled_by_braces_inside_strings(payload, description):
    """Both scanners echo submission-derived text into their reports.

    Counting braces is not string-aware, so a `}` in a filename or a quoted source line ended
    the object early — failing the parse, or worse yielding a shorter object that parses fine
    and carries fewer findings than the scanner actually reported. That let a submission
    influence how much of its own scan result survived.
    """
    import json as _json

    from app.engines.mcp_scanner import _extract_json as mcp_extract
    from app.engines.skill_scanner import _extract_json as skill_extract

    expected = _json.loads(payload)
    for extract in (mcp_extract, skill_extract):
        assert extract(payload) == expected, description


def test_json_extraction_still_skips_leading_noise():
    """The reason the scanner output is scanned at all: LiteLLM chatter precedes the payload."""
    from app.engines.mcp_scanner import _extract_json

    noisy = 'LiteLLM.Info: give feedback\nnot json at all\n{"scan_results": [], "ok": true}'
    assert _extract_json(noisy) == {"scan_results": [], "ok": True}


def test_a_directory_named_requirements_txt_is_not_handed_to_pip_audit(tmp_path):
    """pip-audit's project mode resolves and installs declared dependencies.

    Pointing it at a submission-controlled directory would run a build backend on attacker
    input, which is the one thing this tool must never do.
    """
    root = tmp_path / "src"
    (root / "requirements.txt").mkdir(parents=True)
    # A real manifest nested inside the attacker-named directory: skipping the directory
    # alone left this reachable, which is how the first attempt at this fix fell short.
    (root / "requirements.txt" / "pyproject.toml").write_text("[project]\nname='x'\n")

    assert _find_requirements(root) is None


def test_a_pyproject_is_never_handed_to_pip_audit(tmp_path):
    """Only requirements.txt is accepted; pyproject.toml selects pip-audit's project mode."""
    root = tmp_path / "src"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='x'\n")

    assert _find_requirements(root) is None


# --- Finding 2: SSRF — routability check and address pinning -----------------------------


@pytest.mark.parametrize(
    "address",
    [
        "100.64.0.1",  # CGNAT — the range the previous predicate list missed
        "100.127.255.254",
        "192.88.99.1",  # deprecated 6to4 relay anycast; is_global reports True
        "127.0.0.1",
        "10.0.0.5",
        "169.254.169.254",  # cloud instance metadata
        "192.168.1.1",
        "172.16.0.1",
        "::1",
        "0.0.0.0",
    ],
)
def test_non_routable_addresses_are_refused(address):
    with pytest.raises(UnsafeUrlError, match="not a globally routable"):
        _require_public("example.test", ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(address):
    _require_public("example.test", ipaddress.ip_address(address))


def test_cgnat_is_rejected_through_the_url_path_too():
    """The regression as a caller would hit it, not just at the predicate."""
    with pytest.raises(UnsafeUrlError):
        validate_url("https://100.64.0.1/card")


def test_the_extra_deny_list_covers_the_ranges_is_global_allows():
    """`is_global` is necessary but not sufficient; document which cases it misses."""
    six_to_four = ipaddress.ip_address("192.88.99.1")
    assert six_to_four.is_global, "if this becomes False, EXTRA_DENY can drop this entry"
    assert any(six_to_four in network for network in EXTRA_DENY)


def test_fetch_pins_the_validated_address_rather_than_re_resolving():
    """Validation and connection must use the same address, or rebinding defeats the check."""
    import inspect

    from app.engines import safe_fetch

    fetch_source = inspect.getsource(safe_fetch.fetch_text)
    assert "_pin_to_validated_address" in fetch_source
    assert "sni_hostname" in fetch_source, "TLS would fail against a bare IP without SNI"
    assert '"Host"' in fetch_source, "virtual hosting needs the original Host header"


def test_pinning_rewrites_the_host_to_a_literal_address(monkeypatch):
    from app.engines import safe_fetch

    monkeypatch.setattr(
        safe_fetch, "_addresses_for", lambda host: [ipaddress.ip_address("93.184.216.34")]
    )
    pinned, host = safe_fetch._pin_to_validated_address("https://example.com/a/b?c=1")

    assert host == "example.com"
    assert "93.184.216.34" in pinned
    assert "/a/b" in pinned and "c=1" in pinned


def test_pinning_refuses_when_the_second_lookup_returns_something_internal(monkeypatch):
    """The rebinding case: the address is re-checked at connection time, not just up front."""
    from app.engines import safe_fetch

    monkeypatch.setattr(
        safe_fetch, "_addresses_for", lambda host: [ipaddress.ip_address("10.1.2.3")]
    )
    with pytest.raises(UnsafeUrlError):
        safe_fetch._pin_to_validated_address("https://rebind.example.com/")


# --- Hardening: scanner subprocesses get the same scrubbing as the eval child ------------


def test_scanner_environments_carry_no_provider_credentials(monkeypatch, tmp_path):
    """The scanners need the gateway pair and nothing else.

    Not known to be exploitable in the documented deployment, but the asymmetry with
    inspect_child was the kind of inconsistency that turns into a leak after a config change.
    """
    from app.config import Settings
    from app.engines import mcp_scanner, skill_scanner

    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-propagate")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-must-not-propagate")

    settings = Settings(
        gateway_base_url="http://gateway:4000/v1",
        gateway_api_key="sk-local",
        gateway_provider="gateway",
        default_judge_model="qwen35",
        default_subject_model="gemma4",
        scanner_model="gemma4",
        db_path=tmp_path / "db.sqlite",
        artifact_dir=tmp_path / "artifacts",
        workspace_dir=tmp_path / "workspaces",
        policy_dir=tmp_path / "policy",
        fixtures_dir=tmp_path / "fixtures",
    )

    for build_env in (mcp_scanner.scanner_env, skill_scanner.scanner_env):
        env = build_env(settings)
        assert "OPENAI_API_KEY" not in env
        assert "ANTHROPIC_API_KEY" not in env
        assert "sk-must-not-propagate" not in env.values()
        # The credentials they legitimately need are still present.
        assert env["MCP_SCANNER_LLM_API_KEY" if build_env is mcp_scanner.scanner_env else "SKILL_SCANNER_LLM_API_KEY"] == "sk-local"
