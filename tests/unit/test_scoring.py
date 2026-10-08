from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.adapters.gmail.client import GmailPage, MockGmailAdapter, NormalizedEmail
from app.adapters.llm.client import MockLLMClient
from app.domain.scoring import DEFAULT_SCORING_RULES, calculate_score, parse_stated_budget
from app.persistence.base import Base
from app.persistence.database import build_session_factory
from app.persistence.models import Lead, ScoreEvaluation, ScoringRuleVersion
from app.services.extraction import LeadExtractionService
from app.services.gmail_polling import GmailPollingService
from app.services.scoring import LeadScoringService


def _message() -> NormalizedEmail:
    return NormalizedEmail(
        provider_message_id="message-m4-001",
        provider_thread_id="thread-m4-001",
        sender_email="prospect@example.invalid",
        sender_name="Synthetic Prospect",
        received_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        subject="Inquiry for Customer Support Automation",
        label_names=("Sales Leads",),
        is_auto_reply=False,
        body_text="We need customer support automation for our store. Budget is $1,500.",
    )


def _response() -> dict[str, object]:
    return {
        "intent": "sales_inquiry",
        "service_interest": "Customer Support Automation",
        "stated_budget": "$1,500",
        "business_summary": "Online store seeking automated support.",
        "confidence": 0.95,
        "ambiguity_flags": [],
    }


def test_scoring_is_deterministic_and_parses_only_stated_budget() -> None:
    facts = _response()

    first = calculate_score(facts=facts, rules=DEFAULT_SCORING_RULES, source_message_id=7)
    second = calculate_score(facts=facts, rules=DEFAULT_SCORING_RULES, source_message_id=7)

    assert parse_stated_budget("approximately $1,500 USD") == 1500
    assert parse_stated_budget("budget not stated") is None
    assert first == second
    assert first.score == 100
    assert first.priority == "High"
    assert "rule_version=m4-baseline-draft-v1" in first.explanation
    assert first.input_snapshot == {
        "source_message_id": 7,
        "intent": "sales_inquiry",
        "has_service_interest": True,
        "has_stated_budget": True,
        "budget_band": "budget_1000_plus",
        "has_business_summary": True,
    }


def test_valid_extraction_creates_one_versioned_score_and_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    llm = MockLLMClient(responses=[_response()])
    scoring = LeadScoringService(
        session_factory=session_factory,
        rules=DEFAULT_SCORING_RULES,
    )
    extraction = LeadExtractionService(
        llm_client=llm,
        session_factory=session_factory,
        model="synthetic-model",
        max_input_chars=320,
        timeout_seconds=5,
        retry_max=1,
        scoring_service=scoring,
    )
    polling = GmailPollingService(
        adapter=MockGmailAdapter([GmailPage(messages=(_message(),), next_cursor=None)]),
        session_factory=session_factory,
        mailbox_key="synthetic-mailbox-m4",
        label_name="Sales Leads",
        extraction_service=extraction,
    )

    try:
        result = polling.poll_once()

        assert result.extraction_succeeded_count == 1
        with Session(engine) as session:
            lead = session.scalar(select(Lead))
            evaluation = session.scalar(select(ScoreEvaluation))
            rule_version = session.scalar(select(ScoringRuleVersion))
            assert lead is not None
            assert lead.score == 100
            assert lead.priority == "High"
            assert lead.score_reason is not None
            assert "rule_version=m4-baseline-draft-v1" in lead.score_reason
            assert evaluation is not None
            assert evaluation.source_message_id is not None
            assert evaluation.priority == "High"
            assert rule_version is not None
            assert rule_version.version == DEFAULT_SCORING_RULES.version

            score_outcome = scoring.score_lead(
                lead_id=lead.id,
                source_message_id=evaluation.source_message_id,
                facts=_response(),
            )
            assert score_outcome.status == "already_scored"
            assert session.scalar(select(ScoreEvaluation.id)) == evaluation.id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
