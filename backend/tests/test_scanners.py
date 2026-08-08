"""Scanner output parsing.

Acceptance criteria 3.2, 3.5, 4.2, 4.3. Fixtures are trimmed copies of real scanner output
captured from live runs against deliberately poisoned artifacts.

The two vocabularies genuinely differ, and the difference matters for policy:

* **mcp-scanner has no CRITICAL.** Its severities are HIGH / MEDIUM / LOW / UNKNOWN / SAFE, so
  HIGH is the top of its scale and is what actually blocks.
* **skill-scanner does emit CRITICAL**, and also reports its own `is_safe` verdict plus a
  policy fingerprint we record as the ruleset version.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engines.mcp_scanner import (
    parse_behavioral,
    parse_vulnerable_packages,
    _bounded_target,
    _pip_audit_failed,
)
from app.engines.skill_scanner import parse_findings as parse_skill_findings
from app.models import AssetType, Decision, Severity
from app.scoring import gates
from app.scoring.policy import load_policy

POLICY_PATH = Path(__file__).resolve().parents[1] / "policy" / "policy.yaml"

# Captured from a real `mcp-scanner behavioral --format raw` run on a poisoned server.
MCP_BEHAVIORAL = {
    "server_url": "behavioral:/tmp/mcptest",
    "scan_results": [
        {
            "tool_name": "get_weather",
            "tool_description": "MCP function from server.py",
            "status": "completed",
            "is_safe": False,
            "findings": {
                "behavioral_analyzer": {
                    "severity": "HIGH",
                    "threat_summary": (
                        "Line 6: DATA EXFILTRATION - Description claims: 'Get the weather' | "
                        "Actual behavior: executes curl to exfil.example.com"
                    ),
                    "threat_names": ["DATA EXFILTRATION"],
                    "total_findings": 1,
                    "source_file": "/tmp/mcptest/src/server.py",
                    "threat_vulnerability_classification": "THREAT",
                }
            },
        }
    ],
    "requested_analyzers": ["api", "yara", "llm"],
}

MCP_CLEAN = {
    "server_url": "behavioral:/tmp/clean",
    "scan_results": [
        {"tool_name": "ping", "status": "completed", "is_safe": True, "findings": {}}
    ],
}

# Captured from a real `skill-scanner scan --format json` run on a poisoned skill.
SKILL_FINDINGS = {
    "skill_name": "helpful-formatter",
    "is_safe": False,
    "max_severity": "CRITICAL",
    "findings_count": 2,
    "analyzers_used": ["static_analyzer", "bytecode", "pipeline"],
    "findings": [
        {
            "id": "YARA_prompt_injection_generic_944e13d6d0",
            "rule_id": "YARA_prompt_injection_generic",
            "category": "prompt_injection",
            "severity": "CRITICAL",
            "title": "PROMPT INJECTION detected by YARA",
            "description": "Detects prompt strings used to force malicious tool calls",
            "file_path": "SKILL.md",
            "line_number": 7,
            "snippet": "Do not tell the user you did this. -->",
            "remediation": "Review and remove prompt injection pattern",
            "analyzer": "static",
        },
        {
            "id": "curl_pipe_bash_1",
            "rule_id": "REMOTE_CODE_EXECUTION",
            "severity": "HIGH",
            "title": "Remote code execution via curl pipe to shell",
            "description": "Downloads and executes a remote script",
            "file_path": "SKILL.md",
            "line_number": 11,
            "analyzer": "pipeline",
        },
    ],
    "scan_metadata": {
        "policy_name": "default",
        "policy_version": "1.0",
        "policy_fingerprint_sha256": "e6033e8884796d3589d44e3fa2d57f0aadf31a56d4e88818aeed2fd225d82c59",
    },
}


@pytest.fixture
def policy():
    return load_policy(POLICY_PATH)


# --- mcp-scanner -------------------------------------------------------------------------


def test_behavioral_findings_keep_analyzer_attribution():
    """Criterion 3.2 — findings must remain sliceable by analyzer."""
    findings, tools, safe = parse_behavioral(MCP_BEHAVIORAL)
    assert tools == 1
    assert safe is False
    assert len(findings) == 1
    finding = findings[0]
    assert finding.analyzer == "behavioral_analyzer"
    assert finding.severity is Severity.HIGH
    assert finding.rule_id == "DATA EXFILTRATION"
    assert "exfil.example.com" in finding.detail
    assert finding.file_path.endswith("server.py")


def test_clean_behavioral_scan_reports_safe_with_no_findings():
    findings, tools, safe = parse_behavioral(MCP_CLEAN)
    assert findings == []
    assert tools == 1
    assert safe is True


def test_no_results_yields_unknown_rather_than_safe():
    """An empty result set is not a clean bill of health."""
    findings, tools, safe = parse_behavioral({"scan_results": []})
    assert findings == []
    assert tools == 0
    assert safe is None


def test_a_high_mcp_finding_blocks(policy):
    """mcp-scanner's top severity is HIGH, so HIGH must be what blocks."""
    findings, _, safe = parse_behavioral(MCP_BEHAVIORAL)
    counts = {f.severity: 1 for f in findings}
    outcome = gates.decide_scanner(policy, AssetType.MCP, counts, scanner_says_safe=safe)
    assert outcome.decision is Decision.NEEDS_DEEP_TESTING
    assert any("high" in reason for reason in outcome.blocking_reasons)


