"""M0 worker bootstrap; polling and scheduling arrive in later milestones."""

import logging

from app.core.config import get_settings
from app.core.logging import configure_logging, log_event


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log_event(
        logging.getLogger(__name__),
        action="worker_bootstrap",
        status="ready",
    )


if __name__ == "__main__":
    main()
