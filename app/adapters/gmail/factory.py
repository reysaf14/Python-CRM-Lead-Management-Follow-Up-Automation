"""Gmail adapter construction from the validated runtime profile."""

from app.adapters.gmail.client import GmailAdapter, LiveGmailAdapter, MockGmailAdapter
from app.core.config import Settings


def build_gmail_adapter(settings: Settings) -> GmailAdapter:
    """Build the selected Gmail boundary without silently changing transports."""

    if settings.gmail_transport == "mock":
        return MockGmailAdapter(pages=())
    return LiveGmailAdapter(settings)
