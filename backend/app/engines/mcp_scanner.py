"""Running cisco-ai-mcp-scanner over submitted MCP server source.

Output shape was captured from a real run, not documentation:

    {
      "server_url": "behavioral:/path",
      "scan_results": [
        {"tool_name": "get_weather", "tool_description": "...", "status": "completed",
         "is_safe": false,
         "findings": {"behavioral_analyzer": {
             "severity": "HIGH", "threat_summary": "...", "threat_names": ["DATA EXFILTRATION"],
             "total_findings": 1, "source_file": "...", "mcp_taxonomies": [...],
             "threat_vulnerability_classification": "THREAT"}}}
      ],
      "requested_analyzers": ["api", "yara", "llm"]
    }

Two limitations worth stating plainly rather than papering over:

1. **mcp-scanner's top severity is HIGH — it has no CRITICAL.** Its vocabulary is
   HIGH / MEDIUM / LOW / UNKNOWN / SAFE. A policy that blocks on `critical` for MCP would
   never match anything; HIGH is what does the work.

2. **We do not enumerate the server's live tools.** Getting the real tool list means launching
   the server (`stdio`) or connecting to it (`remote`), which is executing untrusted code —
   the one thing this tool must not do by default. So detection comes from source analysis,
   which reads tool definitions where they are written but cannot see tools generated at
   runtime. The `stdio` path exists behind an explicit opt-in for cases where that trade is
   acceptable.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models import Severity

# mcp-scanner severities, uppercase in JSON output, mapped onto ours. UNKNOWN becomes LOW
# rather than being dropped: an analyzer that flagged something it could not classify is still
# telling us something.
SEVERITY_MAP = {
    "CRITICAL": Severity.CRITICAL,
    "HIGH": Severity.HIGH,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
    "UNKNOWN": Severity.LOW,
    "SAFE": Severity.INFO,
    "INFO": Severity.INFO,
}


@dataclass
class ScanFinding:
    analyzer: str
    severity: Severity
    title: str
    detail: str
    rule_id: str | None = None
    file_path: str | None = None


@dataclass
class McpScanResult:
    ok: bool
    findings: list[ScanFinding] = field(default_factory=list)
    tools_scanned: int = 0
    scanner_says_safe: bool | None = None
    engine_version: str | None = None
    ruleset_version: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def severity_counts(self) -> dict[Severity, int]:
        counts: dict[Severity, int] = {}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts


def scanner_env(settings: Settings) -> dict[str, str]:
    """mcp-scanner talks to an LLM through LiteLLM, so it takes the same gateway pair.

    `openai/<alias>` tells LiteLLM to use its OpenAI-compatible client against our base URL,
    which is how a local model ends up doing the analysis for free.
    """
    # Scrubbed the same way the eval child is. The scanners only ever need the gateway pair,
    # so passing the whole environment gave them provider credentials they have no use for.
    # Not known to be exploitable — the backend container is not given provider keys — but the
    # asymmetry with inspect_child was the kind of inconsistency that becomes a leak later.
    from app.engines.inspect_child import scrub_provider_credentials

    env = scrub_provider_credentials(dict(os.environ))
    env["MCP_SCANNER_LLM_API_KEY"] = settings.gateway_api_key
    env["MCP_SCANNER_LLM_BASE_URL"] = settings.gateway_base_url
    env["MCP_SCANNER_LLM_MODEL"] = f"openai/{settings.scanner_model}"
    return env


async def _run(argv: list[str], env: dict[str, str], timeout: float) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return 124, "", f"timed out after {timeout:.0f}s"
    return process.returncode or 0, stdout.decode(), stderr.decode()


def _extract_json(text: str) -> dict[str, Any] | None:
    """Find the JSON document in stdout, which may be preceded by other output.

    Uses `raw_decode` at each candidate `{` rather than counting braces. Brace counting is not
    string-aware: a `}` inside a JSON string value — and both scanners echo submission-derived
    text such as filenames and source lines into their reports — ends the object early. That
    either fails the parse or, worse, yields a shorter object that happens to be valid and
    carries fewer findings than the scanner actually reported.
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    return None


def parse_behavioral(payload: dict[str, Any]) -> tuple[list[ScanFinding], int, bool | None]:
    """Turn scan_results into findings, preserving analyzer attribution."""
    findings: list[ScanFinding] = []
    results = payload.get("scan_results") or []
    any_unsafe = False

    for entry in results:
        tool = entry.get("tool_name") or "?"
        if entry.get("is_safe") is False:
            any_unsafe = True
        for analyzer, detail in (entry.get("findings") or {}).items():
            if not isinstance(detail, dict):
                continue
            severity = SEVERITY_MAP.get(
                str(detail.get("severity", "UNKNOWN")).upper(), Severity.LOW
            )
            threats = detail.get("threat_names") or []
            findings.append(
                ScanFinding(
                    analyzer=analyzer,
                    severity=severity,
                    rule_id=",".join(str(t) for t in threats) or None,
                    title=f"{tool}: {', '.join(str(t) for t in threats) or 'finding'}",
                    detail=str(detail.get("threat_summary") or "")[:4000],
                    file_path=detail.get("source_file"),
                )
            )

    return findings, len(results), (not any_unsafe) if results else None


