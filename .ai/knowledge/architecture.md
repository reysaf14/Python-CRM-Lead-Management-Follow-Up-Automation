# Architecture - Lead Management and Follow-Up Automation

**Status:** AWAITING_HUMAN_APPROVAL  
**Architecture version:** 1.0  
**Related PRD:** v1.1 (approved)  
**Lane:** Professional  
**Date:** 2026-10-08

## 1. Primary Approach and Rationale

The MVP uses a small Python application with three operational surfaces: a scheduled worker for Gmail polling and follow-up evaluation, an internal application interface for operational actions, and a Streamlit dashboard for sales review. PostgreSQL is the durable internal CRM system of record. This is proportionate to the PRD because the product must persist conversation history, deduplicate retries, preserve activity evidence, support scheduled reminders, and safely recover from provider failures.

The Gmail adapter polls only the approved business mailbox and `Sales Leads` label. It performs deterministic filtering and idempotency checks before any LLM call. Eligible messages are passed once to a provider-neutral LLM extraction adapter, which returns structured facts only. Pydantic validates the structured result; Python domain services then apply deterministic scoring, routing, and state transitions. The LLM never decides priority, status, sales ownership, or customer communication.

The application exposes an internal FastAPI service for dashboard actions and health/readiness operations. It is not a public lead-ingestion endpoint. Streamlit is selected for the sales dashboard because the MVP requires an operator-facing review surface rather than a customer-facing application. Docker Compose is selected for consistent local/private deployment of the dashboard/API, worker, and PostgreSQL because these are distinct long-running processes; it is not a production-release authorization.

### Component Responsibilities

| Component | Responsibility | Explicit boundary |
| --- | --- | --- |
| Gmail adapter | Poll the authorized mailbox and labeled messages; retrieve only required metadata/body content. | Gmail is an external provider and email content is untrusted Confidential data. |
| Preprocessing service | Apply label scope, duplicate/retry detection, auto-reply and relevance filters, and input minimization. | No LLM invocation for excluded messages. |
| LLM extraction adapter | Make one conditional structured-extraction call for an eligible message. | Provider-neutral; receives only the approved minimized excerpt and cannot invoke tools or alter workflow rules. |
| Extraction validator | Validate permitted fields and types in LLM output. | Invalid or incomplete output becomes `Pending Extraction` or manual review; it is never treated as a valid lead fact. |
| Lead domain service | Create/update lead and conversation state; score, prioritize, route, and record activity. | Deterministic business logic only. |
| Scheduler | Poll Gmail, coordinate controlled retries, and evaluate follow-up due states. | Repeated runs must be safe and must not duplicate reminders. |
| PostgreSQL | Persist Confidential internal CRM state, activity, extraction state, and reminder state. | Not a log sink; application logs remain sanitized. |
| FastAPI and Streamlit | Provide private operator actions and sales/manual-review visibility. | No public exposure or customer-facing message sending. |

## 2. Data Flow

```text
Approved Gmail mailbox / Sales Leads label
  -> deterministic pre-processing
  -> conditional structured LLM extraction
  -> schema validation
  -> deterministic lead scoring and routing
  -> PostgreSQL internal CRM state
  -> sales dashboard, manual review, and follow-up reminders
```

1. The scheduler asks the Gmail adapter for messages carrying the `Sales Leads` label.
2. The preprocessing service checks source scope, prior message identity, conversation identity, auto-reply/relevance signals, and whether the message can materially change lead facts.
3. A previously completed message is recorded as a safe duplicate and causes no second extraction, lead, or reminder. A new message in an existing conversation is appended to that conversation and is eligible for re-evaluation only when it may change approved facts.
4. For an eligible message, the preparation service removes nonessential content and submits one bounded subject/body excerpt to the LLM extraction adapter.
5. The adapter requests structured fields only: intent, service interest, stated budget, concise business summary, and extraction-confidence/ambiguity indicators. The permitted field list remains subject to Human approval.
6. The validator accepts only schema-conforming values. It records invalid, incomplete, or failed extraction as `Pending Extraction` or manual review without assigning unsupported facts.
7. The lead domain service associates the validated message with its conversation and lead, applies the approved deterministic scoring policy, records the score explanation, and schedules the applicable follow-up state.
8. The dashboard presents active leads, conversation context, priority explanation, pending extraction/manual-review work, and sales follow-up actions. A sales response is recorded through an operator action; outbound Gmail scanning is not part of this MVP.
9. The follow-up scheduler creates a sales-only reminder for an unresponded High-priority lead at the PRD-defined 24-hour deadline. It never contacts the prospect.

