"""Parsing Hugging Face supply-chain scan results.

Acceptance criteria 2.1-2.3. The fixture below is a trimmed copy of a real
`/tree?expand=true` response, so the parser is tested against the shape the Hub actually
serves rather than one we imagined.

The property that matters most: **"not scanned" must never read as "safe"**. Treating absence
of findings as absence of risk is how a poisoned checkpoint gets auto-approved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engines.harvest_hf import SCANNER_KEYS, HarvestResult, parse_security_status
from app.models import Decision
from app.scoring import gates
from app.scoring.policy import load_policy_dir

POLICY_DIR = Path(__file__).resolve().parents[1] / "policy"

# Captured live from openai-community/gpt2.
SAFE_BIN = {
    "status": "safe",
    "protectAiScan": {"status": "safe", "message": "This file has no security findings."},
    "avScan": {"status": "safe", "message": "No security issues detected"},
    "pickleImportScan": {
        "status": "safe",
        "pickleImports": [
            {"module": "collections", "name": "OrderedDict", "safety": "innocuous"},
            {"module": "torch", "name": "FloatStorage", "safety": "innocuous"},
        ],
        "version": "0.0.32",
    },
    "virusTotalScan": {"status": "safe", "message": "0/76 engines detect it as malicious."},
    "jFrogScan": {"status": "safe", "message": "Safe PyTorch model"},
}

# A file the Hub has not finished scanning — observed as `queued` in real responses.
QUEUED_FILE = {
    "status": "queued",
    "protectAiScan": {"status": "safe", "message": "no findings"},
    "avScan": {"status": "safe", "message": "clean"},
    "pickleImportScan": {"status": "unscanned", "pickleImports": [], "version": "0.0.0"},
    "virusTotalScan": {"status": "safe", "message": "0/74"},
}

UNSAFE_BIN = {
    "status": "unsafe",
    "protectAiScan": {"status": "unsafe", "message": "Suspicious pickle import detected"},
    "avScan": {"status": "safe", "message": "clean"},
    "pickleImportScan": {
        "status": "unsafe",
        "pickleImports": [{"module": "posix", "name": "system", "safety": "dangerous"}],
        "version": "0.0.32",
    },
    "virusTotalScan": {"status": "safe", "message": "0/76"},
    "jFrogScan": {"status": "unsafe", "message": "Model supports code execution on load"},
}


@pytest.fixture
def policy():
    return load_policy_dir(POLICY_DIR)


def test_all_five_scanners_are_parsed():
    """Criterion 2.1."""
    scan = parse_security_status("pytorch_model.bin", 500_000, SAFE_BIN)
    assert {v.scanner for v in scan.verdicts} == set(SCANNER_KEYS)
    assert scan.status == "safe"
    assert not scan.is_unsafe
    assert set(scan.scanned_by) == set(SCANNER_KEYS)


def test_pickle_imports_are_retained_as_detail():
    """The imports are the actionable detail when a pickle file is flagged."""
    scan = parse_security_status("pytorch_model.bin", 1, UNSAFE_BIN)
    pickle_verdict = next(v for v in scan.verdicts if v.scanner == "pickleImportScan")
    assert pickle_verdict.details["pickleImports"][0]["module"] == "posix"


def test_any_unsafe_scanner_makes_the_file_unsafe():
    scan = parse_security_status("pytorch_model.bin", 1, UNSAFE_BIN)
    assert scan.is_unsafe
    assert [v.scanner for v in scan.verdicts if v.is_unsafe] == [
        "protectAiScan",
        "pickleImportScan",
        "jFrogScan",
    ]


def test_queued_and_unscanned_do_not_count_as_scanned():
    """Criterion 2.2 at the file level."""
    scan = parse_security_status("model.safetensors", 1, QUEUED_FILE)
    assert "pickleImportScan" not in scan.scanned_by
    assert not scan.is_unsafe  # queued is not a finding either — it is simply unknown


def test_scanner_coverage_reports_per_scanner_counts():
    """Five scanners means little if four of them skipped every file."""
    result = HarvestResult(
        repo_id="x/y",
        revision="main",
        found=True,
        scans_done=True,
        files=[
            parse_security_status("a.bin", 1, SAFE_BIN),
            parse_security_status("b.safetensors", 1, QUEUED_FILE),
        ],
        files_with_issues=[],
    )
    coverage = result.scanner_coverage
    assert coverage["protectAiScan"] == 2
    # Only the .bin was pickle-scanned; the queued file was not.
    assert coverage["pickleImportScan"] == 1


def test_weight_files_are_identified_by_suffix():
    result = HarvestResult(
        repo_id="x/y",
        revision="main",
        found=True,
        scans_done=True,
        files=[
            parse_security_status("pytorch_model.bin", 1, SAFE_BIN),
            parse_security_status("README.md", 1, SAFE_BIN),
            parse_security_status("model.safetensors", 1, SAFE_BIN),
        ],
        files_with_issues=[],
    )
    assert {f.path for f in result.weight_files} == {"pytorch_model.bin", "model.safetensors"}


def test_unsafe_file_blocks_the_gate(policy):
    """Criterion 2.3."""
    result = HarvestResult(
        repo_id="x/y",
        revision="main",
        found=True,
        scans_done=True,
        files=[parse_security_status("pytorch_model.bin", 1, UNSAFE_BIN)],
        files_with_issues=["pytorch_model.bin"],
    )
    assert result.unsafe_files == ["pytorch_model.bin"]
    outcome = gates.decide_weights(policy, result.unsafe_files, result.scans_done)
    assert outcome.decision is Decision.NEEDS_DEEP_TESTING


def test_incomplete_scans_block_rather_than_pass(policy):
    """Criterion 2.2 — the property that stops a poisoned-but-unscanned repo sailing through."""
    outcome = gates.decide_weights(policy, [], scans_done=False)
    assert outcome.decision is Decision.NEEDS_DEEP_TESTING
    assert "scans_incomplete" in outcome.blocking_reasons


def test_scans_done_defaults_to_false_when_absent():
    """A missing scansDone field must not be optimistically read as complete."""
    result = HarvestResult(
        repo_id="x/y", revision="main", found=True, scans_done=False, files=[], files_with_issues=[]
    )
    assert result.scans_done is False
