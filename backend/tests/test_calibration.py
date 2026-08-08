"""Calibration scoring logic.

Acceptance criteria 6.2-6.6. Pure-logic tests: they assert how a case is scored against its
label, which is the part that must be right before any measured number means anything.
"""

from __future__ import annotations

import json

from app.engines.calibration import CalibrationReport, CaseResult, skill_cases


def _case(**kwargs) -> CaseResult:
    defaults = dict(
        corpus="mcp",
        category="data-exfiltration",
        name="x",
        expected_malicious=True,
        blocked=True,
        decision="needs_deep_testing",
    )
    return CaseResult(**{**defaults, "**": None}.pop("**", None) or {**defaults, **kwargs})


def test_confusion_matrix_cells():
    assert _case(expected_malicious=True, blocked=True).outcome == "true_positive"
    assert _case(expected_malicious=True, blocked=False).outcome == "false_negative"
    assert _case(expected_malicious=False, blocked=True).outcome == "false_positive"
    assert _case(expected_malicious=False, blocked=False).outcome == "true_negative"


def test_an_errored_case_is_neither_a_hit_nor_a_miss():
    """Criterion 6.6 — a scan that failed must not be counted as a detection or a clean pass."""
    assert _case(error="boom").outcome == "error"


def _report(cases: list[CaseResult]) -> CalibrationReport:
    return CalibrationReport(
        started_at="now",
        corpus_revisions={"mcp": "abc1234"},
        policy_version="1",
        policy_hash="deadbeef",
        scanner_model="gemma4",
        cases=cases,
    )


def test_recall_and_fp_rate_are_computed_per_corpus():
    """Criterion 6.3 / 6.4."""
    report = _report(
        [
            _case(expected_malicious=True, blocked=True),
            _case(expected_malicious=True, blocked=False, category="backdoor"),
            _case(expected_malicious=False, blocked=False, category="remote-benign"),
        ]
    )
    stats = report.summary()["mcp"]
    assert stats["malicious_total"] == 2
    assert stats["recall"] == 0.5
    assert stats["benign_total"] == 1
    assert stats["false_positive_rate"] == 0.0
    # Criterion 6.3: the missed category must be named, not just counted.
    assert stats["per_category_misses"] == ["backdoor"]


def test_thin_false_positive_denominator_is_flagged():
    """Criterion 6.4 — a rate over 3 benign cases must not read as a real FP rate."""
    report = _report([_case(expected_malicious=False, blocked=False) for _ in range(3)])
    assert report.summary()["mcp"]["fp_denominator_warning"] is not None


def test_no_benign_cases_yields_no_fp_rate_rather_than_zero():
    """Zero would claim a perfect FP rate from no evidence at all."""
    report = _report([_case(expected_malicious=True, blocked=True)])
    assert report.summary()["mcp"]["false_positive_rate"] is None


def test_no_malicious_cases_yields_no_recall_rather_than_zero():
    report = _report([_case(expected_malicious=False, blocked=False)])
    assert report.summary()["mcp"]["recall"] is None


def test_skill_labels_are_read_from_the_corpus(tmp_path):
    """Criterion 6.2 — labels come from _expected.json and the directory split, not guesses."""
    skills = tmp_path / "evals" / "skills" / "data-exfiltration" / "leaky"
    skills.mkdir(parents=True)
    (skills / "_expected.json").write_text(json.dumps({"expected_safe": False}))

    safe = tmp_path / "evals" / "skills" / "safe-skills" / "tidy"
    safe.mkdir(parents=True)
    (safe / "_expected.json").write_text(json.dumps({"expected_safe": True}))

    for label in ("safe", "malicious"):
        d = tmp_path / "evals" / "test_skills" / label / f"{label}-one"
        d.mkdir(parents=True)

    cases = skill_cases(tmp_path)
    by_name = {name: malicious for _, name, _, malicious in cases}
    assert by_name["leaky"] is True
    assert by_name["tidy"] is False
    assert by_name["malicious-one"] is True
    assert by_name["safe-one"] is False


def test_advisory_mode_is_not_counted_as_a_detection():
    """Criterion 6.5 — the load-bearing detail of this whole measurement.

    Advisory mode blocks every scan, so if `advisory_mode` counted as a blocking reason the
    calibration would report 100% recall against an empty scanner. Detection has to mean a real
    finding, which is why `_scan_case` filters that reason out before deciding `blocked`.
    """
    import inspect as _inspect

    from app.engines import calibration

    source = _inspect.getsource(calibration._scan_case)
    assert 'r != "advisory_mode"' in source, (
        "advisory_mode must be excluded from blocking reasons, or recall measures the mode "
        "rather than detection"
    )
