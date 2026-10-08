"""Private Streamlit sales dashboard backed by the internal FastAPI API."""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.core.config import get_settings
from app.dashboard.client import CRMAPIClient, CRMAPIError


settings = get_settings()
st.set_page_config(page_title="Lead Management", page_icon="◈", layout="wide")

st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    [data-testid="stMetric"] { border: 1px solid #e7e7e7; border-radius: 16px; padding: 12px 16px; }
    .lead-card { border: 1px solid #e7e7e7; border-radius: 14px; padding: 14px; margin-bottom: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _client() -> CRMAPIClient:
    return CRMAPIClient(settings.api_base_url)


def _show_api_error() -> None:
    st.error("CRM API unavailable. Verify the private API and PostgreSQL services.")


def _priority_label(priority: str | None) -> str:
    return priority or "Unscored"


def _render_summary(client: CRMAPIClient) -> dict[str, Any] | None:
    try:
        summary = client.summary()
    except CRMAPIError:
        _show_api_error()
        return None
    columns = st.columns(4)
    columns[0].metric("New Leads", summary.get("new_leads", 0))
    columns[1].metric("High Priority", summary.get("high_priority_leads", 0))
    columns[2].metric("Follow-ups Due", summary.get("follow_ups_due", 0))
    columns[3].metric(
        "Pending Review",
        summary.get("pending_extraction_or_manual_review", 0),
    )
    return summary


def _render_lead_card(lead: dict[str, Any]) -> None:
    with st.container(border=True):
        st.subheader(lead.get("subject") or "Untitled inquiry")
        st.caption(lead.get("company_name") or lead.get("contact_name") or "Unknown contact")
        details = []
        if lead.get("service_interest"):
            details.append(f"Service: {lead['service_interest']}")
        if lead.get("stated_budget"):
            details.append(f"Budget: {lead['stated_budget']}")
        if details:
            st.write(" · ".join(details))
        st.write(
            f"Priority: {_priority_label(lead.get('priority'))}  ·  "
            f"Status: {lead.get('status', 'Unknown')}"
        )
        if lead.get("review_state"):
            st.warning(f"Review: {lead['review_state']}")
        if lead.get("next_follow_up_at"):
            st.caption(f"Next follow-up: {lead['next_follow_up_at']}")
        if st.button("Open detail", key=f"open-lead-{lead['id']}"):
            st.session_state["selected_lead_id"] = lead["id"]


def _render_lead_detail(client: CRMAPIClient, lead_id: int) -> None:
    try:
        detail = client.lead(lead_id)
    except CRMAPIError:
        _show_api_error()
        return

    st.divider()
    st.subheader(detail.get("subject") or "Lead detail")
    st.caption(
        f"Lead #{detail['id']} · {detail.get('contact_name') or 'Unknown contact'} · "
        f"{detail.get('contact_email', 'No email')}"
    )
    left, right = st.columns(2)
    with left:
        st.write(f"Status: {detail.get('status', 'Unknown')}")
        st.write(f"Priority: {_priority_label(detail.get('priority'))}")
        st.write(f"Score: {detail.get('score') if detail.get('score') is not None else '—'}")
        st.write(f"Service: {detail.get('service_interest') or '—'}")
        st.write(f"Budget: {detail.get('stated_budget') or '—'}")
    with right:
        st.write(f"Owner: {detail.get('owner_email') or 'Unassigned'}")
        st.write(f"Review: {detail.get('review_state') or 'None'}")
        if detail.get("score_reason"):
            st.caption(detail["score_reason"])

    with st.expander("Record sales response", expanded=False):
        correlation_id = st.text_input(
            "Action reference",
            value=f"dashboard-response:{lead_id}",
            key=f"response-correlation-{lead_id}",
        )
        if st.button("Record Response", key=f"record-response-{lead_id}"):
            try:
                outcome = client.record_response(
                    lead_id=lead_id,
                    correlation_id=correlation_id,
                )
                st.success(f"Response recorded: {outcome.get('status', 'completed')}")
                st.rerun()
            except CRMAPIError:
                _show_api_error()

    for message in detail.get("messages", []):
        with st.expander(f"Message: {message.get('subject') or 'Untitled'}"):
            st.caption(
                f"Received: {message.get('received_at')} · "
                f"State: {message.get('processing_state')}"
            )
            if message.get("content_excerpt"):
                st.write(message["content_excerpt"])

    if detail.get("activities"):
        st.write("Activity")
        st.dataframe(detail["activities"], use_container_width=True, hide_index=True)


def _render_pipeline(client: CRMAPIClient) -> None:
    st.title("Sales Pipeline")
    search = st.text_input("Search contacts, companies, or subjects", key="pipeline-search")
    priority = st.selectbox("Priority", ["All", "High", "Medium", "Low"], key="pipeline-priority")
    try:
        leads = client.leads(
            search=search or None,
            priority=None if priority == "All" else priority,
        )
    except CRMAPIError:
        _show_api_error()
        return

    statuses = sorted({lead.get("status") for lead in leads if lead.get("status")}) or ["New"]
    columns = st.columns(len(statuses))
    for column, status in zip(columns, statuses):
        with column:
            st.subheader(status)
            matching = [lead for lead in leads if lead.get("status") == status]
            if not matching:
                st.caption("No leads")
            for lead in matching:
                _render_lead_card(lead)


def _render_follow_ups(client: CRMAPIClient) -> None:
    st.title("Follow-up Tasks")
    try:
        tasks = client.follow_ups(due_only=True)
    except CRMAPIError:
        _show_api_error()
        return
    if not tasks:
        st.info("No follow-up tasks are due.")
        return
    for task in tasks:
        with st.container(border=True):
            st.subheader(task.get("subject") or "Untitled inquiry")
            st.write(task.get("contact_name") or "Unknown contact")
            st.caption(
                f"Due: {task.get('due_at')} · Priority: {_priority_label(task.get('priority'))}"
            )
            if st.button("Open lead", key=f"open-follow-up-{task['lead_id']}"):
                st.session_state["selected_lead_id"] = task["lead_id"]


def _render_manual_review(client: CRMAPIClient) -> None:
    st.title("Inbox / Manual Review")
    try:
        leads = client.manual_review()
    except CRMAPIError:
        _show_api_error()
        return
    if not leads:
        st.info("No leads require manual review.")
        return
    for lead in leads:
        _render_lead_card(lead)


with st.sidebar:
    st.title("Lead Management")
    st.caption("Private sales CRM")
    workspace = st.radio(
        "Workspace",
        ["Dashboard", "Pipeline", "Follow-up Tasks", "Inbox / Manual Review", "Settings"],
        index=0,
    )

client = _client()
if workspace == "Dashboard":
    st.title("Sales Pipeline")
    _render_summary(client)
    try:
        leads = client.leads(limit=12)
    except CRMAPIError:
        _show_api_error()
        leads = []
    if leads:
        st.subheader("Recent leads")
        columns = st.columns(min(3, len(leads)))
        for index, lead in enumerate(leads):
            with columns[index % len(columns)]:
                _render_lead_card(lead)
    else:
        st.info("No leads available yet.")
elif workspace == "Pipeline":
    _render_pipeline(client)
elif workspace == "Follow-up Tasks":
    _render_follow_ups(client)
elif workspace == "Inbox / Manual Review":
    _render_manual_review(client)
else:
    st.title("Settings")
    st.write(f"Runtime profile: `{settings.app_env}`")
    st.write("API boundary: private internal service")

selected_lead_id = st.session_state.get("selected_lead_id")
if selected_lead_id is not None and workspace != "Settings":
    _render_lead_detail(client, selected_lead_id)