### Trust and State Boundaries

| Boundary | Data and trust treatment | Required behavior |
| --- | --- | --- |
| Gmail to application | External, untrusted, Confidential email content | Treat every message as data, not instructions. Verify label scope; do not execute content or use it to modify configuration. |
| Application to LLM provider | External provider boundary; minimized Confidential excerpt | Send only approved fields of the relevant message, never credentials, full recurring thread history, or unrelated records. Use strict structured output. |
| Application to PostgreSQL | Internal Confidential CRM state | Persist provider/message identity, processing state, lead/conversation history, activities, scores, and reminders transactionally. |
| Operator dashboard/API | Authorized operator boundary | Limit access to a private deployment boundary; constrain actions by operator role and avoid raw payloads in screens/logs. |

## 3. Folder Structure

The Engineer should create the following structure only when implementation begins. It separates provider adapters from deterministic domain logic, keeps dashboard concerns out of ingestion, and makes mock boundaries available to tests.

```text
app/
  api/                 internal FastAPI routes, health/readiness, operator action boundary
  dashboard/           Streamlit entrypoint and presentation-only views
  domain/              lead, conversation, scoring, reminder, and activity rules
  services/            orchestration for intake, extraction preparation, review, and follow-up
  adapters/
    gmail/             Gmail polling and message retrieval adapter
    llm/               provider-neutral extraction interface and provider implementations
  persistence/         SQLAlchemy models, repositories, migrations, and transactions
  workers/             polling, retry, and follow-up scheduler entrypoints
  core/                configuration loading, logging, redaction, and dependency wiring
tests/
  unit/                deterministic domain and validation cases
  integration/         PostgreSQL and adapter-contract cases using mocks/synthetic fixtures
  e2e/                 approved workflow scenarios using isolated mock profiles
docs/                  operator/runbook material created after implementation decisions
```

The `domain` layer must not import Gmail, LLM-provider, dashboard, or web-framework modules. Provider adapters expose normalized domain inputs/results so the Engineer can replace a provider adapter without changing scoring or routing policy.

## 4. Dependencies and Environment Variables

| Dependency or runtime component | Decision and maintenance rationale |
| --- | --- |
| Python | Selected for the requested polling, scheduling, validation, and business-automation workflow. One language keeps provider integration and deterministic rules in a maintainable codebase. |
| FastAPI and an ASGI server | Selected for a small internal operator/health interface. It supports clear request validation without creating a public lead-ingestion endpoint. |
| Streamlit | Selected for the requested sales and manual-review dashboard; it keeps the MVP focused on operational visibility. |
| PostgreSQL | Selected because durable transactional state is required for message idempotency, conversation history, activities, reminder uniqueness, and controlled retry. |
| SQLAlchemy and Alembic | Selected to keep database access, transactions, and schema changes explicit and reviewable. |
| Pydantic | Selected to validate incoming Gmail-normalized data, LLM structured output, API actions, and configuration shapes before domain logic accepts them. |
| Google Gmail client/auth libraries | Selected for Gmail API polling and least-privilege OAuth access to the approved mailbox/label. |
| Provider-neutral LLM client interface | Selected to isolate model/provider-specific transport from extraction semantics and deterministic business logic. Concrete provider adapters are configured, not embedded in the domain layer. |
| Scheduler library or controlled worker trigger | Selected for periodic Gmail polling, retry processing, and follow-up evaluation. The Engineer chooses the smallest implementation consistent with the single-worker and duplicate-safety design. |
| Pytest | Selected for synthetic, reproducible unit, integration, and workflow verification. |
| Docker Compose | Selected for local/private multi-process consistency. It does not imply production deployment or permit live credentials in files. |

The environment contract is defined in [environment-schema.md](environment-schema.md). It provides one planned root `.env.example`, explicit live/mock transport selection, source precedence, required-value behavior, secret ownership, and isolation rules. Exact operational values for polling interval, LLM input limit, timeout, retry count, and follow-up scan interval are intentionally `UNKNOWN` pending Human approval; the implementation must validate them rather than silently defaulting them.

