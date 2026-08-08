"""Loading the governance policy.

The policy is data, never code. It is content-hashed on load so every run records exactly
which policy produced its decision — a threshold edited next month must not silently rewrite
the meaning of a decision made today.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.models import AssetType, Direction, Severity


@dataclass(frozen=True)
class Gate:
    """One benchmark's threshold, on that benchmark's own headline metric."""

    check_id: str
    metric: str
    direction: Direction
    threshold: float
    description: str = ""

    def passes(self, value: float) -> bool:
        if self.direction is Direction.HIGHER_IS_BETTER:
            return value >= self.threshold
        return value <= self.threshold


@dataclass(frozen=True)
class ScannerPolicy:
    """Severity rule for scanner-backed asset classes.

    `advisory` exists because we have no false-positive baseline yet: an untuned severity
    rule must not be trusted to approve anything, so it can only ever withhold approval.
    """

    mode: str  # "advisory" | "gating"
    block_on: frozenset[Severity]
    trust_scanner_verdict: bool

    @property
    def is_advisory(self) -> bool:
        return self.mode == "advisory"


@dataclass(frozen=True)
class Policy:
    version: str
    content_hash: str
    judge_default_model: str
    judge_max_refusal_rate: float
    llm_gates: dict[str, Gate]
    composite_weights: dict[str, float]
    weights_block_on_unsafe_file: bool
    weights_treat_unscanned_as_pass: bool
    scanner: dict[AssetType, ScannerPolicy]
    severity_penalty: dict[Severity, int]
    raw: dict[str, Any]

    def gates_for(self, asset_type: AssetType) -> dict[str, Gate]:
        return self.llm_gates if asset_type is AssetType.LLM else {}

    def scanner_policy(self, asset_type: AssetType) -> ScannerPolicy | None:
        return self.scanner.get(asset_type)


def _parse_gate(check_id: str, spec: dict[str, Any]) -> Gate:
    return Gate(
        check_id=check_id,
        metric=spec["metric"],
        direction=Direction(spec["direction"]),
        threshold=float(spec["threshold"]),
        description=str(spec.get("description", "")).strip(),
    )


def load_policy(path: Path) -> Policy:
    text = path.read_text()
    data = yaml.safe_load(text)
    content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

    llm = data.get("llm") or {}
    judge = data.get("judge") or {}
    weights = data.get("weights") or {}

    scanner: dict[AssetType, ScannerPolicy] = {}
    for asset_type in (AssetType.MCP, AssetType.SKILL):
        spec = data.get(asset_type.value) or {}
        scanner[asset_type] = ScannerPolicy(
            mode=str(spec.get("mode", "advisory")),
            block_on=frozenset(Severity(s) for s in spec.get("block_on", ["critical", "high"])),
            trust_scanner_verdict=bool(spec.get("trust_scanner_verdict", True)),
        )

    return Policy(
        version=str(data.get("version", "0")),
        content_hash=content_hash,
        judge_default_model=str(judge.get("default_model", "qwen35")),
        judge_max_refusal_rate=float(judge.get("max_refusal_rate", 0.05)),
        llm_gates={
            check_id: _parse_gate(check_id, spec)
            for check_id, spec in (llm.get("gates") or {}).items()
        },
        composite_weights={k: float(v) for k, v in (llm.get("composite_weights") or {}).items()},
        weights_block_on_unsafe_file=bool(weights.get("block_on_unsafe_file", True)),
        weights_treat_unscanned_as_pass=bool(weights.get("treat_unscanned_as_pass", False)),
        scanner=scanner,
        severity_penalty={
            Severity(k): int(v) for k, v in (data.get("severity_rollup_penalty") or {}).items()
        },
        raw=data,
    )


@lru_cache
def get_policy(path: Path) -> Policy:
    return load_policy(path)
