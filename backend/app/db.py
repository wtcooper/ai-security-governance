"""Database engine and session handling."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_log = logging.getLogger(__name__)

# check_same_thread=False because FastAPI serves requests from a thread pool and the
# background job runner touches the same SQLite file.
_engine = create_engine(
    get_settings().db_url,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Create tables, then add any columns the models gained since the file was written."""
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(_engine)
    _add_missing_columns()
    _add_missing_unique_indexes()


def _add_missing_columns() -> None:
    """Additive schema reconciliation for SQLite.

    `create_all` creates missing tables but never alters existing ones, so adding a field to a
    model leaves an older database missing that column and every query fails. The obvious
    workaround — delete the database — is the wrong answer here: these rows are the audit
    trail, and a governance decision that can no longer be produced is a decision that may as
    well not have been recorded.

    This is deliberately not a migration framework. It only ADDs nullable columns, which SQLite
    supports directly and which cannot lose data. Renames, type changes and drops are out of
    scope: if one is ever needed, it wants a real migration and a deliberate decision about the
    existing rows. Swapping to Postgres would mean adopting Alembic instead.
    """
    from sqlalchemy import inspect as sa_inspect, text

    # Reflect through the same connection that performs the ALTERs. An Inspector bound to the
    # engine can serve a cached schema view, which produced "duplicate column" errors against a
    # database that had just been changed.
    with _engine.begin() as connection:
        inspector = sa_inspect(connection)
        existing_tables = set(inspector.get_table_names())

        for table_name, table in SQLModel.metadata.tables.items():
            if table_name not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table_name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable:
                    # Refuse rather than guess a backfill value for existing rows.
                    raise RuntimeError(
                        f"{table_name}.{column.name} is NOT NULL and missing from an existing "
                        "database. That needs a real migration with a chosen backfill value."
                    )
                ddl = column.type.compile(_engine.dialect)
                connection.execute(
                    text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {ddl}')
                )


def _add_missing_unique_indexes() -> None:
    """Add unique indexes the models declare and an existing database does not have.

    `create_all` skips a table that already exists, its indexes included, so a uniqueness rule
    declared on a model only ever reaches a freshly created database. This adds it to an older
    one, which is where the rule is needed most: those are the databases written while nothing
    enforced it.

    It never raises. A unique index refuses to be created when existing rows already violate
    it, and `init_db` runs on every start — turning those rows into a permanent boot failure
    would be worse than the ambiguity they cause, and repairing them is a judgement call about
    real records that only their owner can make. So a database that cannot take the index keeps
    running exactly as it did before the index existed, and the problem is reported instead.
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.exc import SQLAlchemyError

    missing = []
    try:
        with _engine.connect() as connection:
            inspector = sa_inspect(connection)
            existing_tables = set(inspector.get_table_names())
            for table_name, table in SQLModel.metadata.tables.items():
                if table_name not in existing_tables:
                    continue
                present = {index["name"] for index in inspector.get_indexes(table_name)}
                missing.extend(
                    index for index in table.indexes if index.unique and index.name not in present
                )
    except SQLAlchemyError:
        _log.exception("could not read the existing indexes; startup is continuing without them")
        return

    for index in missing:
        columns = ", ".join(column.name for column in index.columns)
        try:
            # One transaction per index so a refusal leaves the others unaffected.
            with _engine.begin() as connection:
                index.create(bind=connection)
        except SQLAlchemyError as exc:
            _log.error(
                "could not create unique index %s on %s(%s): %s. Startup is continuing and "
                "%s stays as unconstrained as it was before, so nothing has broken — but "
                "rows almost certainly already duplicate a (%s) pair. A human has to pick "
                "which of each duplicate group is the real row, delete the others, and "
                "restart; until then duplicates can still be written.",
                index.name,
                index.table.name,
                columns,
                exc,
                index.table.name,
                columns,
            )


def get_session() -> Iterator[Session]:
    with Session(_engine) as session:
        yield session


def session_scope() -> Session:
    """A session for code outside the request cycle (background jobs)."""
    return Session(_engine)
