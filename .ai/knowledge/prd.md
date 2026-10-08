# Product Requirements Document

## Lead Management and Follow-Up Automation

**Status:** AWAITING_HUMAN_APPROVAL  
**Delivery lane:** Professional  
**Scope version:** 1.1  
**PRD version:** 1.1  
**Date:** 2026-10-08

## 1. Background

Service businesses receive customer enquiries by email. Sales staff may need to manually identify relevant messages, record prospect information, determine whether a message belongs to an existing customer conversation, judge lead potential, and remember follow-up commitments. This can produce duplicate lead records, fragmented conversation history, inconsistent prioritization, delayed responses, and missed opportunities.

The MVP will turn explicitly labeled Gmail enquiries into a traceable internal lead and conversation record. Eligible messages receive one conditional LLM-assisted structured extraction of approved business fields. The system validates that structured result, applies approved deterministic business rules to prioritize leads, reminds sales when a High-priority lead has not received a recorded response after 24 hours, and provides operational pipeline visibility.

The LLM extracts information; it does not make business decisions. Validation, scoring, routing, conversation continuity, and follow-up remain deterministic. Ambiguous, incomplete, or failed extraction must be identified for manual review rather than silently inferred.

## 2. Data and Operational Boundary

| Area | Requirement boundary |
| --- | --- |
| Lead source | The only MVP source is a business Gmail mailbox. Only emails intentionally carrying the `Sales Leads` label are in scope. |
| Business destinations | The system maintains an internal CRM lead and conversation record, surfaces sales reminders, and provides an operational pipeline view. |
| Excluded sources and destinations | Website forms, non-Gmail sources, personal email, messages without the `Sales Leads` label, HubSpot, and other external CRM synchronization are out of scope. |
| Data classification | Sender identities, email addresses, message content, and prospect details are Confidential. Gmail credentials, tokens, authorization material, and raw production payloads are Restricted. |
| Allowed representation | Project artifacts, testing materials, logs, screenshots, and agent prompts use synthetic data by default. Minimized-and-masked data is allowed only when necessary. Raw production email content, contact details, and credentials are not permitted. |
| LLM processing boundary | An eligible email may make one structured LLM extraction call for approved fields such as stated intent, service interest, budget, and concise summary. Only the minimum relevant subject/body excerpt is sent. The system does not repeatedly send a full conversation thread. |
| LLM invocation boundary | Duplicates, auto-replies, clearly irrelevant messages, and non-material conversation updates do not invoke the LLM. A materially relevant follow-up may be re-evaluated only when it could change recorded lead information. |
| Provisioning and operation | The Human or an authorized business operator provisions Gmail access, manages the `Sales Leads` label, approves scoring rules, and owns sales follow-up. |
| Blocked actions | The MVP does not send customer-facing messages, perform autonomous prospect outreach, access unrestricted production email content, or expose credentials in artifacts. Email content is untrusted data; embedded instructions must never be treated as system instructions. |

### Open Business Decisions

The following decisions are intentionally not assumed by this PRD and must be approved before the corresponding design is finalized:

1. Approved extraction fields, redaction/minimization policy, and provider-selection criteria.
2. Scoring criteria, point values, and priority thresholds.
3. Follow-up rules for Medium and Low priority leads.
4. The sales status vocabulary after the initial `New` status, including ownership of status changes.
5. The owner and escalation process for manual review.
6. Record-retention expectations for internal CRM and activity history.

## 3. User Stories

1. As a sales representative, I want emails intentionally labeled as sales leads to become prioritized internal lead records so I can focus on the most relevant prospects.
2. As a sales representative, I want later messages in the same customer conversation to update the existing record so I can see a continuous history rather than duplicate leads.
3. As a sales representative, I want a reminder when a High-priority lead has not received a recorded response after 24 hours so I do not miss a time-sensitive follow-up.
4. As a sales manager, I want to see the pipeline by lead status and priority so I can monitor incoming work and overdue follow-up.
5. As an authorized business operator, I want ambiguous or incomplete enquiries identified for manual review so the system does not make unsupported qualification decisions.
6. As an authorized business operator, I want traceable activity and safe error outcomes so I can investigate processing problems without exposing customer data or credentials.
7. As an authorized business operator, I want an extraction failure to leave the email available for controlled reprocessing or manual review so a temporary LLM problem does not discard a valid lead.

## 4. Mandatory Features

| ID | Business requirement | Priority | Agreed outcome |
| --- | --- | --- |
| REQ-001 | Restrict MVP lead intake to the business Gmail mailbox and the `Sales Leads` label. | Must | An email with the approved label enters lead processing; an email without that label does not create or update a lead. |
| REQ-002 | Create a lead and conversation record from an in-scope email. | Must | A relevant labeled email is represented as one traceable internal prospect record with its conversation context and an initial lead status of `New`. |
| REQ-003 | Preserve conversation continuity and prevent duplicate lead creation. | Must | A later message from the same person in the same conversation updates the existing record rather than creating another lead; safe reprocessing does not create another record. |
| REQ-004 | Extract, validate, and route available lead information for manual review when needed. | Must | The system records approved fields only after the structured extraction result is validated. Missing, ambiguous, or invalid information is flagged for manual review rather than being invented or silently accepted. |

