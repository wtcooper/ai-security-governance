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
        done = Run(asset_id=1, status=RunStatus.COMPLETE, decision=Decision.NEEDS_DEEP_TESTING)
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
        assert untouched.decision is Decision.NEEDS_DEEP_TESTING
