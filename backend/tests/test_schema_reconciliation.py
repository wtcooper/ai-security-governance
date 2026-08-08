"""Adding a model field must not require destroying the audit trail.

SQLModel's `create_all` creates missing tables but never alters existing ones. Without the
reconciliation in `db.py`, adding a column leaves an older database unqueryable, and the usual
workaround — delete the database — throws away the governance record. That happened once during
development (adding `Run.judge_unresolved_rate` broke every query against the existing volume),
which is why it is tested.

The scenario is built the way it actually occurs: create the schema as a previous version would
have, drop the columns that version did not know about, then reconcile.
"""

from __future__ import annotations

import importlib
import sqlite3

NEW_COLUMNS = ("judge_unresolved_rate", "judge_refusal_rate")


def _reloaded_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "governance.db"))
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))

    from app import config

    config.get_settings.cache_clear()
    import app.db as db_module

    return importlib.reload(db_module)


def test_columns_added_to_a_model_are_added_to_an_existing_database(tmp_path, monkeypatch):
    db_path = tmp_path / "governance.db"
    db = _reloaded_db(tmp_path, monkeypatch)

    # A database as an earlier version of the app would have left it.
    db.init_db()
    connection = sqlite3.connect(db_path)
    connection.execute(
        "INSERT INTO asset (type, name, identifier, created_at) "
        "VALUES ('llm', 'gemma4', 'gemma4', '2026-01-01T00:00:00')"
    )
    connection.execute(
        "INSERT INTO run (asset_id, status, started_at, decision) "
        "VALUES (1, 'complete', '2026-01-01T00:00:00', 'auto_approve')"
    )
    for column in NEW_COLUMNS:
        connection.execute(f"ALTER TABLE run DROP COLUMN {column}")
    connection.commit()
    columns_before = {row[1] for row in connection.execute("PRAGMA table_info(run)")}
    connection.close()
    assert not (columns_before & set(NEW_COLUMNS)), "test setup failed to remove the columns"

    # Reconciliation is what a newer version does on startup.
    db.init_db()

    connection = sqlite3.connect(db_path)
    columns_after = {row[1] for row in connection.execute("PRAGMA table_info(run)")}
    rows = list(
        connection.execute("SELECT status, decision, judge_unresolved_rate FROM run")
    )
    connection.close()

    assert set(NEW_COLUMNS) <= columns_after
    # The pre-existing decision survived, which is the whole point.
    assert rows == [("complete", "auto_approve", None)]

    from app import config

    config.get_settings.cache_clear()


def test_reconciliation_is_idempotent(tmp_path, monkeypatch):
    """Startup runs it every time, so a second pass must not fail or duplicate."""
    db = _reloaded_db(tmp_path, monkeypatch)
    db.init_db()
    db.init_db()
    db.init_db()

    connection = sqlite3.connect(tmp_path / "governance.db")
    names = [row[1] for row in connection.execute("PRAGMA table_info(run)")]
    connection.close()

    assert len(names) == len(set(names)), "a column was added twice"

    from app import config

    config.get_settings.cache_clear()


def test_a_not_null_column_refuses_rather_than_guessing(tmp_path, monkeypatch):
    """A NOT NULL addition needs a chosen backfill, so it must fail loudly.

    Silently inserting a zero or an empty string into historical governance rows would be
    inventing data about decisions that were already made.
    """
    import pytest
    from sqlalchemy import Column, Integer, String, Table

    db = _reloaded_db(tmp_path, monkeypatch)
    db.init_db()

    from sqlmodel import SQLModel

    # A table that exists in the database without the NOT NULL column the model now declares.
    connection = sqlite3.connect(tmp_path / "governance.db")
    connection.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()

    Table(
        "widget",
        SQLModel.metadata,
        Column("id", Integer, primary_key=True),
        Column("mandatory", String, nullable=False),
    )
    try:
        with pytest.raises(RuntimeError, match="NOT NULL"):
            db.init_db()
    finally:
        SQLModel.metadata.remove(SQLModel.metadata.tables["widget"])
        from app import config

        config.get_settings.cache_clear()