### Authentication and Authorization

- Gmail uses a least-privilege OAuth authorization for only the approved mailbox and label. The design does not assume Google Workspace domain-wide delegation.
- Live LLM credentials are Human-provisioned through the approved secret source and are available only to the LLM adapter process.
- The internal API and dashboard are restricted to a private host or private network deployment boundary. Public exposure is not supported by this architecture. If multi-user remote access is required, a separate authentication/authorization design and approval are required.
- Application processes do not interpolate Gmail subject/body text into shell commands. No shell execution is part of the normal message-processing path.

## 5. Database

PostgreSQL is required rather than a stateless design because the MVP must preserve durable message identity, conversation/lead continuity, manual-review state, score explanations, reminders, and recovery state across polling runs and provider failures.

| Logical record | Purpose and key identity | Data handling |
| --- | --- | --- |
| `mailbox_sync_state` | Tracks each approved mailbox/label polling checkpoint and the last completed synchronization state. | Operational metadata only; never stores credentials. A failed run does not advance the successful checkpoint. |
| `messages` | Stores one received message per Gmail message identity, provider thread identity, sender metadata, processing state, and controlled conversation content reference. | Provider message ID is unique; Gmail thread ID groups conversation history. Content is Confidential and excluded from general logs. |
| `contacts` | Represents a prospect identity for internal CRM use. | Normalized contact identity supports review but does not automatically merge unrelated threads solely by sender. |
| `conversations` | Represents one Gmail thread and its associated lead relationship. | One provider thread maps to one conversation. A later message updates the thread's conversation history. |
| `leads` | Holds sales-facing lead state, status, priority, score explanation, owner, and next follow-up state. | New leads begin as `New`; status vocabulary and owner assignment remain business-policy decisions. |
| `extraction_attempts` | Records one extraction decision/attempt per eligible message/version, structured result state, validation outcome, safe error category, and retry eligibility. | Stores approved structured facts and metadata needed for review; it does not use application logs as a raw-email archive. |
| `scoring_rule_versions` and `score_evaluations` | Preserve the approved rule version, inputs, score explanation, and resulting priority. | Scoring remains deterministic and reproducible from validated facts and a rule version. |
| `activities` | Provides the lead/conversation timeline of automated and operator actions. | Activity metadata is sanitized and traceable by correlation ID. |
| `reminders` | Tracks follow-up due state, reminder uniqueness, completion, and suppression after a recorded sales response. | A unique lead/due-state relationship prevents repeat scheduler runs from creating duplicate reminders. |

### State and Idempotency Decisions

- Gmail message identity is the replay/deduplication key. A message already recorded as completed is not extracted or scored again.
- Gmail thread identity is the conversation key. A new relevant message in the same thread updates that conversation and may create a new extraction attempt only when it can change approved facts.
- A new thread from an existing sender is not automatically merged into an earlier lead. It creates a reviewable relationship until the business approves a safe sender-level merge policy.
- Extraction attempts are versioned by message and extraction-policy version, which prevents accidental repeated calls while allowing an explicitly authorized re-evaluation after policy changes or materially new information.
- External provider calls are never held inside an open database transaction. The database records pending work before the call and atomically records the final accepted, pending, or review outcome after it.

## 6. Security and Robustness Notes

### Data and Provider Security

- Gmail message content is untrusted input. The system does not execute, follow, or elevate instructions found in the subject/body, attachments, or quoted text.
- The extraction contract treats email text as delimited source data and permits only an allowlisted structured field set. The LLM adapter has no tool access, database access, configuration access, or authority to trigger sales communication.
- The preprocessing service minimizes content before an LLM request: it uses only the relevant subject/body excerpt and does not repeatedly submit full thread history, unrelated messages, credentials, headers, or internal CRM records.
- Structured output must pass Pydantic validation and business-field allowlisting before it can update internal CRM state. Invalid JSON, unsupported fields, and malformed values are rejected into `Pending Extraction` or manual review.
- Secrets are injected through the approved runtime source. They are absent from repository files, logs, responses, screenshots, fixtures, and dashboard views.