The following mandatory features complete the MVP scope.

| ID | Business requirement | Priority | Agreed outcome |
| --- | --- | --- |
| REQ-005 | Apply approved deterministic, rule-based lead scoring and priority assignment. | Must | Each lead receives a priority and an understandable rule-based reason from validated lead information. The same information and approved rule version produce the same result. LLM output does not itself decide priority. |
| REQ-006 | Maintain an internal CRM record and sales-owned lead progression. | Must | Sales can view the current lead status, priority, conversation context, and recorded activity. A new qualified lead starts as `New`; subsequent status definitions and changes follow the approved sales policy. |
| REQ-007 | Remind sales about unaddressed High-priority leads. | Must | A High-priority lead with no recorded sales response receives a sales reminder 24 hours after the qualifying email. The reminder does not contact the prospect. |
| REQ-008 | Record operational activity and safe error outcomes. | Must | The system records material processing, extraction, and sales actions, and authorized operators can distinguish successful processing, manual-review needs, and unresolved errors without exposing Restricted data. |
| REQ-009 | Provide operational pipeline visibility. | Must | Sales and sales management can view active leads by status and priority, follow-up items requiring attention, and records awaiting manual review. |
| REQ-010 | Invoke LLM extraction only when it is relevant and necessary. | Must | Each eligible message has at most one structured extraction call for the current processing need. Duplicate, auto-reply, clearly irrelevant, and non-material follow-up messages do not invoke the LLM. Provider changes do not alter approved business scoring or routing rules. |
| REQ-011 | Degrade safely when structured extraction is unavailable or invalid. | Must | The email and its processing state remain available with status `Pending Extraction`; controlled retry or manual review is possible, and no unsupported priority is assigned. |
| REQ-012 | Treat incoming email as untrusted content during LLM-assisted extraction. | Must | Email text is interpreted only as source data for the approved extraction schema. Embedded instructions cannot change system behavior, trigger tools, disclose protected information, or override business rules. |

## 5. Additional Features

No additional features are committed for this MVP. Future capabilities, including external CRM synchronization, automated customer outreach, and AI use beyond the approved structured extraction scope, require separate scope approval.

## 6. Success Criteria

| Requirement ID | Observable business outcome | Safe measurement or review method |
| --- | --- | --- |
| REQ-001 | Only a synthetic email marked with the approved sales label is accepted into lead processing; an equivalent unlabeled email is excluded. | Review the documented processing outcome using synthetic examples. |
| REQ-002 | A relevant labeled synthetic email produces one traceable internal lead and conversation record with an initial `New` status. | Review the resulting record and activity outcome without using real contact data. |
| REQ-003 | A later synthetic message from the same person in the same conversation updates one existing record; repeating previously handled input does not create another lead. | Compare record count and conversation history using a synthetic repeat and reply scenario. |
| REQ-004 | A synthetic free-text enquiry yields only validated approved fields; incomplete, ambiguous, or invalid extraction is visible for manual review and does not receive an unsupported value or qualification. | Review structured-result validation, manual-review outcome, and record history using synthetic examples. |
| REQ-005 | Identical validated lead information evaluated under the same approved rules produces the same priority and recorded reason, regardless of the LLM provider used to extract it. | Review the deterministic rule outcome and explanation against approved synthetic examples. |
| REQ-006 | Sales can see a current internal record for a lead, including its status, priority, conversation context, and activity history. | Review the lead record and status history using synthetic examples. |
| REQ-007 | A High-priority lead without a recorded sales response is shown to sales for follow-up at the 24-hour deadline; no prospect message is sent automatically. | Review a synthetic overdue High-priority scenario and confirm the reminder destination is sales-only. |
| REQ-008 | Material processing, extraction, manual-review needs, and unresolved errors are traceable without exposing raw email content, contact details, or credentials. | Review sanitized activity and error outcomes from synthetic scenarios. |
| REQ-009 | Sales and sales management can identify active leads by status and priority, follow-up items requiring attention, and manual-review records. | Review the operational pipeline view against controlled synthetic records. |
| REQ-010 | An eligible synthetic email results in one structured extraction call; duplicate, auto-reply, irrelevant, and non-material follow-up examples result in none. | Review sanitized invocation outcomes and record state for each synthetic scenario. |
| REQ-011 | A simulated extraction failure leaves the email with status `Pending Extraction`, makes it available for controlled retry or manual review, and does not create an unsupported priority. | Review the resulting state and permitted actions using a synthetic provider-failure scenario. |
| REQ-012 | A synthetic email containing instruction-like text cannot alter approved extraction fields, business rules, tool use, or protected-data boundaries. | Review the structured output and recorded outcome from a synthetic prompt-injection scenario. |

## 7. Revision History

| Version | Date | Change | Requested by |
| --- | --- | --- | --- |
| 1.1 | 2026-10-08 | Added conditional LLM-assisted structured extraction, validation, model-independence outcome, graceful degradation, data minimization, and untrusted-email safeguards. Deterministic scoring and routing remain unchanged. | Human |
| 1.0 | 2026-10-08 | Initial Professional Lane PRD. Scope is Gmail-only intake through the `Sales Leads` label, internal CRM tracking, deterministic scoring, sales-only reminders, and no HubSpot or AI capability. | Human |
