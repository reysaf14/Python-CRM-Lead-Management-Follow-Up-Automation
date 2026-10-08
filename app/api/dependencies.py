"""FastAPI dependency boundaries for internal CRM routes."""

from collections.abc import Iterator

from sqlalchemy.orm import Session, sessionmaker

from app.persistence.database import get_session_factory


def get_crm_session_factory() -> sessionmaker[Session]:
    """Resolve the application session factory through validated settings."""

    return get_session_factory()


def get_db_session() -> Iterator[Session]:
    """Yield one request-scoped database session."""

    session = get_crm_session_factory()()
    try:
        yield session
    finally:
        session.close()
