"""Versioned per-class policies and fixed core-set selection (Phase 8).

Two governance properties are on the line here:

* **Immutability** — a policy version that governed a recorded decision must stay exactly
  as it was. Editing means inserting version n+1, never touching version n.
* **Repeatability** — the same seed and size must select the same core set every time, or
  "fixed core set" is a fiction.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import AssetType
from app.scoring import policy as policy_store
from app.scoring.core_set import propose_core_set
from app.scoring.policy import PolicyValidationError, get_active_policy, seed_policies

POLICY_DIR = Path(__file__).resolve().parents[1] / "policy"


def _set_samples(text: str, check_id: str, value: int) -> str:
    """Rewrite one gate's sample count, addressed by gate name.

    Tests used to string-replace a literal like "samples: 20", which silently broke the day
    the shipped default changed. Addressing the gate by name keeps them independent of it.
    """
    import re

    start = text.index(f"  {check_id}:")
    end = text.index("\n  ", text.index("samples:", start))
    block = re.sub(r"samples: \d+", f"samples: {value}", text[start:end])
    return text[:start] + block + text[end:]


def _drop_gate(text: str, check_id: str) -> str:
    """Remove one gate from a policy document, addressed by name.

    Retiring a benchmark is a policy edit, so a test needs to perform one without depending
    on the exact prose of the block it removes.
    """
    start = text.index(f"  {check_id}:")
    # The next top-level key or next sibling gate ends the block.
    rest = text[start + 1 :]
    offsets = [rest.index(m) for m in ("\n  cyse4_", "\n  atb_", "\n  strong_", "\n  agentdojo",
                                       "\n# ", "\ncomposite_weights:") if m in rest]
    end = start + 1 + min(offsets)
    return text[:start] + text[end + 1 :]


def _pin_ids(text: str, check_id: str, ids: list[str]) -> str:
    """Add a fixed core set to one gate, addressed by name."""
    start = text.index(f"  {check_id}:")
    anchor = text.index("samples:", start)
    line_end = text.index("\n", anchor)
    return text[:line_end] + f"\n    sample_ids: [{', '.join(ids)}]" + text[line_end:]


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# --- seeding and versioning ---------------------------------------------------------------


def test_seeding_creates_v1_for_each_class(session):
    seed_policies(session, POLICY_DIR)
    for asset_type in AssetType:
        row = policy_store.newest_version(session, asset_type)
        assert row is not None and row.version == 1
        assert row.content_hash == policy_store.content_hash(row.content)


def test_seeding_twice_does_not_duplicate(session):
    seed_policies(session, POLICY_DIR)
    seed_policies(session, POLICY_DIR)
    for asset_type in AssetType:
        assert len(policy_store.list_versions(session, asset_type)) == 1


def test_editing_creates_a_new_version_and_leaves_the_old_one_untouched(session):
    seed_policies(session, POLICY_DIR)
    v1 = policy_store.newest_version(session, AssetType.LLM)
    original_content = v1.content

    edited = original_content.replace("threshold: 0.85", "threshold: 0.95")
    v2 = policy_store.create_version(session, AssetType.LLM, edited, note="tighten PI gate")

    assert v2.version == 2
    assert v2.note == "tighten PI gate"
    # v1 is still there, byte-identical.
    v1_again = policy_store.get_version(session, AssetType.LLM, 1)
    assert v1_again.content == original_content

    # The newest version is what governs.
    active = get_active_policy(session)
    assert active.llm_gates["cyse4_multilingual_prompt_injection"].threshold == 0.95
    assert active.meta[AssetType.LLM].version == "2"
    # Other classes are unaffected by an LLM edit.
    assert active.meta[AssetType.MCP].version == "1"


def test_versions_are_per_class(session):
    seed_policies(session, POLICY_DIR)
    mcp = policy_store.newest_version(session, AssetType.MCP)
    policy_store.create_version(
        session, AssetType.MCP, mcp.content.replace("mode: advisory", "mode: gating"), None
    )
    assert policy_store.newest_version(session, AssetType.MCP).version == 2
    assert policy_store.newest_version(session, AssetType.LLM).version == 1
    assert policy_store.newest_version(session, AssetType.SKILL).version == 1


# --- validation: invalid content creates nothing ------------------------------------------


@pytest.mark.parametrize(
    "mutation,expected",
    [
        # Unknown benchmark id.
        (lambda t: t.replace("cyse4_mitre_frr:", "cyse4_made_up:"), "not a registered"),
        # Metric that disagrees with what the benchmark reports — the historical bug class.
        (lambda t: t.replace("metric: refusal_rate", "metric: accuracy"), "metric must be"),
        # Direction that disagrees with the registry.
        (
            lambda t: t.replace(
                "metric: refusal_rate\n    direction: lower_is_better",
                "metric: refusal_rate\n    direction: higher_is_better",
            ),
            "direction must be",
        ),
        # Threshold out of the 0-1 unit.
        (lambda t: t.replace("threshold: 0.85", "threshold: 85"), "threshold must be"),
        # Zero samples would silently measure nothing.
        (lambda t: _set_samples(t, "cyse4_mitre_frr", 0), "samples must be"),
    ],
)
def test_invalid_llm_content_is_rejected_and_creates_no_version(session, mutation, expected):
    seed_policies(session, POLICY_DIR)
    content = policy_store.newest_version(session, AssetType.LLM).content
    broken = mutation(content)
    assert broken != content, "the mutation must actually change the document"

    with pytest.raises(PolicyValidationError, match=expected):
        policy_store.create_version(session, AssetType.LLM, broken, None)
    # Nothing was created.
    assert policy_store.newest_version(session, AssetType.LLM).version == 1


def test_invalid_scanner_mode_is_rejected(session):
    seed_policies(session, POLICY_DIR)
    content = policy_store.newest_version(session, AssetType.MCP).content
    with pytest.raises(PolicyValidationError, match="mode must be"):
        policy_store.create_version(
            session, AssetType.MCP, content.replace("mode: advisory", "mode: sometimes"), None
        )


def test_sample_ids_win_over_samples():
    text = (POLICY_DIR / "llm.yaml").read_text()
    pinned = _pin_ids(text, "cyse4_multilingual_prompt_injection", ["id_a", "id_b", "id_c"])
    data = policy_store.validate_class_content(AssetType.LLM, pinned)
    gate = policy_store._gate_from_spec(  # noqa: SLF001 - the parsing seam under test
        "cyse4_multilingual_prompt_injection",
        data["gates"]["cyse4_multilingual_prompt_injection"],
    )
    assert gate.sample_ids == ("id_a", "id_b", "id_c")
    assert gate.planned_samples == 3


def test_duplicate_sample_ids_are_rejected():
    text = (POLICY_DIR / "llm.yaml").read_text()
    duplicated = _pin_ids(text, "cyse4_multilingual_prompt_injection", ["id_a", "id_a"])
    with pytest.raises(PolicyValidationError, match="duplicates"):
        policy_store.validate_class_content(AssetType.LLM, duplicated)


# --- core-set selection: deterministic and stratified -------------------------------------


def _fake_dataset(per_stratum: dict[str, int]) -> tuple[list[str], dict[str, str]]:
    ids: list[str] = []
    id_strata: dict[str, str] = {}
    for stratum, count in per_stratum.items():
        for index in range(count):
            sample_id = f"{stratum}_{index:04d}"
            ids.append(sample_id)
            id_strata[sample_id] = stratum
    return ids, id_strata


def test_same_seed_selects_the_same_ids():
    ids, strata = _fake_dataset({"a": 300, "b": 500, "c": 204})
    first = propose_core_set(ids, strata, size=50, seed="governance-v1")
    second = propose_core_set(ids, strata, size=50, seed="governance-v1")
    assert first.sample_ids == second.sample_ids
    assert len(first.sample_ids) == 50

    # A different seed selects a different set (with overwhelming probability for these
    # sizes; equality would indicate the seed is ignored).
    third = propose_core_set(ids, strata, size=50, seed="governance-v2")
    assert third.sample_ids != first.sample_ids


def test_allocation_is_proportional_across_strata():
    ids, strata = _fake_dataset({"a": 300, "b": 500, "c": 200})
    proposal = propose_core_set(ids, strata, size=100, seed="s")
    assert proposal.allocation["a"][0] == 30
    assert proposal.allocation["b"][0] == 50
    assert proposal.allocation["c"][0] == 20
    # Every selected id exists and carries the stratum it was allocated under.
    assert set(proposal.sample_ids) <= set(ids)


def test_input_order_does_not_change_the_selection():
    """The draw must depend on the dataset's contents, not the order a file listed them."""
    ids, strata = _fake_dataset({"a": 100, "b": 100})
    proposal = propose_core_set(ids, strata, size=20, seed="s")
    reversed_proposal = propose_core_set(list(reversed(ids)), strata, size=20, seed="s")
    assert proposal.sample_ids == reversed_proposal.sample_ids