def parse_vulnerable_packages(payload: dict[str, Any]) -> list[ScanFinding]:
    """Dependency CVEs from the pip-audit-backed analyzer."""
    findings: list[ScanFinding] = []
    for entry in payload.get("scan_results") or []:
        for analyzer, detail in (entry.get("findings") or {}).items():
            if not isinstance(detail, dict):
                continue
            severity = SEVERITY_MAP.get(
                str(detail.get("severity", "UNKNOWN")).upper(), Severity.LOW
            )
            findings.append(
                ScanFinding(
                    analyzer=analyzer,
                    severity=severity,
                    rule_id="vulnerable_dependency",
                    title=f"Vulnerable dependency: {entry.get('tool_name') or '?'}",
                    detail=str(detail.get("threat_summary") or "")[:4000],
                )
            )
    return findings


async def scan_source(
    settings: Settings,
    source_path: Path,
    timeout: float = 1800.0,
    max_source_files: int = 40,
) -> McpScanResult:
    """Full safe-path sweep: behavioral source analysis plus dependency vulnerabilities.

    `pypi-scan` and `npm-scan` are deliberately not run: they require a Docker sandbox, which
    is unavailable inside this container, and they download and unpack packages. The
    pip-audit-backed `vulnerable-package` analyzer covers dependency risk without either.

    `max_source_files` bounds the behavioral analyzer, which invokes an LLM per source file —
    unbounded, a large monorepo would run for hours. When the cap bites it is recorded as a
    finding, because a scan that silently covered a fraction of the tree reads exactly like a
    scan that found nothing.
    """
    env = scanner_env(settings)
    result = McpScanResult(ok=True, engine_version=_engine_version())

    scan_target, skipped = _bounded_target(source_path, max_source_files)
    if skipped:
        result.findings.append(
            ScanFinding(
                analyzer="coverage",
                severity=Severity.MEDIUM,
                rule_id="scan_coverage_capped",
                title=f"Behavioral analysis covered {max_source_files} of {max_source_files + skipped} source files",
                detail=(
                    f"{skipped} source file(s) were not analysed, because the behavioral "
                    "analyzer runs a model per file and an unbounded sweep of a large "
                    "repository does not finish. Treat the uncovered portion as unassessed "
                    "rather than clean. Raise max_source_files, or submit the individual "
                    "server directory instead of a monorepo."
                ),
            )
        )
    source_path = scan_target

    code, stdout, stderr = await _run(
        [sys.executable, "-m", "mcpscanner.cli", "behavioral", str(source_path), "--format", "raw"],
        env,
        timeout,
    )
    payload = _extract_json(stdout)
    if payload is None:
        result.ok = False
        result.errors.append(
            f"behavioral scan produced no JSON (exit {code}): "
            f"{(stderr or stdout)[-600:]}"
        )
    else:
        findings, tools, safe = parse_behavioral(payload)
        result.findings.extend(findings)
        result.tools_scanned = tools
        result.scanner_says_safe = safe
        result.raw["behavioral"] = payload

    # Dependency scan is best-effort: a repo with no Python manifest simply has nothing to
    # audit, which must not fail the whole scan.
    requirements = _find_requirements(source_path)
    if requirements is not None:
        code, stdout, stderr = await _run(
            [
                sys.executable,
                "-m",
                "mcpscanner.cli",
                "vulnerable-package",
                str(requirements),
                # Without these, pip-audit tries to build a resolution venv via ensurepip,
                # which aborts on some hosts (observed: SIGABRT). The scanner then logs a
                # warning and reports "SAFE (0 findings)" — a silent false negative, which is
                # the single worst outcome for a governance tool. Scanning only the pinned
                # packages is a narrower claim, but it is a true one.
                "--no-deps",
                "--disable-pip",
                "--format",
                "raw",
            ],
            env,
            timeout,
        )
        combined = f"{stdout}\n{stderr}"
        dep_payload = _extract_json(stdout)

        # Never accept a clean dependency result that came from a broken audit.
        if _pip_audit_failed(combined):
            result.findings.append(
                ScanFinding(
                    analyzer="vulnerable_package_analyzer",
                    severity=Severity.MEDIUM,
                    rule_id="dependency_scan_unreliable",
                    title="Dependency vulnerability scan did not complete",
                    detail=(
                        "pip-audit failed, so a clean result here would be meaningless rather "
                        "than reassuring. Treat dependency risk as unassessed. Scanner output: "
                        + combined[-800:]
                    ),
                )
            )
            result.errors.append("pip-audit failed; dependency risk is unassessed")
        elif dep_payload is not None:
            result.findings.extend(parse_vulnerable_packages(dep_payload))
            result.raw["vulnerable_package"] = dep_payload
        else:
            result.errors.append(
                f"dependency scan produced no JSON (exit {code}): {(stderr or stdout)[-400:]}"
            )

    result.ruleset_version = _ruleset_version()
    return result