### Operational Failure Handling

| Failure or condition | Required response | Forbidden side effect |
| --- | --- | --- |
| Unlabeled, auto-reply, duplicate, or clearly irrelevant email | Persist an appropriate safe processing outcome when required; do not invoke the LLM. | Creating/scoring a lead or consuming an extraction call. |
| Gmail timeout, authorization failure, or unavailable provider | Preserve the last successful checkpoint, classify the failure, and allow a controlled later retry after provisioning/recovery. | Advancing the checkpoint, reporting success, or dropping a newly observed message. |
| LLM timeout, provider failure, or invalid structured output | Preserve the message and mark `Pending Extraction` with a sanitized error category; apply the configured bounded retry policy or manual review. | Assigning inferred facts, priority, or customer communication. |
| Database write failure | Fail the affected unit of work and retain/retry the source message from a safe checkpoint. | Partial lead/conversation/reminder state reported as complete. |
| Repeated poll or concurrent worker attempt | Use database uniqueness and a worker lease/transaction boundary to ensure one logical message/extraction/reminder outcome. | Duplicate lead, extraction call, activity, or reminder. |
| Dashboard/API access outside the approved private boundary | Deny access and log a sanitized security event. | Disclosure of customer email content or operator actions. |

### Logging, Audit, and Retention

- Every processing path uses a correlation ID and records source category, state transition, adapter category, and safe failure reason.
- Logs exclude raw subject/body, contact details, OAuth/LLM credentials, authorization headers, full structured payloads, and database rows.
- Operator history is held in CRM/activity records under access control, not copied into general logs. Retention duration remains a Human business decision and must be implemented before a production deployment.

## 7. Acceptance and Failure Scenarios

This is a design-time matrix, not execution evidence. All inputs are synthetic; no real mailbox, customer record, or provider credential is required to define these scenarios. Each scenario is required unless explicitly marked otherwise.

| AC ID / requirement | Family / applicability | Preconditions and synthetic input or fault | Expected observable result and forbidden side effect | Planned level / target |
| --- | --- | --- | --- | --- |
| AC-001 / REQ-001 | Valid input | A synthetic Gmail message has the approved `Sales Leads` label. | One intake-processing outcome is created and proceeds to deterministic pre-processing. A message outside the label cannot enter through this path. | Mock integration / required |
| AC-002 / REQ-001 | Invalid or excluded input | A synthetic message is unlabeled or labeled differently. | It is recorded as excluded only if audit policy requires it; no lead, extraction attempt, score, or reminder is created. | Unit plus mock integration / required |
| AC-003 / REQ-002 | Valid input | An eligible synthetic message has a unique provider message ID and thread ID. | One message, conversation, and initial `New` lead state are persisted with a traceable correlation ID. | Integration / required |
| AC-004 / REQ-003 | Duplicate and retry | The same synthetic provider message is delivered twice or a prior worker outcome is retried. | Exactly one logical message/lead/extraction outcome exists. No duplicate extraction, activity, or reminder is created. | Integration / required |
| AC-005 / REQ-003 | Conversation update | A new material synthetic message uses an existing provider thread ID. | The existing conversation is updated; an extraction is considered only when the message can change approved facts. A second lead is not created for that thread. | Mock integration / required |
| AC-006 / REQ-004 | Valid structured extraction | A synthetic eligible message produces schema-conforming allowed fields. | Only validated fields update CRM state and become available to deterministic scoring. | Unit plus mock integration / required |
| AC-007 / REQ-004 | Invalid extraction | A synthetic extraction has malformed JSON, unsupported fields, invalid types, or ambiguous required facts. | No unsupported field/priority is persisted; state becomes `Pending Extraction` or manual review with a safe reason. | Unit / required |
| AC-008 / REQ-005 | Deterministic decision | Identical validated synthetic facts are evaluated twice under one approved scoring-rule version. | Both evaluations produce the same score explanation and priority. | Unit / required |
| AC-009 / REQ-006 | Operator state update | An authorized synthetic operator records a sales response for an active lead. | The lead activity/status is updated and applicable pending reminder state is suppressed. Unauthorized access has no state change. | API integration / required |
| AC-010 / REQ-007 | Due and duplicate reminder | An unresponded High-priority synthetic lead reaches the PRD-defined 24-hour deadline; the scheduler runs repeatedly. | One sales-only reminder is visible. No customer message is sent and no duplicate reminder is created. | Integration / required |
| AC-011 / REQ-008 | Audit and redaction | A synthetic processing and extraction error occurs. | Activity/error records contain correlation and safe category; logs contain no raw body, contact value, token, or authorization header. | Integration / required |
| AC-012 / REQ-009 | Pipeline visibility | Controlled synthetic leads cover active, pending extraction, manual-review, due, and completed states. | The private dashboard/API returns the correct operational grouping without exposing raw payloads to unauthorized access. | API plus manual review / required |
| AC-013 / REQ-010 | Conditional invocation | Eligible, duplicate, auto-reply, irrelevant, and non-material follow-up synthetic messages are processed. | The eligible message causes exactly one extraction attempt; each excluded case causes none. | Mock integration / required |
| AC-014 / REQ-011 | Timeout and provider failure | The LLM adapter has an injected timeout or retryable provider failure. | The message becomes `Pending Extraction`, with controlled retry/manual review available and no priority assigned. | Mock integration / required |
| AC-015 / REQ-012 | Untrusted-content resistance | A synthetic email contains instruction-like and data-exfiltration language. | Only permitted schema fields may be accepted; rules, tools, credentials, and protected data remain unchanged/unavailable. | Unit plus mock integration / required |
| AC-016 / REQ-001, REQ-002 | Gmail provider failure | Gmail returns an injected authorization error, timeout, or unavailable response before a new message is durably processed. | The successful checkpoint is unchanged, the fault is visible, and no false completion or partial lead is reported. | Mock integration / required |
| AC-017 / REQ-002, REQ-008 | Transaction failure | A database failure is injected while persisting a new message/conversation/lead outcome. | No partial success is visible; the source message remains recoverable from the last safe checkpoint. | PostgreSQL integration / required |
| AC-018 / environment schema | Missing configuration | A live transport mode starts without a required Gmail, LLM, or database value. | Startup stops before network/write activity and reports only the missing variable name. | Configuration integration / required |

