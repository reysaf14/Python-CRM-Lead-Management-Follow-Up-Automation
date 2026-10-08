from sqlalchemy import UniqueConstraint, create_engine
from sqlalchemy.orm import Session

from app.persistence.base import Base
from app.persistence.database import build_session_factory, session_scope
from app.persistence.models import Contact


def test_m1_metadata_contains_all_logical_records() -> None:
    expected_tables = {
        "mailbox_sync_state",
        "messages",
        "contacts",
        "conversations",
        "leads",
        "extraction_attempts",
        "scoring_rule_versions",
        "score_evaluations",
        "activities",
        "reminders",
    }

    assert expected_tables.issubset(Base.metadata.tables)


def test_session_scope_rolls_back_the_complete_unit_of_work() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

    try:
        try:
            with session_scope(session_factory) as session:
                session.add(Contact(email_normalized="rollback@example.invalid"))
                raise RuntimeError("synthetic transaction failure")
        except RuntimeError:
            pass

        with Session(engine) as session:
            assert (
                session.query(Contact)
                .filter_by(email_normalized="rollback@example.invalid")
                .count()
                == 0
            )
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_schema_exposes_unique_provider_message_identity() -> None:
    messages = Base.metadata.tables["messages"]

    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns} == {"provider_message_id"}
        for constraint in messages.constraints
    )
