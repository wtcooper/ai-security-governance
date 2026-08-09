"""SQLModel tables.

All DB access goes through SQLModel so swapping SQLite for a hosted Postgres is a
connection-string change rather than a rewrite.

Two shapes here carry governance meaning and are worth reading carefully:

* ``Score.gated`` — benchmarks emit more than one metric (AgentDojo also reports benign
  utility; the CyberSecEval code tasks also report BLEU). Only the benchmark's single
  headline metric is thresholded. Everything else is stored with ``gated=False`` so a
  reviewer can see it, and the gate evaluator never reads it.

* ``Run.engine_version`` / ``Run.ruleset_version`` — scanner findings shift when Cisco
  ships new rules. Recording both means a later spike in findings can be attributed to a
  ruleset change rather than to the artifacts, which is what makes hand-tuning the
  severity rule possible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AssetType(StrEnum):
    LLM = "llm"
    MCP = "mcp"
    SKILL = "skill"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class Decision(StrEnum):
    AUTO_APPROVE = "auto_approve"
    NEEDS_DEEP_TESTING = "needs_deep_testing"
    ERROR = "error"


class Provenance(StrEnum):
    """Where a score came from. Displayed on every score in the UI."""

    PUBLISHED = "published"  # vendor system card / paper, with a source URL
    HARVESTED = "harvested"  # pulled from a structured third-party source (e.g. HF scans)
    SELF_RUN = "self_run"  # we computed it


class Direction(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class PolicyVersion(SQLModel, table=True):
    """One immutable version of one asset class's governance policy.

    Rows are only ever inserted — editing a policy means writing version n+1, and the newest
    version per asset class is the one applied to new runs. Old rows are the audit trail
    that makes a historical run's recorded (version, hash) pair resolvable to actual
    content, which is the whole point of versioning.
    """

    __tablename__ = "policy_version"

    id: int | None = Field(default=None, primary_key=True)
    asset_type: AssetType = Field(index=True)
    # Monotonic per asset_type, starting at 1.
    version: int = Field(index=True)
    # YAML text, kept as authored (comments included) so the policy stays a readable
    # document rather than a normalised blob.
    content: str
    content_hash: str
    # Why this version exists, supplied at save time.
    note: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class Asset(SQLModel, table=True):
    __tablename__ = "asset"

    id: int | None = Field(default=None, primary_key=True)
    type: AssetType = Field(index=True)
    name: str = Field(index=True)
    # Gateway alias for an LLM; repo URL or upload name for MCP/skills.
    identifier: str
    provider: str | None = None
    hf_repo_id: str | None = None
    source_url: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class Run(SQLModel, table=True):
    __tablename__ = "run"

    id: int | None = Field(default=None, primary_key=True)
    asset_id: int = Field(foreign_key="asset.id", index=True)
    status: RunStatus = Field(default=RunStatus.PENDING, index=True)

    # The policy that produced the decision, content-hashed so a historical run stays
    # interpretable after policy.yaml is edited.
    policy_version: str | None = None
    policy_hash: str | None = None

    decision: Decision | None = Field(default=None, index=True)
    # Why the decision landed where it did, human-readable.
    decision_reason: str | None = None

    # Which models did the work. Recorded so a wiring-proof run against `mock-judge` can
    # never be mistaken for a real evaluation.
    gateway_model: str | None = None
    judge_model: str | None = None
    # Gated on: the scorer's own count of unclassifiable judge verdicts, as a rate.
    judge_unresolved_rate: float | None = None
    # Advisory only: refusal phrasing seen in explanations. Cannot separate a judge refusal
    # from a subject refusal, so it informs a human but never fails a run.
    judge_refusal_rate: float | None = None

    # Scanner provenance (MCP/skill runs).
    engine_version: str | None = None
    ruleset_version: str | None = None

    # A per-run sample-count override from the submit form. Nullable and visibly flagged in
    # the UI when set: an override exists for wiring checks, and a wiring check must never
    # read as a governance run.
    sample_override: int | None = None

    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None
    error: str | None = None


class Score(SQLModel, table=True):
    __tablename__ = "score"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    check_id: str = Field(index=True)
    metric: str

    raw_value: float | None = None
    normalized: float | None = None  # 0-100, for display/ordering

    # Only meaningful when gated is True.
    direction: Direction | None = None
    threshold: float | None = None
    gated: bool = Field(default=False)
    passed: bool | None = None

    provenance: Provenance = Field(default=Provenance.SELF_RUN)
    source_url: str | None = None
    model_used: str | None = None

    # Samples the judge declined to grade. Excluded from the denominator rather than
    # counted as a pass, because counting them as passes inflates refusal-style metrics.
    unresolved_samples: int | None = None
    total_samples: int | None = None


class Finding(SQLModel, table=True):
    __tablename__ = "finding"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    analyzer: str = Field(index=True)
    severity: Severity = Field(index=True)
    rule_id: str | None = None
    title: str
    detail: str | None = None
    file_path: str | None = None


class Artifact(SQLModel, table=True):
    __tablename__ = "artifact"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    kind: str  # "inspect_log" | "scanner_json" | "scanner_sarif" | "hf_scan_json"
    path: str
