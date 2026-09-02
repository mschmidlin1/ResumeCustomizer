"""Typed helpers for reading optional Streamlit secrets blocks."""

from __future__ import annotations

from typing import Any, Mapping, TypedDict

import streamlit as st


class TextkernelSecrets(TypedDict):
    """Tx Platform credentials (data center and parse flags live in resume_scorer.settings)."""

    account_id: str
    service_key: str


def _secrets_block(name: str) -> Mapping[str, Any] | None:
    """Return a secrets section mapping, or ``None`` if missing/unreadable."""
    try:
        block = st.secrets.get(name, {})
    except Exception:
        return None
    if block is None:
        return None
    return block


def get_auth_password() -> str | None:
    """Return ``[auth].password``, or ``None`` if unset."""
    block = _secrets_block("auth")
    if block is None:
        return None
    pwd = block.get("password")
    if pwd is not None and str(pwd).strip() != "":
        return str(pwd).strip()
    return None


def get_anthropic_api_key() -> str | None:
    """Return ``[anthropic].api_key``, or ``None`` if unset."""
    block = _secrets_block("anthropic")
    if block is None:
        return None
    key = block.get("api_key")
    if key is not None and str(key).strip() != "":
        return str(key).strip()
    return None


def get_google_secrets() -> dict[str, str] | None:
    """Return Google Cloud OAuth/Picker secrets, or ``None`` if incomplete.

    Requires ``client_id``, ``client_secret``, ``api_key``, and ``app_id``
    (``app_id`` defaults to the numeric prefix of ``client_id`` when omitted).
    ``redirect_uri`` may be empty (inferred at runtime).
    """
    block = _secrets_block("google")
    if block is None:
        return None
    client_id = str(block.get("client_id") or "").strip()
    client_secret = str(block.get("client_secret") or "").strip()
    api_key = str(block.get("api_key") or "").strip()
    app_id = str(block.get("app_id") or "").strip()
    if client_id and not app_id:
        app_id = client_id.split("-", 1)[0]
    if not client_id or not client_secret or not api_key or not app_id:
        return None
    redirect_uri = str(block.get("redirect_uri") or "").strip()
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "api_key": api_key,
        "app_id": app_id,
        "redirect_uri": redirect_uri,
    }


def get_google_client_secret() -> str | None:
    """Return ``[google].client_secret`` alone, or ``None`` if unset."""
    block = _secrets_block("google")
    if block is None:
        return None
    secret = str(block.get("client_secret") or "").strip()
    return secret or None


def get_textkernel_secrets() -> TextkernelSecrets | None:
    """Return ``[textkernel]`` credentials, or ``None`` if account_id/service_key missing."""
    block = _secrets_block("textkernel")
    if block is None:
        return None
    account_id = str(block.get("account_id") or "").strip()
    service_key = str(block.get("service_key") or "").strip()
    if not account_id or not service_key:
        return None
    return {
        "account_id": account_id,
        "service_key": service_key,
    }
