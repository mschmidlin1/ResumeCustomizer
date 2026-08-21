"""Signed cookie payloads for app login, OAuth handshake, and Google tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Mapping

APP_COOKIE_NAME = "rc_auth"
OAUTH_STATE_COOKIE_NAME = "rc_oauth_state"
GOOGLE_COOKIE_NAME = "rc_google"

APP_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
OAUTH_STATE_MAX_AGE_SECONDS = 15 * 60
GOOGLE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

_BROWSER_CRED_KEYS = ("token", "refresh_token", "token_uri", "client_id", "scopes", "expiry")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    pad = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data + pad)


def sign_payload(payload: Mapping[str, Any], secret: str) -> str:
    """Return ``body.mac`` for a JSON payload (includes ``iat`` if missing)."""
    body_obj = dict(payload)
    body_obj.setdefault("iat", int(time.time()))
    body = _b64encode(json.dumps(body_obj, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    mac = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64encode(mac)}"


def verify_payload(value: str | None, secret: str, *, max_age_seconds: int) -> dict[str, Any] | None:
    """Return the payload if the signature and age are valid, else ``None``."""
    if not value or "." not in value or not secret:
        return None
    body, _, mac_b64 = value.partition(".")
    if not body or not mac_b64:
        return None
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    try:
        given = _b64decode(mac_b64)
    except (ValueError, OSError):
        return None
    if not hmac.compare_digest(expected, given):
        return None
    try:
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    iat = payload.get("iat")
    if not isinstance(iat, int):
        return None
    if int(time.time()) - iat > max_age_seconds + 60:
        return None
    return payload


def sign_app_cookie(secret: str) -> str:
    """Signed value meaning the app password was already accepted."""
    return sign_payload({"ok": True}, secret)


def verify_app_cookie(value: str | None, secret: str) -> bool:
    """Return True if the app-login cookie is valid and unexpired."""
    payload = verify_payload(value, secret, max_age_seconds=APP_MAX_AGE_SECONDS)
    return bool(payload and payload.get("ok") is True)


def sign_oauth_state_cookie(state: str, secret: str) -> str:
    """Signed value for the Google OAuth ``state`` handshake."""
    return sign_payload({"state": state}, secret)


def verify_oauth_state_cookie(value: str | None, secret: str) -> str | None:
    """Return the OAuth ``state`` string, or ``None`` if invalid."""
    payload = verify_payload(value, secret, max_age_seconds=OAUTH_STATE_MAX_AGE_SECONDS)
    if not payload:
        return None
    state = payload.get("state")
    return str(state) if isinstance(state, str) and state else None


def browser_credentials_from_token_dict(token_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Copy Google creds for a cookie; never includes ``client_secret``."""
    return {key: token_dict.get(key) for key in _BROWSER_CRED_KEYS}


def token_dict_from_browser_credentials(creds: Mapping[str, Any], client_secret: str) -> dict[str, Any]:
    """Rebuild a session token dict, filling ``client_secret`` from server secrets."""
    out = {key: creds.get(key) for key in _BROWSER_CRED_KEYS}
    out["client_secret"] = client_secret
    return out


def sign_google_cookie(token_dict: Mapping[str, Any], email: str, secret: str) -> str:
    """Signed Google token cookie (no OAuth client secret)."""
    return sign_payload(
        {
            "email": email or "",
            "creds": browser_credentials_from_token_dict(token_dict),
        },
        secret,
    )


def verify_google_cookie(value: str | None, secret: str) -> dict[str, Any] | None:
    """Return ``{email, creds}`` from a Google cookie, or ``None``."""
    payload = verify_payload(value, secret, max_age_seconds=GOOGLE_MAX_AGE_SECONDS)
    if not payload:
        return None
    creds = payload.get("creds")
    if not isinstance(creds, dict):
        return None
    if creds.get("client_secret"):
        return None
    email = payload.get("email")
    return {
        "email": str(email) if email else "",
        "creds": browser_credentials_from_token_dict(creds),
    }
