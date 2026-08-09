"""Structured (form) edits to policy documents.

The policy remains a YAML document — that is what gets hashed, versioned and displayed —
but most edits are a handful of numbers, and asking someone to hand-edit YAML to change a
threshold invites indentation accidents. This module applies a validated form payload to
the newest version's text using ruamel.yaml's round-trip mode, which preserves the
document's comments — the rationale written next to each gate survives a form edit.

The result goes through exactly the same validation and versioning as a raw edit: an
invalid form creates nothing, and a valid one becomes the next immutable version.
"""

from __future__ import annotations

import io

from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from app.models import AssetType


class GateForm(BaseModel):
    threshold: float
    samples: int = Field(ge=1)
    # A pinned core set survives a form edit untouched unless explicitly cleared, because
    # dropping it silently would change what a run measures without anyone deciding that.
    clear_sample_ids: bool = False


class LlmPolicyForm(BaseModel):
    judge_default_model: str = Field(min_length=1)
    judge_max_refusal_rate: float = Field(ge=0, le=1)
    gates: dict[str, GateForm]
    composite_weights: dict[str, float]
    weights_block_on_unsafe_file: bool
    weights_treat_unscanned_as_pass: bool


class ScannerPolicyForm(BaseModel):
    mode: str
    block_on: list[str]
    trust_scanner_verdict: bool
    severity_rollup_penalty: dict[str, int]


def _round_trip() -> YAML:
    # ruamel's default typ="rt" (round-trip) is built on its SAFE loader: it constructs
    # only CommentedMap/CommentedSeq and plain scalars, never arbitrary Python objects via
    # !!python tags — unlike PyYAML's unsafe yaml.load. Content here is also re-validated
    # against the registry before any version is created.
    yaml = YAML()
    yaml.preserve_quotes = True
    # Match the seed documents' style so diffs between versions stay minimal.
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


def apply_llm_form(current_text: str, form: LlmPolicyForm) -> str:
    yaml = _round_trip()
    data = yaml.load(current_text)

    judge = data.setdefault("judge", {})
    judge["default_model"] = form.judge_default_model
    judge["max_refusal_rate"] = form.judge_max_refusal_rate

    gates = data.setdefault("gates", {})
    for check_id, gate_form in form.gates.items():
        # Only known gates are touched; adding a gate is a raw-edit operation because it
        # needs metric/direction/description, which the form deliberately does not carry
        # (they are registry facts, not preferences).
        if check_id not in gates:
            continue
        gate = gates[check_id]
        gate["threshold"] = gate_form.threshold
        if gate_form.clear_sample_ids and "sample_ids" in gate:
            del gate["sample_ids"]
        # `samples` only governs when no core set is pinned, but it is kept current either
        # way so clearing a pin later falls back to a deliberate number.
        gate["samples"] = gate_form.samples

    weights = data.setdefault("composite_weights", {})
    for check_id, weight in form.composite_weights.items():
        if check_id in weights:
            weights[check_id] = weight

    supply = data.setdefault("weights", {})
    supply["block_on_unsafe_file"] = form.weights_block_on_unsafe_file
    supply["treat_unscanned_as_pass"] = form.weights_treat_unscanned_as_pass

    out = io.StringIO()
    yaml.dump(data, out)
    return out.getvalue()


def apply_scanner_form(current_text: str, form: ScannerPolicyForm) -> str:
    yaml = _round_trip()
    data = yaml.load(current_text)

    data["mode"] = form.mode
    data["block_on"] = list(form.block_on)
    data["trust_scanner_verdict"] = form.trust_scanner_verdict
    penalty = data.setdefault("severity_rollup_penalty", {})
    for severity, value in form.severity_rollup_penalty.items():
        penalty[severity] = value

    out = io.StringIO()
    yaml.dump(data, out)
    return out.getvalue()


def current_form_values(asset_type: AssetType, content: str) -> dict:
    """The form's initial values, read from a policy document."""
    yaml = _round_trip()
    data = yaml.load(content)
    if asset_type is AssetType.LLM:
        judge = data.get("judge") or {}
        return {
            "judge_default_model": judge.get("default_model", ""),
            "judge_max_refusal_rate": judge.get("max_refusal_rate", 0.05),
            "gates": {
                check_id: {
                    "metric": spec.get("metric"),
                    "direction": spec.get("direction"),
                    "threshold": spec.get("threshold"),
                    "samples": spec.get("samples", 20),
                    "sample_ids_count": len(spec.get("sample_ids") or []),
                    "description": str(spec.get("description", "")).strip(),
                }
                for check_id, spec in (data.get("gates") or {}).items()
            },
            "composite_weights": dict(data.get("composite_weights") or {}),
            "weights_block_on_unsafe_file": bool(
                (data.get("weights") or {}).get("block_on_unsafe_file", True)
            ),
            "weights_treat_unscanned_as_pass": bool(
                (data.get("weights") or {}).get("treat_unscanned_as_pass", False)
            ),
        }
    return {
        "mode": data.get("mode", "advisory"),
        "block_on": list(data.get("block_on") or []),
        "trust_scanner_verdict": bool(data.get("trust_scanner_verdict", True)),
        "severity_rollup_penalty": dict(data.get("severity_rollup_penalty") or {}),
    }
