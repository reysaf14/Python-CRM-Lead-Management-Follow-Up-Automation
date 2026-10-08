# Environment Schema

**Status:** APPROVED
**Version:** 1.0  
**Related PRD:** v1.1  
**Date:** 2026-10-08
**Approved by:** Human on 2026-10-08

This schema defines configuration metadata only. It contains no credential values, customer records, or raw Gmail content. The Engineer creates the single root `.env.example` from this approved schema; the Human provisions real secrets through the selected local or deployment secret source.

## Variable Schema

| Name | Purpose / type | Required / condition | Environment | Safe example | Owner / source | Secret? | Consumer / validation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `APP_ENV` | Application mode; enum | Required | local, test, private-operational | `test` | Engineer / runtime profile | No | All entrypoints; allow only documented values. |
| `DATABASE_URL` | Internal CRM database connection URL | Required | local, test, private-operational | Empty in template | Human / approved local or deployment secret source | Yes | Persistence layer; absent, empty, or placeholder must stop before database/network work. |
| `POSTGRES_PASSWORD` | Password for the local/private PostgreSQL container role | Required only when the Compose PostgreSQL service is used | local, test, private-operational | Empty in template | Human / approved local or deployment secret source | Yes | Compose database service; never logged, committed, or exposed to the dashboard. |
| `GMAIL_TRANSPORT` | Gmail boundary mode; enum | Required | local, test, private-operational | `mock` | Architect / runtime profile | No | Gmail adapter; only `mock` or `live` allowed. Test must use `mock`. |
| `GMAIL_OAUTH_CLIENT_ID` | Gmail OAuth client identifier | Required only when `GMAIL_TRANSPORT=live` | local, private-operational | Empty in template | Human / approved Google Cloud credential source | Yes | Gmail adapter; required before any live Gmail request. |
| `GMAIL_OAUTH_CLIENT_SECRET` | Gmail OAuth client secret | Required only when `GMAIL_TRANSPORT=live` | local, private-operational | Empty in template | Human / approved Google Cloud credential source | Yes | Gmail adapter; required before any live Gmail request. |
| `GMAIL_OAUTH_REFRESH_TOKEN` | Authorized mailbox refresh token | Required only when `GMAIL_TRANSPORT=live` | local, private-operational | Empty in template | Human / approved credential source | Yes | Gmail adapter; never logged or returned by the application. |
| `GMAIL_MAILBOX_ADDRESS` | Authorized business mailbox identity | Required only when `GMAIL_TRANSPORT=live` | local, private-operational | `sales@example.invalid` | Human / business mailbox administrator | No - Confidential | Gmail adapter; must match the approved mailbox and never appear in general logs. |
| `GMAIL_LABEL_NAME` | Intake label name | Required | local, test, private-operational | `Sales Leads` | Human / business operator | No | Gmail adapter; messages without this label are excluded. |
| `GMAIL_POLL_INTERVAL_SECONDS` | Email polling interval; positive integer | Required | local, test, private-operational | `UNKNOWN - approve operational value` | Architect / approved operational policy | No | Scheduler; reject non-positive values. |
| `LLM_TRANSPORT` | LLM boundary mode; enum | Required | local, test, private-operational | `mock` | Architect / runtime profile | No | LLM adapter; only `mock` or `live` allowed. Test must use `mock`. |
| `LLM_PROVIDER` | Provider adapter identifier | Required only when `LLM_TRANSPORT=live` | local, private-operational | `provider-name` | Human / approved provider decision | No | LLM adapter factory; must resolve to an allowlisted adapter. |
| `LLM_MODEL` | Provider model identifier | Required only when `LLM_TRANSPORT=live` | local, private-operational | `model-name` | Human / approved provider decision | No | LLM adapter; validates against the selected adapter policy. |
| `LLM_API_KEY` | LLM provider authentication material | Required only when `LLM_TRANSPORT=live` | local, private-operational | Empty in template | Human / approved credential source | Yes | LLM adapter; never logged or sent to the dashboard. |
| `LLM_BASE_URL` | Provider endpoint URL override | Optional; required only for a non-default approved endpoint | local, test, private-operational | Empty in template | Architect / approved provider profile | No | LLM adapter; must match the allowlisted selected-provider profile. |
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
- The Human provisions Gmail and LLM credentials through an approved local or deployment secret source; credentials are never pasted into chat, logs, test fixtures, or repository files.
- The Engineer documents actual consumers and validates missing-value behavior. DevOps, if later required, documents the runtime wiring and test isolation.
