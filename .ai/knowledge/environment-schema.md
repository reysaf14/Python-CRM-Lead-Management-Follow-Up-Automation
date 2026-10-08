# Environment Schema

**Status:** APPROVED BASELINE WITH ENGINEERING EXTENSION
**Version:** 1.3
**Related PRD:** v1.1  
**Date:** 2026-10-08
**Approved by:** Human on 2026-10-08 for baseline v1.0; M6 added the internal API URL extension.

This schema defines configuration metadata only. It contains no credential values, customer records, or raw Gmail content. The Engineer creates the single root `.env.example` from this approved schema; the Human provisions real secrets through the selected local or deployment secret source.

## Variable Schema

| Name | Purpose / type | Required / condition | Environment | Safe example | Owner / source | Secret? | Consumer / validation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `APP_ENV` | Application mode; enum | Required | local, test, private-operational | `test` | Engineer / runtime profile | No | All entrypoints; allow only documented values. |
| `SERVICE_ROLE` | Process role; enum | Required | local, test, private-operational | `application` | Engineer / runtime profile | No | API, worker, dashboard, or application configuration; controls least-privilege required settings. |
| `DATABASE_URL` | Internal CRM database connection URL | Required | local, test, private-operational | Empty in template | Human / approved local or deployment secret source | Yes | Persistence layer; absent, empty, or placeholder must stop before database/network work. |
| `POSTGRES_PASSWORD` | Password for the local/private PostgreSQL container role | Required only when the Compose PostgreSQL service is used | local, test, private-operational | Empty in template | Human / approved local or deployment secret source | Yes | Compose database service; never logged, committed, or exposed to the dashboard. |
| `API_BASE_URL` | Internal FastAPI base URL used by the Streamlit dashboard | Required by the dashboard process; defaults to `http://api:8000` in application settings | local, test, private-operational | `http://api:8000` | Human / deployment configuration | No | Private internal service URL only; never a public customer endpoint. |
| `OPERATOR_ACCESS_TOKEN` | Shared private operator API token for the current single-operator MVP | Required for API, dashboard, and application roles outside test profile | local, private-operational | Empty in template | Human / approved secret source | Yes | FastAPI operator routes and Streamlit API client; compared in constant time and never logged. |
| `SOURCE_MANIFEST_SHA256` | Canonical SHA-256 of the effective Docker build target input manifest | Required only when Docker Compose builds an application image | local, test, private-operational | Empty in template | Engineer build script | No | Compose build argument; must be generated from committed Docker inputs and is embedded in the image label. |
| `SOURCE_CANDIDATE_ID` | Immutable source candidate identifier in the form `git:<full-commit-SHA>` | Required only when Docker Compose builds an application image | local, test, private-operational | Empty in template | Engineer build script | No | Compose build argument; must match the source candidate recorded in the manifest and image label. |
| `GMAIL_TRANSPORT` | Gmail boundary mode; enum | Required | local, test, private-operational | `mock` | Architect / runtime profile | No | Gmail adapter; only `mock` or `live` allowed. Test must use `mock`. |
| `GMAIL_OAUTH_CLIENT_ID` | Gmail OAuth client identifier | Required only when `GMAIL_TRANSPORT=live` | local, private-operational | Empty in template | Human / approved Google Cloud credential source | Yes | Gmail adapter; required before any live Gmail request. |
| `GMAIL_OAUTH_CLIENT_SECRET` | Gmail OAuth client secret | Required only when `GMAIL_TRANSPORT=live` | local, private-operational | Empty in template | Human / approved Google Cloud credential source | Yes | Gmail adapter; required before any live Gmail request. |
| `GMAIL_OAUTH_REFRESH_TOKEN` | Authorized mailbox refresh token | Required only when `GMAIL_TRANSPORT=live` | local, private-operational | Empty in template | Human / approved credential source | Yes | Gmail adapter; never logged or returned by the application. |
| `GMAIL_MAILBOX_ADDRESS` | Authorized business mailbox identity | Required only when `GMAIL_TRANSPORT=live` | local, private-operational | `sales@example.invalid` | Human / business mailbox administrator | No - Confidential | Gmail adapter; must match the approved mailbox and never appear in general logs. |
| `GMAIL_LABEL_NAME` | Intake label name | Required | local, test, private-operational | `Sales Leads` | Human / business operator | No | Gmail adapter; messages without this label are excluded. |
| `GMAIL_POLL_INTERVAL_SECONDS` | Email polling interval; positive integer | Required | local, test, private-operational | `UNKNOWN - approve operational value` | Architect / approved operational policy | No | Scheduler; reject non-positive values. |
| `LLM_TRANSPORT` | LLM boundary mode; enum | Required | local, test, private-operational | `mock` | Architect / runtime profile | No | LLM adapter; only `mock` or `live` allowed. Test must use `mock`. |
| `LLM_PROVIDER` | Provider adapter identifier | Required only when `LLM_TRANSPORT=live` | local, private-operational | `deepseek` | Human / approved provider decision | No | LLM adapter factory; currently allowlists `deepseek`. |
| `LLM_MODEL` | Provider model identifier | Required only when `LLM_TRANSPORT=live` | local, private-operational | `approved-model-name` | Human / approved provider decision | No | LLM adapter; required for the selected provider. |
| `LLM_API_KEY` | LLM provider authentication material | Required only when `LLM_TRANSPORT=live` | local, private-operational | Empty in template | Human / approved credential source | Yes | LLM adapter; never logged or sent to the dashboard. |
| `LLM_BASE_URL` | Provider endpoint URL override | Optional; only the allowlisted DeepSeek endpoint is accepted | local, test, private-operational | `https://api.deepseek.com` | Architect / approved provider profile | No | LLM adapter; exact host allowlist prevents arbitrary outbound endpoint configuration. |
| `LLM_MAX_INPUT_CHARS` | Maximum minimized subject/body input length | Required | local, test, private-operational | `UNKNOWN - approve data-minimization limit` | Architect / approved data-minimization policy | No | Extraction-preparation service; reject values outside approved bounds. |
| `LLM_TIMEOUT_SECONDS` | Per-extraction timeout; positive integer | Required | local, test, private-operational | `UNKNOWN - approve timeout` | Architect / approved operational policy | No | LLM adapter; timeout produces `Pending Extraction`, not a successful lead qualification. |
| `LLM_RETRY_MAX` | Maximum controlled retry count for retryable extraction failures | Required | local, test, private-operational | `UNKNOWN - approve retry limit` | Architect / approved operational policy | No | Retry coordinator; reject negative values. |
| `FOLLOW_UP_SCAN_INTERVAL_SECONDS` | Follow-up evaluation interval; positive integer | Required | local, test, private-operational | `UNKNOWN - approve operational value` | Architect / approved operational policy | No | Scheduler; repeated scans must not duplicate reminders. |
| `LOG_LEVEL` | Application log level; enum | Optional | local, test, private-operational | `info` | Engineer / application default | No | Logger; cannot disable redaction. |
| `OPERATOR_ACCESS_MODE` | Dashboard/API access policy; enum | Required | local, test, private-operational | `private-host-only` | Human / deployment owner | No | API and dashboard entrypoints; public exposure is not supported by this architecture. |