def test_unstratified_datasets_form_one_group():
    ids = [f"id_{i:03d}" for i in range(97)]
    proposal = propose_core_set(ids, {}, size=10, seed="s")
    assert len(proposal.sample_ids) == 10
    assert proposal.allocation == {"all": (10, 97)}


def test_size_beyond_dataset_is_refused():
    ids = [f"id_{i}" for i in range(5)]
    with pytest.raises(ValueError, match="exceeds dataset size"):
        propose_core_set(ids, {}, size=6, seed="s")


def test_rounding_never_over_allocates_a_tiny_stratum():
    """A stratum with 1 member must not be asked for 2, even when quotas round against it."""
    ids, strata = _fake_dataset({"big": 997, "tiny": 1})
    proposal = propose_core_set(ids, strata, size=500, seed="s")
    assert len(proposal.sample_ids) == 500
    assert proposal.allocation["tiny"][0] <= 1


# --- interpreting historical runs ---------------------------------------------------------


def test_a_run_is_interpreted_under_the_policy_it_recorded(session):
    """Adding a benchmark to the suite must not rewrite what past evaluations meant.

    The run page and the evaluations table both recompute gates and the composite at read
    time, so both resolve a run's policy through `policy_for_run`. If that returned the
    ACTIVE policy instead, enabling a new benchmark would retroactively change the gate
    denominator of every historical run on screen.
    """
    from app.models import Asset, Run
    from app.scoring.policy import policy_for_run

    seed_policies(session, POLICY_DIR)
    v1 = policy_store.newest_version(session, AssetType.LLM)

    # A run governed by v1, recorded faithfully.
    asset = Asset(type=AssetType.LLM, name="subject", identifier="gemma4")
    session.add(asset)
    session.commit()
    session.refresh(asset)
    run = Run(
        asset_id=asset.id,
        policy_version=str(v1.version),
        policy_hash=v1.content_hash,
    )
    session.add(run)
    session.commit()

    v1_gate_count = len(policy_store.build_policy(
        {t: ((policy_store.newest_version(session, t)).content, "1") for t in AssetType}
    ).llm_gates)

    # Now tighten the suite: drop a benchmark, creating v2.
    reduced = _drop_gate(v1.content, "atb_memory_poison")
    assert reduced != v1.content
    policy_store.create_version(session, AssetType.LLM, reduced, "drop one benchmark")

    active = get_active_policy(session)
    assert len(active.llm_gates) == v1_gate_count - 1, "the edit must change the active suite"

    # The run still resolves to v1's suite, not the active one.
    resolved = policy_for_run(session, run, asset)
    assert len(resolved.llm_gates) == v1_gate_count
    assert "atb_memory_poison" in resolved.llm_gates
    assert resolved.meta[AssetType.LLM].version == str(v1.version)


def test_an_unresolvable_policy_falls_back_to_active(session):
    """Runs predating versioning have a hash that matches nothing; they must still render."""
    from app.models import Asset, Run
    from app.scoring.policy import policy_for_run

    seed_policies(session, POLICY_DIR)
    asset = Asset(type=AssetType.LLM, name="old", identifier="gemma4")
    session.add(asset)
    session.commit()
    session.refresh(asset)
    run = Run(asset_id=asset.id, policy_version="1", policy_hash="deadbeefdeadbeef")
    session.add(run)
    session.commit()

    resolved = policy_for_run(session, run, asset)
    assert resolved.llm_gates, "must fall back rather than raise"
