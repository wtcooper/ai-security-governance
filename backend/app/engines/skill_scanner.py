"""Running cisco-ai-skill-scanner over submitted agent skills.

Output shape captured from a real run:

    {
      "skill_name": "...", "skill_path": "...",
      "is_safe": false, "max_severity": "CRITICAL", "findings_count": 4,
      "analyzers_used": ["static_analyzer", "bytecode", "pipeline"],
      "findings": [{"id": "...", "rule_id": "YARA_prompt_injection_generic",
                    "category": "prompt_injection", "severity": "CRITICAL",
                    "title": "...", "description": "...", "file_path": "SKILL.md",
                    "line_number": 7, "snippet": "...", "remediation": "...",
                    "analyzer": "static", "metadata": {...}}],
      "scan_metadata": {"policy_version": "1.0",
                        "policy_fingerprint_sha256": "e6033e..."}
    }

Unlike mcp-scanner, this one **does** emit CRITICAL, and it reports its own `is_safe`
verdict plus a policy fingerprint we can record as the ruleset version — so nothing has to
be re-derived here.
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
from app.engines.mcp_scanner import ScanFinding
from app.models import Severity

SEVERITY_MAP = {
    "CRITICAL": Severity.CRITICAL,
    "HIGH": Severity.HIGH,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
    "INFO": Severity.INFO,
    "UNKNOWN": Severity.LOW,
}


@dataclass
class SkillScanResult:
    ok: bool
    findings: list[ScanFinding] = field(default_factory=list)
    skill_name: str | None = None
    # The scanner's own verdict. Honoured rather than re-derived — it already applies the
    # meta-analyzer's false-positive filtering, which we would only be second-guessing.
    scanner_says_safe: bool | None = None
    max_severity: str | None = None
    analyzers_used: list[str] = field(default_factory=list)
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
    """skill-scanner is LiteLLM-backed, so it takes the same gateway pair."""
    env = dict(os.environ)
    env["SKILL_SCANNER_LLM_API_KEY"] = settings.gateway_api_key
    env["SKILL_SCANNER_LLM_BASE_URL"] = settings.gateway_base_url
    env["SKILL_SCANNER_LLM_MODEL"] = f"openai/{settings.scanner_model}"
    return env


def parse_findings(payload: dict[str, Any]) -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    for entry in payload.get("findings") or []:
        severity = SEVERITY_MAP.get(str(entry.get("severity", "UNKNOWN")).upper(), Severity.LOW)
        location = entry.get("file_path") or ""
        if entry.get("line_number"):
            location = f"{location}:{entry['line_number']}"
        detail_parts = [
            str(entry.get("description") or ""),
            f"snippet: {entry['snippet']}" if entry.get("snippet") else "",
            f"remediation: {entry['remediation']}" if entry.get("remediation") else "",
        ]
        findings.append(
            ScanFinding(
                analyzer=str(entry.get("analyzer") or "unknown"),
                severity=severity,
                rule_id=entry.get("rule_id") or entry.get("id"),
                title=str(entry.get("title") or entry.get("category") or "finding"),
                detail=" | ".join(p for p in detail_parts if p)[:4000],
                file_path=location or None,
            )
        )
    return findings


async def scan_skill(
    settings: Settings,
    source_path: Path,
    use_llm: bool = True,
    timeout: float = 1800.0,
) -> SkillScanResult:
    """Full analyzer sweep over a skill directory.

    `--lenient` is passed because real-world skill repos frequently do not match the strict
    Agent Skills layout, and refusing to scan them would leave the riskiest submissions
    unassessed.
    """
    argv = [
        sys.executable,
        "-m",
        # Entry point is skill_scanner.cli.cli:main. `skill_scanner.cli` alone is a PACKAGE
        # with no __main__, so `python -m skill_scanner.cli` fails at import time.
        "skill_scanner.cli.cli",
        "scan",
        str(source_path),
        "--use-behavioral",
        "--enable-meta",
        "--use-osv",
        "--lenient",
        "--format",
        "json",
    ]
    if use_llm:
        # openai-compatible is exactly our case: an OpenAI-shaped endpoint that is not OpenAI.
        argv += ["--use-llm", "--llm-provider", "openai-compatible"]

    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=scanner_env(settings),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return SkillScanResult(ok=False, errors=[f"skill scan timed out after {timeout:.0f}s"])

    text = stdout.decode()
    payload = _extract_json(text)
    if payload is None:
        return SkillScanResult(
            ok=False,
            errors=[
                "skill scan produced no JSON "
                f"(exit {process.returncode}): {(stderr.decode() or text)[-800:]}"
            ],
        )

    metadata = payload.get("scan_metadata") or {}
    fingerprint = metadata.get("policy_fingerprint_sha256")
    return SkillScanResult(
        ok=True,
        findings=parse_findings(payload),
        skill_name=payload.get("skill_name"),
        scanner_says_safe=payload.get("is_safe"),
        max_severity=payload.get("max_severity"),
        analyzers_used=list(payload.get("analyzers_used") or []),
        engine_version=_engine_version(),
        ruleset_version=(
            f"policy {metadata.get('policy_version')} "
            f"({str(fingerprint)[:12]})" if fingerprint else metadata.get("policy_version")
        ),
        raw=payload,
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    """Find the JSON document in stdout, which may be preceded by log lines."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : index + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def _engine_version() -> str | None:
    import importlib.metadata as md

    try:
        return f"cisco-ai-skill-scanner {md.version('cisco-ai-skill-scanner')}"
    except md.PackageNotFoundError:
        return None
