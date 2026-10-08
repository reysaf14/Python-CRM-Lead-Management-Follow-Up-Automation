"""M2 Gmail polling worker entrypoint."""

import logging
import time
from collections.abc import Callable

from app.adapters.gmail import GmailAdapterError, build_gmail_adapter
from app.adapters.llm import LLMAdapterError, build_llm_client
from app.core.config import get_settings
from app.core.logging import configure_logging, log_event
from app.persistence.database import get_session_factory
from app.services.gmail_polling import GmailPollingService, PollResult
from app.services.extraction import LeadExtractionService


def run_polling_loop(
    *,
    max_cycles: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    """Run bounded Gmail polling cycles, or continue until process shutdown."""

    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    try:
        adapter = build_gmail_adapter(settings)
    except GmailAdapterError as error:
        log_event(
            logger,
            action="gmail_adapter_init",
            status="failed",
            error_category=error.category,
        )
        return 1

    try:
        llm_client = build_llm_client(settings)
    except LLMAdapterError as error:
        log_event(
            logger,
            action="llm_adapter_init",
            status="failed",
            error_category=error.category,
        )
        return 1

    extraction_service = LeadExtractionService(
        llm_client=llm_client,
        session_factory=get_session_factory(),
        model=settings.llm_model,
        max_input_chars=settings.llm_max_input_chars,
        timeout_seconds=settings.llm_timeout_seconds,
        retry_max=settings.llm_retry_max,
    )

    service = GmailPollingService(
        adapter=adapter,
        session_factory=get_session_factory(),
        mailbox_key=settings.gmail_mailbox_address or "mock-mailbox",
        label_name=settings.gmail_label_name,
        extraction_service=extraction_service,
    )

    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        result: PollResult = service.poll_once()
        log_event(
            logger,
            action="gmail_poll",
            status="completed" if result.succeeded else "failed",
            error_category=result.error_category,
        )
        cycle += 1
        if max_cycles is not None and cycle >= max_cycles:
            break
        sleep_fn(settings.gmail_poll_interval_seconds)
    return 0


def main() -> None:
    run_polling_loop()


if __name__ == "__main__":
    main()
