"""Google OAuth helpers for Streamlit session tokens and signed browser cookies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

GOOGLE_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
)


def client_config(client_id: str, client_secret: str, redirect_uri: str) -> dict[str, Any]:
    """Web-application client config for :class:`Flow`."""
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def build_flow(*, client_id: str, client_secret: str, redirect_uri: str) -> Flow:
    """Create an OAuth flow for Drive file + Docs edit scopes."""
    return Flow.from_client_config(
        client_config(client_id, client_secret, redirect_uri),
        scopes=list(GOOGLE_SCOPES),
        redirect_uri=redirect_uri,
    )


def credentials_to_dict(creds: Credentials) -> dict[str, Any]:
    """Serialize credentials for ``st.session_state``.

    Browser cookies store a subset of this dict (never ``client_secret``).
    """
    expiry = creds.expiry.isoformat() if creds.expiry else None
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or GOOGLE_SCOPES),
        "expiry": expiry,
    }


def credentials_from_dict(data: Mapping[str, Any]) -> Credentials:
    """Rebuild credentials from session dict and refresh if expired."""
    expiry = None
    raw_expiry = data.get("expiry")
    if isinstance(raw_expiry, str) and raw_expiry:
        try:
            expiry = datetime.fromisoformat(raw_expiry)
        except ValueError:
            expiry = None
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=str(data.get("token_uri") or "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=list(data.get("scopes") or GOOGLE_SCOPES),
    )
    if expiry is not None:
        creds.expiry = expiry
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def fetch_account_email(creds: Credentials) -> str:
    """Return the signed-in Google account email, or empty string."""
    oauth2 = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    info = oauth2.userinfo().get().execute()
    if isinstance(info, dict) and info.get("email"):
        return str(info["email"])
    return ""


def build_drive_and_docs(creds: Credentials) -> tuple[Any, Any]:
    """Construct Drive v3 and Docs v1 clients."""
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs = build("docs", "v1", credentials=creds, cache_discovery=False)
    return drive, docs
