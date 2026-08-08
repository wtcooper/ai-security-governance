"""Database engine and session handling."""

from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

# check_same_thread=False because FastAPI serves requests from a thread pool and the
# background job runner touches the same SQLite file.
_engine = create_engine(
    get_settings().db_url,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Create tables. Imported for the side effect of registering the models."""
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(_engine)


def get_session() -> Iterator[Session]:
    with Session(_engine) as session:
        yield session


def session_scope() -> Session:
    """A session for code outside the request cycle (background jobs)."""
    return Session(_engine)