Webhook signature verification is **NOT_APPLICABLE** because the approved MVP has no public webhook or customer-facing inbound HTTP endpoint. Attachment extraction is **NOT_APPLICABLE** because only subject/body extraction is in scope. If either is added, the architecture and matrix require revision and approval.

## 8. Special Notes: Assumptions, Risks, and Unresolved Boundaries

### Approved Design Assumptions

- One Gmail thread is one conversation. Same-sender messages in a different thread remain unmerged unless an authorized operator links them; automatic sender-level merge is not approved.
- A sales response is recorded through the internal operator workflow. The MVP does not read or infer outbound Gmail replies.
- The initial LLM role is limited to structured extraction of approved fields. It cannot classify final priority, send a message, alter configuration, or access a tool.
- The private deployment boundary is adequate for the initial operator group. A public URL, shared remote workforce, or multi-tenant access is a material architecture change.

### Risks and Required Human Decisions

| Area | Risk or unresolved decision | Owner before implementation/release |
| --- | --- | --- |
| Business rules | Scoring criteria, thresholds, Medium/Low follow-up rules, status vocabulary, and manual-review ownership are not fixed. | Human/business owner |
| LLM data boundary | Approved extraction fields, content-minimization/redaction policy, provider-selection criteria, input limit, timeout, and retry limit are not fixed. | Human with Architect recommendation |
| Provider provisioning | Gmail OAuth and LLM credential source are unavailable until Human provisions approved least-privilege access. | Human/business administrator |
| Retention | CRM/conversation retention and deletion expectations are not defined. | Human/business owner |
| Deployment | Private-host/private-network ownership, backup, and recovery responsibilities are not defined. | Human/deployment owner |

No implementation, provider call, mailbox access, production configuration, or test execution has occurred. These are architecture decisions and planned verification targets only.

## 9. Revision History

| Version | Date | Change | Related ADR |
| --- | --- | --- | --- |
| 1.0 | 2026-10-08 | Initial Professional Lane architecture for Gmail polling, conditional LLM extraction, deterministic lead logic, PostgreSQL CRM state, scheduling, and private sales dashboard. | None; no structural revision exists yet. |
