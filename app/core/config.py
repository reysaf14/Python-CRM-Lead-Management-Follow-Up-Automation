"""Fail-fast application configuration loaded from process environment only."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PositiveInt, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


AppEnvironment = Literal["local", "test", "private-operational"]
TransportMode = Literal["mock", "live"]
ServiceRole = Literal["application", "api", "worker", "dashboard"]

APPROVED_GMAIL_LABEL_NAME = "Sales Leads"
SUPPORTED_LLM_PROVIDERS = {"deepseek"}
DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"


class Settings(BaseSettings):
    """Validated runtime settings.

    The loader intentionally does not read .env files. Launchers must provide
    the selected profile explicitly, which prevents tests from falling back to
    developer or production configuration.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    service_role: ServiceRole = Field(default="application", validation_alias="SERVICE_ROLE")
    app_env: AppEnvironment = Field(validation_alias="APP_ENV")
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    api_base_url: str = Field(
        default="http://api:8000",
        validation_alias="API_BASE_URL",
        min_length=1,
    )
    operator_access_token: SecretStr | None = Field(
        default=None, validation_alias="OPERATOR_ACCESS_TOKEN"
    )

    gmail_transport: TransportMode = Field(
        default="mock", validation_alias="GMAIL_TRANSPORT"
    )
    gmail_oauth_client_id: SecretStr | None = Field(
        default=None, validation_alias="GMAIL_OAUTH_CLIENT_ID"
    )
    gmail_oauth_client_secret: SecretStr | None = Field(
        default=None, validation_alias="GMAIL_OAUTH_CLIENT_SECRET"
    )
    gmail_oauth_refresh_token: SecretStr | None = Field(
        default=None, validation_alias="GMAIL_OAUTH_REFRESH_TOKEN"
    )
    gmail_mailbox_address: str | None = Field(
        default=None, validation_alias="GMAIL_MAILBOX_ADDRESS"
    )
    gmail_label_name: str = Field(
        default=APPROVED_GMAIL_LABEL_NAME,
        validation_alias="GMAIL_LABEL_NAME",
        min_length=1,
    )
    gmail_poll_interval_seconds: PositiveInt = Field(
        default=60, validation_alias="GMAIL_POLL_INTERVAL_SECONDS"
    )

    llm_transport: TransportMode = Field(default="mock", validation_alias="LLM_TRANSPORT")
    llm_provider: str | None = Field(default=None, validation_alias="LLM_PROVIDER")
    llm_model: str | None = Field(default=None, validation_alias="LLM_MODEL")
    llm_api_key: SecretStr | None = Field(default=None, validation_alias="LLM_API_KEY")
    llm_base_url: str | None = Field(default=None, validation_alias="LLM_BASE_URL")
    llm_max_input_chars: PositiveInt = Field(
        default=320, validation_alias="LLM_MAX_INPUT_CHARS"
    )
    llm_timeout_seconds: PositiveInt = Field(
        default=5, validation_alias="LLM_TIMEOUT_SECONDS"
    )
    llm_retry_max: int = Field(default=1, validation_alias="LLM_RETRY_MAX", ge=0)

    follow_up_scan_interval_seconds: PositiveInt = Field(
        default=60, validation_alias="FOLLOW_UP_SCAN_INTERVAL_SECONDS"
    )
    log_level: Literal["debug", "info", "warning", "error", "critical"] = Field(
        default="info", validation_alias="LOG_LEVEL"
    )
    operator_access_mode: Literal["private-host-only"] = Field(
        default="private-host-only", validation_alias="OPERATOR_ACCESS_MODE"
    )

    @model_validator(mode="after")
    def validate_transport_requirements(self) -> "Settings":
        if self.app_env == "test" and (
            self.gmail_transport != "mock" or self.llm_transport != "mock"
        ):
            raise ValueError("APP_ENV=test requires GMAIL_TRANSPORT=mock and LLM_TRANSPORT=mock")

        if self.gmail_label_name != APPROVED_GMAIL_LABEL_NAME:
            raise ValueError(
                f"GMAIL_LABEL_NAME must be exactly {APPROVED_GMAIL_LABEL_NAME!r}"
            )

        if self.service_role != "dashboard":
            self._require_text(self.database_url, "DATABASE_URL")

        if self.service_role in {"application", "api", "dashboard"} and self.app_env != "test":
            self._require_secret(self.operator_access_token, "OPERATOR_ACCESS_TOKEN")

        if self.gmail_transport == "live":
            self._require_secret(self.gmail_oauth_client_id, "GMAIL_OAUTH_CLIENT_ID")
            self._require_secret(self.gmail_oauth_client_secret, "GMAIL_OAUTH_CLIENT_SECRET")
            self._require_secret(self.gmail_oauth_refresh_token, "GMAIL_OAUTH_REFRESH_TOKEN")
            self._require_text(self.gmail_mailbox_address, "GMAIL_MAILBOX_ADDRESS")

        if self.llm_transport == "live":
            self._require_text(self.llm_provider, "LLM_PROVIDER")
            self._require_text(self.llm_model, "LLM_MODEL")
            self._require_secret(self.llm_api_key, "LLM_API_KEY")
            if self.llm_provider not in SUPPORTED_LLM_PROVIDERS:
                raise ValueError("LLM_PROVIDER is not allowlisted for live transport")
            if self.llm_base_url and self.llm_base_url.rstrip("/") != DEEPSEEK_DEFAULT_BASE_URL:
                raise ValueError("LLM_BASE_URL must use the allowlisted DeepSeek endpoint")

        return self

    @staticmethod
    def _require_text(value: str | None, name: str) -> None:
        if value is None or not value.strip():
            raise ValueError(f"{name} is required for the selected transport mode")

    @staticmethod
    def _require_secret(value: SecretStr | None, name: str) -> None:
        if value is None or not value.get_secret_value().strip():
            raise ValueError(f"{name} is required for the selected transport mode")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one validated settings object per process."""

    return Settings()
