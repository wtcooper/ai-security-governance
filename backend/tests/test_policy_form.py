"""Form edits to policy documents: same rigor as raw edits, none of the YAML hazards.

The properties that matter:

* A form edit changes exactly the fields it names — and the document's comments survive,
  because the rationale written next to a gate is part of the policy's value.
* A pinned core set is never dropped implicitly; clearing it is an explicit form action.
* Form output passes the same validation as a raw edit, so the form cannot construct a
  policy the editor would have rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import AssetType
from app.scoring.policy import validate_class_content
from app.scoring.policy_form import (
    GateForm,
    LlmPolicyForm,
    ScannerPolicyForm,
    apply_llm_form,
    apply_scanner_form,
    current_form_values,
)

POLICY_DIR = Path(__file__).resolve().parents[1] / "policy"


def _llm_form(**overrides) -> LlmPolicyForm:
    base = current_form_values(AssetType.LLM, (POLICY_DIR / "llm.yaml").read_text())
    form = LlmPolicyForm(
        judge_default_model=base["judge_default_model"],
        judge_max_refusal_rate=base["judge_max_refusal_rate"],
        gates={
            check_id: GateForm(threshold=g["threshold"], samples=g["samples"])
            for check_id, g in base["gates"].items()
        },
        composite_weights=base["composite_weights"],
        weights_block_on_unsafe_file=base["weights_block_on_unsafe_file"],
        weights_treat_unscanned_as_pass=base["weights_treat_unscanned_as_pass"],
    )
    return form.model_copy(update=overrides)


def test_threshold_edit_changes_only_that_field_and_keeps_comments():
    text = (POLICY_DIR / "llm.yaml").read_text()
    form = _llm_form()
    form.gates["cyse4_mitre"].threshold = 0.8

    edited = apply_llm_form(text, form)
    data = validate_class_content(AssetType.LLM, edited)

    assert data["gates"]["cyse4_mitre"]["threshold"] == 0.8
    # Everything else held.
    assert data["gates"]["cyse4_instruct"]["threshold"] == 0.25
    assert data["judge"]["default_model"] == "qwen35"
    # The comments — the document's rationale — survived the round trip.
    for marker in (
        "# A judge that refuses to grade cyber content",
        "# Metric is `refusal_rate`, not `accuracy`",
        "# Two judged model calls per sample",
    ):
        assert marker in edited, f"comment lost in round trip: {marker}"


def test_form_output_passes_the_same_validation_as_raw_edits():
    text = (POLICY_DIR / "llm.yaml").read_text()
    edited = apply_llm_form(text, _llm_form(judge_max_refusal_rate=0.1))
    data = validate_class_content(AssetType.LLM, edited)
    assert data["judge"]["max_refusal_rate"] == 0.1


def test_pinned_core_set_survives_unless_explicitly_cleared():
    text = (POLICY_DIR / "llm.yaml").read_text().replace(
        "threshold: 0.85\n    samples: 20",
        "threshold: 0.85\n    samples: 20\n    sample_ids: [id_a, id_b]",
    )

    # Untouched by default.
    kept = apply_llm_form(text, _llm_form())
    kept_data = validate_class_content(AssetType.LLM, kept)
    assert kept_data["gates"]["cyse4_multilingual_prompt_injection"]["sample_ids"] == [
        "id_a",
        "id_b",
    ]

    # Cleared only on request, at which point `samples` governs again.
    form = _llm_form()
    form.gates["cyse4_multilingual_prompt_injection"].clear_sample_ids = True
    form.gates["cyse4_multilingual_prompt_injection"].samples = 30
    cleared = apply_llm_form(text, form)
    cleared_data = validate_class_content(AssetType.LLM, cleared)
    gate = cleared_data["gates"]["cyse4_multilingual_prompt_injection"]
    assert "sample_ids" not in gate
    assert gate["samples"] == 30


def test_unknown_gate_in_the_form_is_ignored_not_added():
    """Adding a gate needs registry facts the form does not carry; it must not sneak in."""
    text = (POLICY_DIR / "llm.yaml").read_text()
    form = _llm_form()
    form.gates["cyse4_made_up"] = GateForm(threshold=0.5, samples=10)
    edited = apply_llm_form(text, form)
    data = validate_class_content(AssetType.LLM, edited)
    assert "cyse4_made_up" not in data["gates"]


def test_scanner_form_flips_mode_and_keeps_comments():
    text = (POLICY_DIR / "mcp.yaml").read_text()
    form = ScannerPolicyForm(
        mode="gating",
        block_on=["critical", "high", "medium"],
        trust_scanner_verdict=True,
        severity_rollup_penalty={"critical": 40, "high": 20, "medium": 8, "low": 2, "info": 0},
    )
    edited = apply_scanner_form(text, form)
    data = validate_class_content(AssetType.MCP, edited)
    assert data["mode"] == "gating"
    assert data["block_on"] == ["critical", "high", "medium"]
    assert "# NOTE: mcp-scanner has no CRITICAL severity" in edited


def test_scanner_form_with_invalid_mode_fails_validation():
    text = (POLICY_DIR / "skill.yaml").read_text()
    form = ScannerPolicyForm(
        mode="sometimes",
        block_on=["high"],
        trust_scanner_verdict=True,
        severity_rollup_penalty={"critical": 40, "high": 20, "medium": 8, "low": 2, "info": 0},
    )
    edited = apply_scanner_form(text, form)
    with pytest.raises(Exception, match="mode must be"):
        validate_class_content(AssetType.SKILL, edited)


def test_current_form_values_round_trip():
    values = current_form_values(AssetType.LLM, (POLICY_DIR / "llm.yaml").read_text())
    assert values["judge_default_model"] == "qwen35"
    assert values["gates"]["cyse4_mitre"]["samples"] == 10
    assert values["gates"]["cyse4_mitre"]["metric"] == "accuracy"
    assert values["composite_weights"]["agentdojo"] == 0.25

    scanner = current_form_values(AssetType.MCP, (POLICY_DIR / "mcp.yaml").read_text())
    assert scanner["mode"] == "advisory"
    assert scanner["block_on"] == ["critical", "high"]
    assert scanner["severity_rollup_penalty"]["critical"] == 40
