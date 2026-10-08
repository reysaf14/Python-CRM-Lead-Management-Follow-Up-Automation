"""Internal health surface for the M0 container foundation."""

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging


settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="Lead Management and Follow-Up Automation")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Return a non-sensitive liveness response."""

    return {"status": "ok"}


@app.get("/ready", tags=["system"])
def ready() -> dict[str, str]:
    """Expose configuration readiness without probing external providers in M0."""

    return {"status": "ready"}
