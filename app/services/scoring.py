"""Persistence orchestration for deterministic lead scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.scoring import ScoringRuleSet, calculate_score
from app.persistence.base import utc_now
from app.persistence.database import session_scope
from app.persistence.models import Lead, Message, ScoreEvaluation, ScoringRuleVersion


class ScoringConfigurationError(RuntimeError):
    """Raised when a persisted rule version conflicts with application rules."""


@dataclass(frozen=True)
class ScoreOutcome:
    """Sanitized result of one scoring decision."""

    status: str
    score: int | None = None
    priority: str | None = None
    error_category: str | None = None


class LeadScoringService:
    """Persist one reproducible evaluation per lead/rule/message identity."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        rules: ScoringRuleSet,
        now_factory: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._rules = rules
        self._now_factory = now_factory

    def score_lead(
        self,
        *,
        lead_id: int,
        source_message_id: int,
        facts: dict[str, Any],
    ) -> ScoreOutcome:
        """Score validated extraction facts without contacting any provider."""

        decision = calculate_score(
            facts=facts,
            rules=self._rules,
            source_message_id=source_message_id,
        )
        try:
            with session_scope(self._session_factory) as session:
                rule_version = self._get_or_create_rule_version(session)
                lead = session.get(Lead, lead_id)
                message = session.get(Message, source_message_id)
                if lead is None or message is None:
                    return ScoreOutcome("failed", error_category="scoring_target_not_found")

                existing = session.scalar(
                    select(ScoreEvaluation).where(
                        ScoreEvaluation.lead_id == lead_id,
                        ScoreEvaluation.rule_version_id == rule_version.id,
                        ScoreEvaluation.source_message_id == source_message_id,
                    )
                )
                if existing is not None:
                    return ScoreOutcome(
                        "already_scored",
                        score=existing.score,
                        priority=existing.priority,
                    )

                evaluation = ScoreEvaluation(
                    lead_id=lead_id,
                    rule_version_id=rule_version.id,
                    source_message_id=source_message_id,
                    score=decision.score,
                    priority=decision.priority,
                    explanation=decision.explanation,
                    input_snapshot=decision.input_snapshot,
                    evaluated_at=self._now_factory(),
                )
                session.add(evaluation)
                lead.score = decision.score
                lead.priority = decision.priority
                lead.score_reason = decision.explanation
                return ScoreOutcome(
                    "scored",
                    score=decision.score,
                    priority=decision.priority,
                )
        except ScoringConfigurationError:
            return ScoreOutcome("failed", error_category="scoring_rule_conflict")
        except SQLAlchemyError:
            return ScoreOutcome("failed", error_category="database_write_failed")

    def _get_or_create_rule_version(self, session: Session) -> ScoringRuleVersion:
        payload = self._rules.model_dump(mode="json")
        version = session.scalar(
            select(ScoringRuleVersion).where(ScoringRuleVersion.version == self._rules.version)
        )
        if version is None:
            version = ScoringRuleVersion(
                version=self._rules.version,
                description=self._rules.description,
                rules_payload=payload,
                is_active=True,
            )
            session.add(version)
            session.flush()
            return version
        if version.rules_payload != payload:
            raise ScoringConfigurationError("scoring_rule_version_conflict")
        version.is_active = True
        return version
