import pytest
from pydantic import ValidationError

from app.core.config import Settings


BASE_ENV = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+psycopg://crm:test@localhost:5432/crm_test",
    "GMAIL_TRANSPORT": "mock",
    "GMAIL_LABEL_NAME": "Sales Leads",
    "GMAIL_POLL_INTERVAL_SECONDS": "60",
    "LLM_TRANSPORT": "mock",
    "LLM_MAX_INPUT_CHARS": "1000",
    "LLM_TIMEOUT_SECONDS": "10",
    "LLM_RETRY_MAX": "1",
    "FOLLOW_UP_SCAN_INTERVAL_SECONDS": "60",
    "OPERATOR_ACCESS_MODE": "private-host-only",
}


def settings_from(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    values = {**BASE_ENV, **overrides}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return Settings()


def test_test_profile_accepts_only_mock_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_from(monkeypatch)

    assert settings.app_env == "test"
    assert settings.gmail_transport == "mock"
    assert settings.llm_transport == "mock"


def test_missing_database_url_fails_before_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {**BASE_ENV}
    values.pop("DATABASE_URL")
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings()


def test_test_profile_rejects_live_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="APP_ENV=test"):
        settings_from(monkeypatch, GMAIL_TRANSPORT="live")


def test_live_gmail_requires_all_authorization_values(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="GMAIL_OAUTH_CLIENT_ID"):
        settings_from(
            monkeypatch,
            APP_ENV="local",
            GMAIL_TRANSPORT="live",
            GMAIL_OAUTH_CLIENT_ID="",
            GMAIL_OAUTH_CLIENT_SECRET="synthetic-secret",
            GMAIL_OAUTH_REFRESH_TOKEN="synthetic-refresh-token",
            GMAIL_MAILBOX_ADDRESS="sales@example.invalid",
        )

