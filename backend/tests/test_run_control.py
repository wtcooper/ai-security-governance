"""Run control introduced in Phase 8: policy-driven samples reach the child, and
interrupted runs are closed out rather than left spinning."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.engines.inspect_runner import build_eval_argv
from app.jobs import close_orphaned_runs
from app.models import Decision, Run, RunStatus


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        gateway_base_url="http://gateway:4000/v1",
        gateway_api_key="sk-local",
        gateway_provider="gateway",
        default_judge_model="qwen35",
        default_subject_model="gemma4",
        scanner_model="gemma4",
        db_path=tmp_path / "db.sqlite",
        artifact_dir=tmp_path / "artifacts",
        workspace_dir=tmp_path / "workspaces",
        policy_dir=tmp_path / "policy",
        fixtures_dir=tmp_path / "fixtures",
    )


def test_sample_ids_reach_the_child_argv(settings):
    """Acceptance 8.5 — a fixed core set is passed as explicit --sample-id arguments."""
    argv = build_eval_argv(
        settings,
        task="cyse4_multilingual_prompt_injection",
        model_alias="gemma4",
        judge_alias="qwen35",
        limit=None,
        sample_ids=("pi_aaa", "pi_bbb"),
        log_dir="/logs",
    )
    assert argv.count("--sample-id") == 2
    assert argv[argv.index("--sample-id") + 1] == "pi_aaa"
    assert "--limit" not in argv, "a core set replaces the limit; both would be ambiguous"


def test_limit_and_no_sample_ids_is_the_counted_form(settings):
    argv = build_eval_argv(
        settings,
        task="cyse4_instruct",
        model_alias="gemma4",
        judge_alias=None,
        limit=20,
        sample_ids=(),
        log_dir="/logs",
    )
    assert argv[argv.index("--limit") + 1] == "20"
    assert "--sample-id" not in argv
    assert "--judge-model" not in argv


def test_orphaned_runs_are_failed_on_startup(tmp_path):
    """Acceptance 8.10 — a backend restart must not leave a run claiming to be running."""
    engine = create_engine(f"sqlite:///{tmp_path / 'orphans.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Run(asset_id=1, status=RunStatus.RUNNING))
        session.add(Run(asset_id=1, status=RunStatus.PENDING))
        done = Run(asset_id=1, status=RunStatus.COMPLETE, decision=Decision.REQUIRES_REVIEW)
        session.add(done)
        session.commit()

        assert close_orphaned_runs(session) == 2

        from sqlmodel import select

        runs = session.exec(select(Run)).all()
        interrupted = [r for r in runs if r.status is RunStatus.FAILED]
        assert len(interrupted) == 2
        for run in interrupted:
            assert run.decision is Decision.ERROR
            assert "restart" in (run.decision_reason or "")
            assert run.finished_at is not None
        # The completed run is untouched.
        untouched = next(r for r in runs if r.status is RunStatus.COMPLETE)
        assert untouched.decision is Decision.REQUIRES_REVIEW


def test_grouped_metric_extras_do_not_collide():
    """Regression: `security.stderr` and `utility.stderr` both truncated to "stderr".

    Grouped-metric benchmarks (AgentDojo, AgentThreatBench) report the same metric name
    under two groups. Truncating to the last segment produced two identically-named rows and
    hid `utility.accuracy` — the metric that says whether the model could act at all, which
    is exactly what a perfect security score has to be read against.
    """
    from app.engines.registry import get_check

    check = get_check("atb_memory_poison")
    metrics = {
        "security.accuracy": 0.8,
        "security.stderr": 0.13,
        "utility.accuracy": 0.3,
        "utility.stderr": 0.15,
    }
    extras = [key for key in metrics if key != check.metric_key]
    ids = [f"{check.id}::{key}" for key in extras]

    assert len(set(ids)) == len(ids), f"extras collide: {ids}"
    assert f"{check.id}::utility.accuracy" in ids, "utility must stay identifiable"
    # The gated metric is not duplicated into the extras.
    assert f"{check.id}::security.accuracy" not in ids


def test_progress_reports_the_suite_the_run_was_started_under(tmp_path):
    """A run's progress must agree with its own gate table, not with the current suite.

    Progress used to resolve the ACTIVE policy while the run page and the evaluations table
    resolved the run's recorded one. Retiring a benchmark therefore made a completed run
    report seven benchmarks on one part of the page and eight on another.
    """
    from pathlib import Path

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Asset, AssetType
    from app.scoring import policy as policy_store
    from app.scoring.policy import policy_for_run, seed_policies

    policy_dir = Path(__file__).resolve().parents[1] / "policy"
    engine = create_engine(f"sqlite:///{tmp_path / 'progress.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_policies(session, policy_dir)
        v1 = policy_store.newest_version(session, AssetType.LLM)

        asset = Asset(type=AssetType.LLM, name="subject", identifier="alias")
        session.add(asset)
        session.commit()
        session.refresh(asset)
        run = Run(
            asset_id=asset.id,
            status=RunStatus.COMPLETE,
            policy_version=str(v1.version),
            policy_hash=v1.content_hash,
        )
        session.add(run)
        session.commit()

        original = len(policy_for_run(session, run, asset).llm_gates)

        # Retire a benchmark, creating a smaller active suite.
        from tests.test_policy_versions import _drop_gate

        policy_store.create_version(
            session, AssetType.LLM, _drop_gate(v1.content, "atb_memory_poison"), "retire one"
        )

        resolved = policy_for_run(session, run, asset)
        assert len(resolved.llm_gates) == original, (
            "the run's progress suite must not shrink when the active suite does"
        )


def test_historical_decisions_are_renamed_not_orphaned(tmp_path):
    """A run recorded under the old vocabulary must stay readable.

    The subtlety that made the first attempt at this a no-op: SQLAlchemy's Enum column persists
    the member NAME, so the database holds "NEEDS_DEEP_TESTING", not "needs_deep_testing". A
    migration matching on values updated zero rows and reported success, and every historical
    run then failed to load. This test writes the NAME form deliberately.
    """
    from sqlalchemy import text as sql_text
    from sqlmodel import Session, SQLModel, create_engine

    from app.jobs import migrate_decision_vocabulary
    from app.models import Decision

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.exec(
            sql_text(
                "INSERT INTO run (asset_id, status, decision, started_at) VALUES "
                "(1, 'COMPLETE', 'NEEDS_DEEP_TESTING', '2026-01-01 00:00:00'), "
                "(1, 'COMPLETE', 'AUTO_APPROVE', '2026-01-01 00:00:00')"
            )
        )
        session.commit()

        assert migrate_decision_vocabulary(session) == 2
        stored = {row[0] for row in session.exec(sql_text("SELECT decision FROM run")).all()}
        assert stored == {"REQUIRES_REVIEW", "PASS"}

        # The rows now load through the ORM, which is the point.
        from sqlmodel import select

        from app.models import Run

        decisions = {run.decision for run in session.exec(select(Run)).all()}
        assert decisions == {Decision.REQUIRES_REVIEW, Decision.PASS}

        # Idempotent: a second pass changes nothing.
        assert migrate_decision_vocabulary(session) == 0