## Runtime Profiles and Loading

| Profile | Working boundary and target | Source precedence | Required safeguards |
| --- | --- | --- | --- |
| Local development | Project root; local PostgreSQL and explicitly selected mock or approved live adapters | Process environment overrides `.env`; `.env` is optional and Human-managed | Missing required values stop before network/write. Live Gmail or LLM access requires Human-provisioned credentials and explicit transport mode. |
| Isolated test | Project root; synthetic database and mock Gmail/LLM adapters only | Process environment overrides `.env.test`; test mode must never fall back to `.env` | No production mailbox, provider, database, inherited credentials, or raw customer data. |
| Private operational | Private host or private network deployment; approved CRM database and live adapters | Injected process environment or approved secret source overrides optional deployment file | Only approved operators may reach the dashboard/API. Public exposure, unrestricted shell inheritance, and production-secret logging are prohibited. |

All entrypoints use the same explicit configuration loader. Required live-mode values that are absent, blank, or placeholders cause startup failure before any Gmail, LLM, or database side effect. Business scoring policy is versioned application data, not an environment variable.

## Provisioning and Handoff Notes

- The Engineer creates one root `.env.example` with safe examples from this schema and no actual credential values.
- Before a Compose image build, the Engineer generates the target manifest from committed Docker inputs and sets `SOURCE_MANIFEST_SHA256` and `SOURCE_CANDIDATE_ID` from that output. Omitted or placeholder provenance values must fail the image build before dependency installation.
- Live LLM transport currently supports only the explicitly allowlisted DeepSeek Chat Completions endpoint. The Human provisions the API key and model selection outside the repository; the Engineer must use synthetic transport tests when those values are unavailable.
- The Human provisions Gmail and LLM credentials through an approved local or deployment secret source; credentials are never pasted into chat, logs, test fixtures, or repository files.
- The Engineer documents actual consumers and validates missing-value behavior. DevOps, if later required, documents the runtime wiring and test isolation.