SOURCE_SUFFIXES = (".py", ".js", ".ts", ".mjs", ".cjs", ".tsx", ".jsx")
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__", "tests"}


def _source_files(root: Path) -> list[Path]:
    """Source files inside the scan root, excluding anything that points outside it.

    `is_file()` follows symlinks and `suffix` comes from the link name, so without the
    symlink checks a submission containing `a.py -> /etc/passwd` would have that file read as
    if it were part of the submission.
    """
    files: list[Path] = []
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*")):
        # Checked before is_file(), which would follow the link and report the target's type.
        if path.is_symlink():
            continue
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        # Belt and braces: a symlinked *parent* directory would not be caught above.
        try:
            path.resolve().relative_to(resolved_root)
        except ValueError:
            continue
        files.append(path)
    return files


def _bounded_target(root: Path, cap: int) -> tuple[Path, int]:
    """Return a directory to scan, plus how many source files were left out.

    Under the cap, the whole tree is scanned. Over it, a staging directory is built holding
    the first `cap` files (preserving relative layout so the analyzer still sees module
    context), and the shortfall is reported by the caller.
    """
    files = _source_files(root)
    if len(files) <= cap:
        return root, 0

    import shutil

    staged = root.parent / f"{root.name}-bounded"
    if staged.exists():
        shutil.rmtree(staged)
    for path in files[:cap]:
        destination = staged / path.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # follow_symlinks=False matters: the default copies the TARGET's bytes, which would
        # materialise content from outside the scan root as an ordinary file inside a fresh
        # root — laundering it past the vendor scanner's own symlink guard.
        shutil.copy2(path, destination, follow_symlinks=False)
    # Manifests are small and needed by the dependency analyzer.
    for manifest in ("requirements.txt", "pyproject.toml", "package.json"):
        for match in sorted(root.rglob(manifest))[:1]:
            if match.is_symlink():
                continue
            destination = staged / match.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(match, destination, follow_symlinks=False)
    return staged, len(files) - cap


def _pip_audit_failed(output: str) -> bool:
    """Detect the failure mode where pip-audit dies but the scan still reports SAFE."""
    markers = (
        "pip-audit exited with code",
        "produced no JSON output",
        "dependency-resolution failure",
        "CalledProcessError",
    )
    return any(marker in output for marker in markers)


def _find_requirements(source_path: Path) -> Path | None:
    """A manifest inside the tree, never a symlink to one outside it.

    pip-audit reads the path it is given, so a symlinked manifest would have it read an
    arbitrary host file.
    """
    resolved_root = source_path.resolve()
    # requirements.txt ONLY. A pyproject.toml selects pip-audit's project mode, which resolves
    # and installs declared dependencies — running a build backend on attacker input. A
    # submission can also place a real pyproject.toml inside a directory it names
    # "requirements.txt", so refusing the directory is not enough on its own; the file type
    # we accept has to be the narrow one.
    for candidate in ("requirements.txt",):
        for match in sorted(source_path.rglob(candidate)):
            if match.is_symlink():
                continue
            # A submission can contain a DIRECTORY named requirements.txt. Handing that to
            # pip-audit selects its project mode, which resolves and installs declared
            # dependencies — i.e. runs a build backend on attacker-controlled input.
            if not match.is_file():
                continue
            try:
                match.resolve().relative_to(resolved_root)
            except ValueError:
                continue
            return match
    return None


def _engine_version() -> str | None:
    import importlib.metadata as md

    try:
        return f"cisco-ai-mcp-scanner {md.version('cisco-ai-mcp-scanner')}"
    except md.PackageNotFoundError:
        return None


def _ruleset_version() -> str | None:
    """Hash the bundled YARA rules.

    The scanner does not report a ruleset version, so we derive one. Without it, a change in
    findings could not be attributed to a rule update rather than to the artifact — which is
    exactly what hand-tuning the severity rule requires.
    """
    import hashlib
    from importlib.util import find_spec

    spec = find_spec("mcpscanner")
    if spec is None or not spec.submodule_search_locations:
        return None
    root = Path(next(iter(spec.submodule_search_locations)))
    rule_files = sorted(root.rglob("*.yar")) + sorted(root.rglob("*.yara"))
    if not rule_files:
        return None
    digest = hashlib.sha256()
    for path in rule_files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return f"yara:{digest.hexdigest()[:12]} ({len(rule_files)} files)"
