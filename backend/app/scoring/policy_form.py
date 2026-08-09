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

from app.engines.registry import CHECKS_BY_ID, DEPTH_BY_KEY, DEPTH_PRESETS, checks_for
from app.models import AssetType


class GateForm(BaseModel):
    threshold: float
    samples: int = Field(ge=1)
    # A pinned core set survives a form edit untouched unless explicitly cleared, because
    # dropping it silently would change what a run measures without anyone deciding that.
    clear_sample_ids: bool = False
    # Include this benchmark in the suite. A benchmark that is registered in code but not
    # yet in the policy shows in the form as "available"; enabling it here adds a gate.
    # Metric and direction come from the registry, never the form — they are facts about
    # the benchmark, not preferences. Set false to remove a gate from the suite.
    enabled: bool = True
    # Composite weight, applied when the gate is enabled. Optional; defaults to a small
    # value so a newly-added benchmark contributes to the display score without dominating.
    weight: float = Field(default=0.1, ge=0)


class LlmPolicyForm(BaseModel):
    judge_default_model: str = Field(min_length=1)
    judge_max_refusal_rate: float = Field(ge=0, le=1)
    # Keyed by check id. Includes every registered benchmark; `enabled` says which are in
    # the suite, and each carries its own composite weight.
    gates: dict[str, GateForm]
    weights_block_on_unsafe_file: bool
    weights_treat_unscanned_as_pass: bool


class ScannerPolicyForm(BaseModel):
    mode: str
    block_on: list[str]
    trust_scanner_verdict: bool
    severity_rollup_penalty: dict[str, int]
    # Assessment coverage per scan. Editable because it is a trade-off, not a constant.
    max_source_files: int = Field(default=200, ge=1)


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
    weights = data.setdefault("composite_weights", {})

    for check_id, gate_form in form.gates.items():
        registered = CHECKS_BY_ID.get(check_id)
        # Only registered benchmarks can be in the suite; an unknown id is ignored rather
        # than written, so a stale client cannot invent a gate.
        if registered is None or registered.asset_type is not AssetType.LLM:
            continue

        if not gate_form.enabled:
            # Remove from the suite entirely, weight and all. Validation later ensures at
            # least one gate remains.
            gates.pop(check_id, None)
            weights.pop(check_id, None)
            continue

        gate = gates.get(check_id)
        if gate is None:
            # Enabling a benchmark that was not in the policy: add it, taking metric,
            # direction and description from the REGISTRY (facts, not form input).
            from ruamel.yaml.comments import CommentedMap

            gate = CommentedMap()
            gate["metric"] = registered.metric_name
            gate["direction"] = registered.direction.value
            gate["threshold"] = gate_form.threshold
            gate["samples"] = gate_form.samples
            if registered.description:
                gate["description"] = registered.description
            gates[check_id] = gate
        else:
            gate["threshold"] = gate_form.threshold
            if gate_form.clear_sample_ids and "sample_ids" in gate:
                del gate["sample_ids"]
            # `samples` only governs when no core set is pinned, but it is kept current
            # either way so clearing a pin later falls back to a deliberate number.
            gate["samples"] = gate_form.samples

        weights[check_id] = gate_form.weight

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
    data["max_source_files"] = form.max_source_files
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
        gates = data.get("gates") or {}
        weights = data.get("composite_weights") or {}

        # Every REGISTERED benchmark appears, enabled or not, so the form can both tune the
        # active suite and offer benchmarks that are available but not yet in it. Metric,
        # direction, description, intent and cost come from the registry.
        rows = {}
        for check in checks_for(AssetType.LLM):
            spec = gates.get(check.id) or {}
            enabled = check.id in gates
            # An ungated benchmark still needs a sensible sample count to offer, because that
            # value is what gets written the moment someone enables it. Defaulting to the
            # registry's `default_limit` would quietly add it at wiring-check depth; the
            # standard depth is the honest default for something entering the suite.
            standard = DEPTH_BY_KEY["good"].samples_for(check)
            rows[check.id] = {
                "enabled": enabled,
                "metric": check.metric_name,
                "direction": check.direction.value,
                "threshold": spec.get("threshold", 0.9),
                "samples": spec.get("samples", standard),
                "sample_ids_count": len(spec.get("sample_ids") or []),
                "weight": float(weights.get(check.id, 0.1)),
                "description": check.description,
                "needs_judge": check.needs_judge,
                "dataset_max": check.dataset_size or check.default_limit,
                # So the form can show what a change to `samples` costs, live.
                "calls_per_sample": check.calls_per_sample,
            }
        # Depth presets, with the totals they would produce for the ENABLED suite. Computed
        # here rather than in the UI so the slider can never show a number the backend would
        # not actually run.
        depth = []
        for preset in DEPTH_PRESETS:
            per_check, tests, calls = {}, 0, 0
            for check in checks_for(AssetType.LLM):
                if check.id not in gates:
                    continue
                n = preset.samples_for(check)
                per_check[check.id] = n
                tests += n
                calls += n * check.calls_per_sample
            depth.append(
                {
                    "key": preset.key,
                    "label": preset.label,
                    "blurb": preset.blurb,
                    "samples": preset.samples,
                    "per_check": per_check,
                    "total_tests": tests,
                    "total_calls": calls,
                }
            )

        return {
            "judge_default_model": judge.get("default_model", ""),
            "judge_max_refusal_rate": judge.get("max_refusal_rate", 0.05),
            "depth_presets": depth,
            "gates": rows,
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
        "max_source_files": int(data.get("max_source_files", 200)),
        "severity_rollup_penalty": dict(data.get("severity_rollup_penalty") or {}),
    }
