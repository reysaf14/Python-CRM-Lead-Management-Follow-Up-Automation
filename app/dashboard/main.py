"""M0 dashboard shell; operational views arrive in later milestones."""

import streamlit as st

from app.core.config import get_settings


settings = get_settings()
st.set_page_config(page_title="Lead Management", layout="wide")

with st.sidebar:
    st.title("Lead Management")
    st.caption("M0 foundation")
    st.radio("Workspace", ["Dashboard", "Pipeline", "Follow-up Tasks", "Manual Review"], index=0)

st.title("Lead Management and Follow-Up Automation")
st.info(
    "The M0 foundation is ready. Gmail intake, extraction, CRM records, and operational views "
    "are implemented in later milestones."
)
st.caption(f"Runtime profile: {settings.app_env}")
