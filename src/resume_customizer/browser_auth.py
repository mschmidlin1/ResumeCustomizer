"""Read and write signed browser cookies for Streamlit login and Google OAuth."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from resume_customizer.auth_cookies import (
    APP_COOKIE_NAME,
    APP_MAX_AGE_SECONDS,
    GOOGLE_COOKIE_NAME,
    GOOGLE_MAX_AGE_SECONDS,
    OAUTH_STATE_COOKIE_NAME,
    OAUTH_STATE_MAX_AGE_SECONDS,
    sign_app_cookie,
    sign_google_cookie,
    sign_oauth_state_cookie,
    token_dict_from_browser_credentials,
    verify_app_cookie,
    verify_google_cookie,
    verify_oauth_state_cookie,
)
from resume_customizer.google_auth import credentials_from_dict, credentials_to_dict
from resume_customizer.secrets_config import get_auth_password, get_google_client_secret

_FRONTEND_DIR = Path(__file__).resolve().parent / "cookie_bridge_frontend"
_cookie_bridge = components.declare_component("rc_cookie_bridge", path=str(_FRONTEND_DIR))


def signing_secret() -> str | None:
    """Return the shared app password used to sign browser cookies, or ``None``."""
    return get_auth_password()


def _read_cookie(name: str) -> str | None:
    cookies = getattr(st.context, "cookies", None)
    if cookies is None:
        return None
    try:
        value = cookies.get(name)
    except Exception:
        return None
    if not value:
        return None
    return str(value)


def restore_from_cookies() -> None:
    """Fill empty session keys from signed cookies (new browser session only)."""
    secret = signing_secret()
    if not secret:
        return
    if not st.session_state.get("authenticated") and verify_app_cookie(_read_cookie(APP_COOKIE_NAME), secret):
        st.session_state.authenticated = True
    if not st.session_state.get("google_token"):
        payload = verify_google_cookie(_read_cookie(GOOGLE_COOKIE_NAME), secret)
        client_secret = get_google_client_secret()
        if payload and client_secret:
            token_dict = token_dict_from_browser_credentials(payload["creds"], client_secret)
            try:
                creds = credentials_from_dict(token_dict)
                st.session_state.google_token = credentials_to_dict(creds)
                st.session_state.google_email = payload.get("email") or ""
            except Exception:
                st.caption("Could not restore Google sign-in from cookies; Connect Google again if needed.")
    if not st.session_state.get("google_token") and not st.session_state.get("google_oauth_state"):
        handshake = verify_oauth_state_cookie(_read_cookie(OAUTH_STATE_COOKIE_NAME), secret)
        if handshake:
            st.session_state.google_oauth_state = handshake["state"]
            if handshake["verifier"]:
                st.session_state.google_oauth_code_verifier = handshake["verifier"]


def cookie_assignments() -> list[dict[str, Any]]:
    """Cookie set/delete ops that match the current session."""
    secret = signing_secret()
    if not secret:
        return []
    assignments: list[dict[str, Any]] = []
    if st.session_state.get("authenticated"):
        assignments.append(
            {
                "name": APP_COOKIE_NAME,
                "value": sign_app_cookie(secret),
                "maxAge": APP_MAX_AGE_SECONDS,
            }
        )
    else:
        assignments.append({"name": APP_COOKIE_NAME, "delete": True})

    token_dict = st.session_state.get("google_token")
    if token_dict:
        assignments.append(
            {
                "name": GOOGLE_COOKIE_NAME,
                "value": sign_google_cookie(
                    token_dict,
                    str(st.session_state.get("google_email") or ""),
                    secret,
                ),
                "maxAge": GOOGLE_MAX_AGE_SECONDS,
            }
        )
        assignments.append({"name": OAUTH_STATE_COOKIE_NAME, "delete": True})
    else:
        assignments.append({"name": GOOGLE_COOKIE_NAME, "delete": True})
        state = st.session_state.get("google_oauth_state")
        if state:
            assignments.append(
                {
                    "name": OAUTH_STATE_COOKIE_NAME,
                    "value": sign_oauth_state_cookie(
                        str(state),
                        secret,
                        code_verifier=str(st.session_state.get("google_oauth_code_verifier") or ""),
                    ),
                    "maxAge": OAUTH_STATE_MAX_AGE_SECONDS,
                }
            )
        else:
            assignments.append({"name": OAUTH_STATE_COOKIE_NAME, "delete": True})
    return assignments


def sync_cookies(*, key: str = "rc_cookie_sync") -> None:
    """Write the current session into browser cookies (or clear them)."""
    assignments = cookie_assignments()
    if not assignments:
        return
    _cookie_bridge(cookies=assignments, key=key)


def render_connect_google_button(auth_url: str) -> None:
    """Store handshake cookies, then show a normal link to Google.

    The control must be a Streamlit ``link_button`` on the main page. A button
    inside the cookie iframe cannot send the browser to Google (the iframe is
    sandboxed).
    """
    sync_cookies(key="rc_google_connect_cookies")
    st.link_button("Connect Google", auth_url)
