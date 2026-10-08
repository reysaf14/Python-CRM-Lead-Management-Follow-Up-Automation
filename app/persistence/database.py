"""Engine and transaction boundaries for PostgreSQL persistence."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def build_engine(settings: Settings | None = None) -> Engine:
    """Build an engine without opening a database connection immediately."""

    resolved_settings = settings or get_settings()
    if not resolved_settings.database_url:
        raise ValueError("DATABASE_URL is required for database runtime")
    return create_engine(
        resolved_settings.database_url,
        pool_pre_ping=True,
        future=True,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create an explicit, non-autocommitting session factory."""

    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process engine created from validated runtime settings."""

    return build_engine()


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the process session factory."""

    return build_session_factory(get_engine())


@contextmanager
def session_scope(
    session_factory: Callable[[], Session] | sessionmaker[Session],
) -> Iterator[Session]:
    """Commit one unit of work or roll it back completely on failure.

    External provider calls must occur outside this context. Callers should
    persist a pending state before an external call and use a new scope for the
    accepted, retryable, or manual-review outcome.
    """

    session = session_factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine(engine: Engine | None = None) -> None:
    """Dispose an explicitly supplied engine, primarily for isolated tests."""

    (engine or get_engine()).dispose()


__all__ = [
    "build_engine",
    "build_session_factory",
    "dispose_engine",
    "get_engine",
    "get_session_factory",
    "session_scope",
]
