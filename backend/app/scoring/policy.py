"""Loading, validating and versioning the governance policies.

The policy is data, never code. Each asset class (llm / mcp / skill) has its own policy
document, stored in the database as an immutable sequence of versions: every edit inserts a
new version, the newest version is the one applied to new runs, and older versions stay
readable so a historical run's recorded (version, hash) pair always resolves to real
content. The YAML files under backend/policy/ exist only to seed an empty database.

Validation is strict on purpose. A policy typo that silently drops a gate is a governance
failure, not a formatting nit — so unknown keys, unknown check ids, and metrics that
disagree with the registry are rejected at save time with a specific error, and no version
is created.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engines.registry import CHECKS_BY_ID
from app.models import AssetType, Direction, PolicyVersion, Severity


class PolicyValidationError(ValueError):
    """Raised when policy content is structurally wrong. The message names the problem."""


# Keys that older policy versions legitimately contain and current ones must not.
#
# Immutable versioning only means something if a historical document still LOADS: a run records
# the version that governed it, and resolving that version has to keep working forever. So a
# retired key is ignored when READING a stored document and rejected when WRITING a new one —
# history stays readable, and the retired concept cannot return through the form or the API.
#
# `mode` was the advisory/gating switch. It is gone: a finding at a blocking severity means the
# submission requires review, and the judgement is in choosing which severities those are.
LEGACY_SCANNER_KEYS = frozenset({"mode"})


@dataclass(frozen=True)
class Gate:
    """One benchmark's threshold, on that benchmark's own headline metric."""

    check_id: str
    metric: str
    direction: Direction
    threshold: float
    # How many test cases a run draws from the dataset (its first N — deterministic).
    samples: int = 20
    # A fixed, explicit core set. When non-empty it wins over `samples`: the run executes
    # exactly these dataset sample ids, which is what makes results repeatable across runs
    # and comparable across models. Changing the set is a policy edit, never a re-roll.
    sample_ids: tuple[str, ...] = ()
    description: str = ""

    def passes(self, value: float) -> bool:
        if self.direction is Direction.HIGHER_IS_BETTER:
            return value >= self.threshold
        return value <= self.threshold

    @property
    def planned_samples(self) -> int:
        return len(self.sample_ids) if self.sample_ids else self.samples


@dataclass(frozen=True)
class ScannerPolicy:
    """Severity rule for scanner-backed asset classes.

    One rule: a finding at a blocking severity means the submission requires review. There is
    no second decision mode — the judgement is in choosing which severities block, which is a
    policy edit.
    """

    block_on: frozenset[Severity]
    trust_scanner_verdict: bool
    severity_penalty: dict[Severity, int] = field(default_factory=dict)
    # How many source files the behavioral analyzer examines in one scan. Governed rather than
    # hard-coded: it trades assessment coverage against wall clock, which is a decision for
    # whoever owns the policy, not a constant chosen during development.
    max_source_files: int = 5000


@dataclass(frozen=True)
class ClassMeta:
    """Which version of a class policy a Policy object was built from."""

    version: str
    content_hash: str


@dataclass(frozen=True)
class Policy:
    meta: dict[AssetType, ClassMeta]
    judge_default_model: str
    judge_max_refusal_rate: float
    llm_gates: dict[str, Gate]
    composite_weights: dict[str, float]
    weights_block_on_unsafe_file: bool
    weights_treat_unscanned_as_pass: bool
    scanner: dict[AssetType, ScannerPolicy]
    raw: dict[str, Any]

    def gates_for(self, asset_type: AssetType) -> dict[str, Gate]:
        return self.llm_gates if asset_type is AssetType.LLM else {}

    def scanner_policy(self, asset_type: AssetType) -> ScannerPolicy | None:
        return self.scanner.get(asset_type)

    def meta_for(self, asset_type: AssetType) -> ClassMeta:
        return self.meta[asset_type]

    # Compatibility accessors. Callers that predate per-class policies read a single
    # version/hash; give them the LLM class's, which is what they were reading before.
    @property
    def version(self) -> str:
        return self.meta[AssetType.LLM].version

    @property
    def content_hash(self) -> str:
        return self.meta[AssetType.LLM].content_hash

    @property
    def severity_penalty(self) -> dict[Severity, int]:
        return self.scanner[AssetType.MCP].severity_penalty


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# --- validation ---------------------------------------------------------------------------


def _require_mapping(data: Any, what: str) -> dict:
    if not isinstance(data, dict):
        raise PolicyValidationError(f"{what} must be a YAML mapping, got {type(data).__name__}")
    return data


def _reject_unknown_keys(data: dict, allowed: set[str], what: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise PolicyValidationError(
            f"{what} has unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}"
        )


def _parse_llm_doc(text: str) -> dict[str, Any]:
    """Parse + validate an LLM policy document. Returns the loaded data."""
    data = _require_mapping(yaml.safe_load(text), "LLM policy")
    _reject_unknown_keys(data, {"judge", "gates", "composite_weights", "weights"}, "LLM policy")

    judge = _require_mapping(data.get("judge") or {}, "judge")
    _reject_unknown_keys(judge, {"default_model", "max_refusal_rate"}, "judge")
    rate = judge.get("max_refusal_rate", 0.05)
    if not isinstance(rate, (int, float)) or not 0 <= float(rate) <= 1:
        raise PolicyValidationError(f"judge.max_refusal_rate must be a number in [0,1], got {rate!r}")

    gates = _require_mapping(data.get("gates") or {}, "gates")
    if not gates:
        raise PolicyValidationError("LLM policy defines no gates; nothing would be evaluated")

    for check_id, spec in gates.items():
        registered = CHECKS_BY_ID.get(check_id)
        if registered is None:
            raise PolicyValidationError(
                f"gate {check_id!r} is not a registered benchmark; known: {sorted(CHECKS_BY_ID)}"
            )
        spec = _require_mapping(spec, f"gate {check_id!r}")
        _reject_unknown_keys(
            spec,
            {"metric", "direction", "threshold", "samples", "sample_ids", "description"},
            f"gate {check_id!r}",
        )
        # The registry is the ground truth for what a benchmark reports and which way it
        # runs — a policy that disagrees is a typo, and this exact class of mismatch has
        # produced a real bug before (cyse4_mitre_frr gated on the wrong metric).
        if spec.get("metric") != registered.metric_name:
            raise PolicyValidationError(
                f"gate {check_id!r}: metric must be {registered.metric_name!r} "
                f"(what the benchmark reports), got {spec.get('metric')!r}"
            )
        if spec.get("direction") != registered.direction.value:
            raise PolicyValidationError(
                f"gate {check_id!r}: direction must be {registered.direction.value!r}, "
                f"got {spec.get('direction')!r}"
            )
        threshold = spec.get("threshold")
        if not isinstance(threshold, (int, float)) or not 0 <= float(threshold) <= 1:
            raise PolicyValidationError(
                f"gate {check_id!r}: threshold must be a number in [0,1] "
                f"(all metrics are stored as 0-1 rates), got {threshold!r}"
            )
        samples = spec.get("samples", 20)
        if not isinstance(samples, int) or isinstance(samples, bool) or samples < 1:
            raise PolicyValidationError(
                f"gate {check_id!r}: samples must be a positive integer, got {samples!r}"
            )
        sample_ids = spec.get("sample_ids")
        if sample_ids is not None:
            if (
                not isinstance(sample_ids, list)
                or not sample_ids
                or not all(isinstance(s, str) and s for s in sample_ids)
            ):
                raise PolicyValidationError(
                    f"gate {check_id!r}: sample_ids must be a non-empty list of id strings"
                )
            if len(set(sample_ids)) != len(sample_ids):
                raise PolicyValidationError(f"gate {check_id!r}: sample_ids contains duplicates")

    weights = _require_mapping(data.get("composite_weights") or {}, "composite_weights")
    for check_id, weight in weights.items():
        if check_id not in CHECKS_BY_ID:
            raise PolicyValidationError(
                f"composite_weights names unknown benchmark {check_id!r}"
            )
        if not isinstance(weight, (int, float)) or float(weight) < 0:
            raise PolicyValidationError(
                f"composite_weights[{check_id!r}] must be a non-negative number, got {weight!r}"
            )

    supply = _require_mapping(data.get("weights") or {}, "weights")
    _reject_unknown_keys(
        supply, {"block_on_unsafe_file", "treat_unscanned_as_pass"}, "weights"
    )
    return data


def _parse_scanner_doc(
    asset_type: AssetType, text: str, strict: bool = True
) -> dict[str, Any]:
    """Parse + validate an MCP/skill policy document. Returns the loaded data.

    `strict` is False when loading a STORED version, so a retired key in a historical document
    does not make that version — and every run recorded against it — unloadable.
    """
    what = f"{asset_type.value} policy"
    data = _require_mapping(yaml.safe_load(text), what)
    if not strict:
        data = {key: value for key, value in data.items() if key not in LEGACY_SCANNER_KEYS}
    _reject_unknown_keys(
        data,
        {
            "block_on",
            "trust_scanner_verdict",
            "severity_rollup_penalty",
            "max_source_files",
        },
        what,
    )

    block_on = data.get("block_on", ["critical", "high"])
    valid = {s.value for s in Severity}
    if not isinstance(block_on, list) or not block_on or not set(block_on) <= valid:
        raise PolicyValidationError(
            f"{what}: block_on must be a non-empty list drawn from {sorted(valid)}, got {block_on!r}"
        )

    cap = data.get("max_source_files", 200)
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise PolicyValidationError(
            f"{what}: max_source_files must be a positive integer, got {cap!r}"
        )

    penalty = _require_mapping(data.get("severity_rollup_penalty") or {}, "severity_rollup_penalty")
    for key, value in penalty.items():
        if key not in valid:
            raise PolicyValidationError(
                f"{what}: severity_rollup_penalty names unknown severity {key!r}"
            )
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PolicyValidationError(
                f"{what}: severity_rollup_penalty[{key!r}] must be a non-negative integer"
            )
    return data


def validate_class_content(
    asset_type: AssetType, text: str, strict: bool = True
) -> dict[str, Any]:
    """Validate a policy document for an asset class. Raises PolicyValidationError.

    Strict by default: anything being SAVED must be current. Pass strict=False to load a stored
    version, which may predate a key's retirement and must still resolve.
    """
    try:
        if asset_type is AssetType.LLM:
            return _parse_llm_doc(text)
        return _parse_scanner_doc(asset_type, text, strict=strict)
    except yaml.YAMLError as exc:
        raise PolicyValidationError(f"not valid YAML: {exc}") from exc


# --- building the runtime Policy object ---------------------------------------------------


def _gate_from_spec(check_id: str, spec: dict[str, Any]) -> Gate:
    return Gate(
        check_id=check_id,
        metric=spec["metric"],
        direction=Direction(spec["direction"]),
        threshold=float(spec["threshold"]),
        samples=int(spec.get("samples", 20)),
        sample_ids=tuple(spec.get("sample_ids") or ()),
        description=str(spec.get("description", "")).strip(),
    )


def _scanner_from_data(data: dict[str, Any]) -> ScannerPolicy:
    return ScannerPolicy(
        block_on=frozenset(Severity(s) for s in data.get("block_on", ["critical", "high"])),
        trust_scanner_verdict=bool(data.get("trust_scanner_verdict", True)),
        severity_penalty={
            Severity(k): int(v)
            for k, v in (data.get("severity_rollup_penalty") or {}).items()
        },
        max_source_files=int(data.get("max_source_files", 5000)),
    )


def build_policy(docs: dict[AssetType, tuple[str, str]]) -> Policy:
    """Build the runtime Policy from {asset_type: (yaml_text, version_label)}."""
    llm_text, llm_version = docs[AssetType.LLM]
    llm = validate_class_content(AssetType.LLM, llm_text, strict=False)
    judge = llm.get("judge") or {}
    supply = llm.get("weights") or {}

    scanner: dict[AssetType, ScannerPolicy] = {}
    raw: dict[str, Any] = {"llm": llm}
    meta: dict[AssetType, ClassMeta] = {
        AssetType.LLM: ClassMeta(version=llm_version, content_hash=content_hash(llm_text))
    }
    for asset_type in (AssetType.MCP, AssetType.SKILL):
        text, version = docs[asset_type]
        data = validate_class_content(asset_type, text, strict=False)
        scanner[asset_type] = _scanner_from_data(data)
        raw[asset_type.value] = data
        meta[asset_type] = ClassMeta(version=version, content_hash=content_hash(text))

    return Policy(
        meta=meta,
        judge_default_model=str(judge.get("default_model", "qwen35")),
        judge_max_refusal_rate=float(judge.get("max_refusal_rate", 0.05)),
        llm_gates={
            check_id: _gate_from_spec(check_id, spec)
            for check_id, spec in (llm.get("gates") or {}).items()
        },
        composite_weights={
            k: float(v) for k, v in (llm.get("composite_weights") or {}).items()
        },
        weights_block_on_unsafe_file=bool(supply.get("block_on_unsafe_file", True)),
        weights_treat_unscanned_as_pass=bool(supply.get("treat_unscanned_as_pass", False)),
        scanner=scanner,
        raw=raw,
    )


# --- file mode (seeding, calibration, tests) ----------------------------------------------


def seed_path(policy_dir: Path, asset_type: AssetType) -> Path:
    return policy_dir / f"{asset_type.value}.yaml"


def load_policy_dir(policy_dir: Path) -> Policy:
    """Build a Policy straight from the seed files, bypassing the database.

    Used by the calibration CLI (which may run without an initialised database) and by
    tests. Versions are labelled "seed" so output can never be mistaken for a governed run.
    """
    return build_policy(
        {
            asset_type: (seed_path(policy_dir, asset_type).read_text(), "seed")
            for asset_type in AssetType
        }
    )


# --- database mode ------------------------------------------------------------------------

# A version number is chosen by reading the newest row, so two writers can choose the same
# one. The unique index on (asset_type, version) makes that a rejected insert instead of two
# rows claiming the same version, and the loser re-reads and takes the next free number. The
# retry is bounded: each pass costs one read and one insert, and it only repeats while another
# writer keeps winning the same instant.
_VERSION_INSERT_ATTEMPTS = 5


def seed_policies(session: Session, policy_dir: Path) -> None:
    """Insert version 1 for any asset class that has no policy rows yet."""
    for attempt in range(1, _VERSION_INSERT_ATTEMPTS + 1):
        # The read below autoflushes the previous class's pending insert, so it can raise the
        # very IntegrityError this retries — it has to sit inside the try, not just the commit.
        try:
            for asset_type in AssetType:
                existing = session.exec(
                    select(PolicyVersion).where(PolicyVersion.asset_type == asset_type).limit(1)
                ).first()
                if existing is not None:
                    continue
                text = seed_path(policy_dir, asset_type).read_text()
                validate_class_content(asset_type, text)
                session.add(
                    PolicyVersion(
                        asset_type=asset_type,
                        version=1,
                        content=text,
                        content_hash=content_hash(text),
                        note="seeded from backend/policy/",
                    )
                )
            session.commit()
            return
        except IntegrityError:
            # Another process seeded the same class between the read and the insert. Its row
            # is exactly what this wanted, so re-read and fill in whatever is still missing —
            # this runs at startup, and a lost race must not stop the application coming up.
            session.rollback()
            if attempt == _VERSION_INSERT_ATTEMPTS:
                raise


def newest_version(session: Session, asset_type: AssetType) -> PolicyVersion | None:
    return session.exec(
        select(PolicyVersion)
        .where(PolicyVersion.asset_type == asset_type)
        .order_by(PolicyVersion.version.desc())
        .limit(1)
    ).first()


def list_versions(session: Session, asset_type: AssetType) -> list[PolicyVersion]:
    return list(
        session.exec(
            select(PolicyVersion)
            .where(PolicyVersion.asset_type == asset_type)
            .order_by(PolicyVersion.version.desc())
        )
    )


def get_version(session: Session, asset_type: AssetType, version: int) -> PolicyVersion | None:
    return session.exec(
        select(PolicyVersion)
        .where(PolicyVersion.asset_type == asset_type)
        .where(PolicyVersion.version == version)
    ).first()


def create_version(
    session: Session, asset_type: AssetType, content: str, note: str | None = None
) -> PolicyVersion:
    """Validate and store a new immutable version. The newest version governs new runs.

    Reading the newest version and inserting the next number is a race two concurrent saves
    can both win, which used to leave two different documents recorded as the same version —
    a run pointing at that version could then no longer be resolved to one document. The
    unique index rejects the second insert instead; this re-reads and takes the next free
    number, so both edits are kept and the sequence stays a sequence.
    """
    validate_class_content(asset_type, content)
    for _ in range(_VERSION_INSERT_ATTEMPTS - 1):
        try:
            return _insert_next_version(session, asset_type, content, note)
        except IntegrityError:
            # Another writer took that number. Re-read and go again.
            session.rollback()
    # Out of retries: the last attempt's failure is the caller's answer, not another loop.
    return _insert_next_version(session, asset_type, content, note)


def _insert_next_version(
    session: Session, asset_type: AssetType, content: str, note: str | None
) -> PolicyVersion:
    """One read-then-insert attempt. Raises IntegrityError if the number was taken."""
    current = newest_version(session, asset_type)
    row = PolicyVersion(
        asset_type=asset_type,
        version=(current.version + 1) if current else 1,
        content=content,
        content_hash=content_hash(content),
        note=(note or "").strip() or None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def policy_for_run(session: Session, run, asset) -> Policy:
    """The policy a recorded run must be interpreted under.

    Gate outcomes and the composite are recomputed at read time, so they have to come from
    the policy version the run actually recorded — otherwise editing a threshold, or adding a
    benchmark to the suite, would silently rewrite the meaning of every historical run on
    screen. Every view of a run resolves it through here, so the run page and the evaluations
    table can never disagree about the same run.

    Falls back to the active policy when the recorded version cannot be resolved (runs that
    predate policy versioning, or whose content hash no longer matches). That fallback is
    visible rather than silent: such a run's coverage is incomplete under the current suite,
    so its composite is withheld rather than presented as a full result.
    """
    active = get_active_policy(session)
    if not run.policy_version or not str(run.policy_version).isdigit():
        return active
    row = get_version(session, asset.type, int(run.policy_version))
    if row is None or row.content_hash != run.policy_hash:
        return active
    docs: dict[AssetType, tuple[str, str]] = {}
    for asset_type in AssetType:
        if asset_type is asset.type:
            docs[asset_type] = (row.content, str(row.version))
        else:
            newest = newest_version(session, asset_type)
            docs[asset_type] = (newest.content, "current") if newest else ("{}", "current")
    try:
        return build_policy(docs)
    except Exception:  # noqa: BLE001 - a historical document must never break a page
        return active


def get_active_policy(session: Session) -> Policy:
    """The policy that governs new runs: the newest version of each class document."""
    docs: dict[AssetType, tuple[str, str]] = {}
    for asset_type in AssetType:
        row = newest_version(session, asset_type)
        if row is None:
            raise RuntimeError(
                f"no policy rows for {asset_type.value}; the database was not seeded"
            )
        docs[asset_type] = (row.content, str(row.version))
    return build_policy(docs)
