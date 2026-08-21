"""Streamlit component: Google Picker that returns file id (not exported bytes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_FRONTEND_DIR = Path(__file__).resolve().parent / "google_picker_frontend"

_picker_component = components.declare_component("google_doc_picker", path=str(_FRONTEND_DIR))


def google_doc_picker(
    *,
    token: str,
    api_key: str,
    app_id: str,
    origin: str,
    key: str | None = None,
) -> dict[str, Any] | None:
    """Show a Pick-a-Doc button and return ``{id, name, mimeType}`` when chosen.

    Args:
        token: OAuth access token.
        api_key: Google Picker developer key.
        app_id: Cloud project number (OAuth client id prefix).
        origin: Streamlit app origin for ``PickerBuilder.setOrigin``.
        key: Streamlit component key.

    Returns:
        Picker document metadata, or ``None`` until the user picks a file.
    """
    value = _picker_component(
        token=token,
        apiKey=api_key,
        appId=app_id,
        origin=origin,
        key=key,
        default=None,
    )
    if isinstance(value, dict) and value.get("id"):
        return {
            "id": str(value["id"]),
            "name": str(value.get("name") or "resume"),
            "mimeType": str(value.get("mimeType") or ""),
        }
    return None