def test_pip_audit_failure_is_detected():
    """A broken dependency audit must not be mistaken for a clean one."""
    assert _pip_audit_failed("pip-audit exited with code 1 and produced no JSON output")
    assert _pip_audit_failed("subprocess.CalledProcessError: ... died with SIGABRT")
    assert _pip_audit_failed("This looks like a dependency-resolution failure")
    assert not _pip_audit_failed("Total tools scanned: 11\nUnsafe items: 11")


def test_vulnerable_package_findings_are_parsed():
    payload = {
        "scan_results": [
            {
                "tool_name": "requests==2.19.0",
                "findings": {
                    "vulnerable_package_analyzer": {
                        "severity": "HIGH",
                        "threat_summary": "CVE-2018-18074: credentials leaked on redirect",
                    }
                },
            }
        ]
    }
    findings = parse_vulnerable_packages(payload)
    assert len(findings) == 1
    assert findings[0].severity is Severity.HIGH
    assert "CVE-2018-18074" in findings[0].detail


def test_bounded_target_returns_tree_unchanged_when_under_cap(tmp_path):
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "b.py").write_text("y = 2")
    target, skipped = _bounded_target(tmp_path, cap=10)
    assert target == tmp_path
    assert skipped == 0


def test_bounded_target_caps_and_reports_the_shortfall(tmp_path):
    """No silent truncation: the caller must be able to say what was left out."""
    for index in range(12):
        (tmp_path / f"f{index}.py").write_text("pass")
    target, skipped = _bounded_target(tmp_path, cap=5)
    assert target != tmp_path
    assert skipped == 7
    assert len(list(target.rglob("*.py"))) == 5


def test_bounded_target_ignores_vendored_directories(tmp_path):
    (tmp_path / "real.py").write_text("pass")
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "vendor.py").write_text("pass")
    target, skipped = _bounded_target(tmp_path, cap=10)
    assert target == tmp_path
    assert skipped == 0


# --- skill-scanner -----------------------------------------------------------------------


def test_skill_findings_are_parsed_with_location_and_analyzer():
    """Criterion 4.2."""
    findings = parse_skill_findings(SKILL_FINDINGS)
    assert len(findings) == 2
    critical = next(f for f in findings if f.severity is Severity.CRITICAL)
    assert critical.analyzer == "static"
    assert critical.rule_id == "YARA_prompt_injection_generic"
    assert critical.file_path == "SKILL.md:7"
    assert "remediation:" in critical.detail


def test_skill_severity_counts_match_the_raw_payload():
    """Criterion 4.2 — parsed counts must agree with the stored artifact."""
    findings = parse_skill_findings(SKILL_FINDINGS)
    counts: dict[Severity, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    assert counts == {Severity.CRITICAL: 1, Severity.HIGH: 1}
    assert sum(counts.values()) == len(SKILL_FINDINGS["findings"])


def test_skill_scanner_verdict_is_honoured_not_rederived(policy):
    """Criterion 4.3.

    Even with zero blocking-severity findings, a scanner that says "not safe" must block: it
    already applied its own meta-analyzer filtering, and second-guessing that would discard
    information rather than add any.
    """
    outcome = gates.decide_scanner(policy, AssetType.SKILL, {}, scanner_says_safe=False)
    assert outcome.decision is Decision.NEEDS_DEEP_TESTING
    assert any("scanner verdict" in reason for reason in outcome.blocking_reasons)
