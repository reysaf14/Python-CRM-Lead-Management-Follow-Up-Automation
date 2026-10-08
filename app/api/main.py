"""Private operator API for CRM visibility and sales actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_crm_session_factory, get_db_session, require_operator
from app.api.schemas import (
    FollowUpResponse,
    LeadCardResponse,
    LeadDetailResponse,
    RecordResponseRequest,
    RecordResponseResult,
    SummaryResponse,
)
from app.persistence.base import utc_now
from app.services.crm_views import CRMViewService
from app.services.follow_up import SalesResponseService


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_operator)])
views = CRMViewService()


def _database_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"error_category": "database_unavailable"},
    )


@router.get("/dashboard/summary", response_model=SummaryResponse, tags=["dashboard"])
def dashboard_summary(session: Session = Depends(get_db_session)) -> SummaryResponse:
    try:
        return SummaryResponse(**views.summary(session, now=utc_now()))
    except SQLAlchemyError as error:
        session.rollback()
        raise _database_unavailable() from error


@router.get("/leads", response_model=list[LeadCardResponse], tags=["leads"])
def list_leads(
    status: str | None = Query(default=None, max_length=40),
    priority: str | None = Query(default=None, max_length=20),
    search: str | None = Query(default=None, max_length=120),
    review_only: bool = False,
    limit: int = Query(default=100, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> list[LeadCardResponse]:
    try:
        cards = views.list_leads(
            session,
            status=status,
            priority=priority,
            search=search,
            review_only=review_only,
            limit=limit,
        )
        return [LeadCardResponse(**card) for card in cards]
    except SQLAlchemyError as error:
        session.rollback()
        raise _database_unavailable() from error


@router.get("/leads/{lead_id}", response_model=LeadDetailResponse, tags=["leads"])
def get_lead(lead_id: int, session: Session = Depends(get_db_session)) -> LeadDetailResponse:
    try:
        detail = views.get_lead_detail(session, lead_id=lead_id)
    except SQLAlchemyError as error:
        session.rollback()
        raise _database_unavailable() from error
    if detail is None:
        raise HTTPException(status_code=404, detail={"error_category": "lead_not_found"})
    return LeadDetailResponse(**detail)


@router.get("/manual-review", response_model=list[LeadCardResponse], tags=["review"])
def manual_review_queue(
    limit: int = Query(default=100, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> list[LeadCardResponse]:
    try:
        cards = views.list_leads(session, review_only=True, limit=limit)
        return [LeadCardResponse(**card) for card in cards]
    except SQLAlchemyError as error:
        session.rollback()
        raise _database_unavailable() from error


@router.get("/follow-ups", response_model=list[FollowUpResponse], tags=["follow-up"])
def follow_up_queue(
    due_only: bool = True,
    limit: int = Query(default=100, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> list[FollowUpResponse]:
    try:
        tasks = views.list_follow_ups(
            session,
            now=utc_now(),
            due_only=due_only,
            limit=limit,
        )
        return [FollowUpResponse(**task) for task in tasks]
    except SQLAlchemyError as error:
        session.rollback()
        raise _database_unavailable() from error


@router.post(
    "/leads/{lead_id}/response",
    response_model=RecordResponseResult,
    tags=["operator-actions"],
)
def record_sales_response(
    lead_id: int,
    request: RecordResponseRequest,
    session_factory: sessionmaker[Session] = Depends(get_crm_session_factory),
) -> RecordResponseResult:
    outcome = SalesResponseService(session_factory=session_factory).record_response(
        lead_id=lead_id,
        correlation_id=request.correlation_id,
    )
    if outcome.status == "failed" and outcome.error_category == "lead_not_found":
        raise HTTPException(status_code=404, detail={"error_category": "lead_not_found"})
    if outcome.status == "failed":
        raise _database_unavailable()
    return RecordResponseResult(
        status=outcome.status,
        suppressed_reminder_count=outcome.suppressed_reminder_count,
    )


def create_app() -> FastAPI:
    """Build the API without opening providers or database connections at import time."""

    application = FastAPI(
        title="Lead Management and Follow-Up Automation",
        description="Private operator API for internal CRM visibility and actions.",
        version="0.1.0",
    )

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Return a non-sensitive liveness response."""

        return {"status": "ok"}

    @application.get("/ready", tags=["system"])
    def ready(
        session_factory: sessionmaker[Session] = Depends(get_crm_session_factory),
    ) -> dict[str, str]:
        """Check database readiness without returning provider or credential details."""

        session = session_factory()
        try:
            session.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            raise _database_unavailable() from error
        finally:
            session.close()
        return {"status": "ready"}

    application.include_router(router)
    return application


app = create_app()
