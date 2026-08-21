"""Google Docs editor: OAuth, Picker, copy into ResumeCustomizer, Docs API edits."""

from __future__ import annotations

from typing import Any

import streamlit as st

from resume_customizer.auth_cookies import (
    sign_oauth_handshake_state,
    verify_oauth_handshake_state,
)
from resume_customizer.browser_auth import render_connect_google_button, signing_secret
from resume_customizer.claude_service import ClaudeCustomizationService
from resume_customizer.editors.base import EditorRunResult, RunSettings, SourceHandle
from resume_customizer.editors.google_picker import google_doc_picker
from resume_customizer.google_auth import (
    build_drive_and_docs,
    build_flow,
    credentials_from_dict,
    credentials_to_dict,
    fetch_account_email,
    generate_pkce_verifier,
)
from resume_customizer.google_docs_ops import GOOGLE_DOC_MIME
from resume_customizer.google_pipeline import run_google_customization


def clear_google_session() -> None:
    """Drop OAuth tokens and the picked Doc from Streamlit session state."""
    for key in (
        "google_token",
        "google_email",
        "google_picked_file",
        "google_oauth_state",
        "google_oauth_code_verifier",
        "google_auth_url",
    ):
        st.session_state.pop(key, None)


def _clear_oauth_handshake() -> None:
    """Drop the in-progress Google OAuth handshake (not finished tokens)."""
    for key in ("google_oauth_state", "google_oauth_code_verifier", "google_auth_url"):
        st.session_state.pop(key, None)


def _google_secrets() -> dict[str, str] | None:
    """Return Google Cloud secrets, or ``None`` if incomplete."""
    try:
        block = st.secrets.get("google", {})
    except Exception:
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


def _infer_redirect_uri(configured: str) -> str:
    """Prefer secrets ``redirect_uri``, else the current request origin."""
    if configured:
        return configured.rstrip("/")
    headers = getattr(st.context, "headers", {}) or {}
    proto = headers.get("X-Forwarded-Proto") or headers.get("x-forwarded-proto") or "http"
    host = headers.get("Host") or headers.get("host") or "localhost:8501"
    return f"{proto}://{host}".rstrip("/")


def _app_origin(redirect_uri: str) -> str:
    """Origin string for Google Picker ``setOrigin``."""
    return redirect_uri.rstrip("/")


def _refresh_stored_google_token(secrets: dict[str, str]) -> dict[str, Any] | None:
    """Refresh an expired access token in session; clear Google state if that fails."""
    token_dict: dict[str, Any] | None = st.session_state.get("google_token")
    if not token_dict:
        return None
    merged = dict(token_dict)
    merged["client_secret"] = secrets["client_secret"]
    try:
        creds = credentials_from_dict(merged)
        fresh = credentials_to_dict(creds)
        st.session_state.google_token = fresh
        return fresh
    except Exception:
        clear_google_session()
        return None


def _query_param_str(params: Any, name: str) -> str | None:
    """Return the first string value for a Streamlit query param, if present."""
    raw = params.get(name)
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _handle_oauth_callback(secrets: dict[str, str]) -> None:
    """Exchange ``?code=`` from Google if present, then clear query params."""
    params = st.query_params
    code = _query_param_str(params, "code")
    if not code:
        return
    state = _query_param_str(params, "state")
    secret = signing_secret()
    verifier = verify_oauth_handshake_state(state, secret) if secret else None
    if not verifier:
        st.error("Google sign-in could not be verified. Click Connect Google again.")
        _clear_oauth_handshake()
        st.query_params.clear()
        return
    redirect_uri = _infer_redirect_uri(secrets["redirect_uri"])
    flow = build_flow(
        client_id=secrets["client_id"],
        client_secret=secrets["client_secret"],
        redirect_uri=redirect_uri,
    )
    flow.code_verifier = verifier
    try:
        flow.fetch_token(code=code, code_verifier=verifier)
        creds = flow.credentials
        st.session_state.google_token = credentials_to_dict(creds)
        try:
            st.session_state.google_email = fetch_account_email(creds)
        except Exception:
            st.session_state.google_email = ""
        _clear_oauth_handshake()
    except Exception as exc:
        st.error(f"Google sign-in failed: {exc}")
        _clear_oauth_handshake()
    st.query_params.clear()


class GoogleEditor:
    """Customize a Google Doc picked from the visitor's Drive."""

    id = "google"
    label = "Google Docs"

    def render_source_controls(self) -> SourceHandle | None:
        """Connect Google, Drive picker, and optional selected-file caption."""
        st.subheader("Google Drive")
        secrets = _google_secrets()
        if secrets is None:
            st.caption(
                "Add `[google]` `client_id`, `client_secret`, `api_key`, and `app_id` "
                "to `.streamlit/secrets.toml` to enable Google Docs."
            )
            return None

        _handle_oauth_callback(secrets)
        token_dict = _refresh_stored_google_token(secrets)
        redirect_uri = _infer_redirect_uri(secrets["redirect_uri"])

        if not token_dict:
            if not st.session_state.get("google_auth_url") or not verify_oauth_handshake_state(
                str(st.session_state.get("google_oauth_state") or ""),
                signing_secret() or "",
            ):
                secret = signing_secret()
                if not secret:
                    st.error("Authentication is not configured; cannot start Google sign-in.")
                    return None
                flow = build_flow(
                    client_id=secrets["client_id"],
                    client_secret=secrets["client_secret"],
                    redirect_uri=redirect_uri,
                )
                flow.code_verifier = generate_pkce_verifier()
                handshake_state = sign_oauth_handshake_state(flow.code_verifier, secret)
                auth_url, _returned_state = flow.authorization_url(
                    access_type="offline",
                    prompt="consent",
                    include_granted_scopes="true",
                    state=handshake_state,
                )
                st.session_state.google_oauth_state = handshake_state
                st.session_state.google_oauth_code_verifier = flow.code_verifier
                st.session_state.google_auth_url = auth_url
            render_connect_google_button(st.session_state.google_auth_url)
            st.caption("Uses your Google account. The app password and Claude key stay the same.")
            return None

        email = st.session_state.get("google_email") or "Google account"
        st.caption(f"Connected as **{email}**")
        if st.button("Disconnect", type="secondary", key="google_disconnect"):
            clear_google_session()
            st.rerun()

        access_token = str(token_dict.get("token") or "")
        picked = google_doc_picker(
            token=access_token,
            api_key=secrets["api_key"],
            app_id=secrets["app_id"],
            origin=_app_origin(redirect_uri),
            key="google_doc_picker",
        )
        if picked:
            mime = picked.get("mimeType") or GOOGLE_DOC_MIME
            if mime and mime != GOOGLE_DOC_MIME:
                st.error("Please pick a Google Doc (not Sheets, Slides, or another Drive file).")
            else:
                st.session_state.google_picked_file = picked

        current = st.session_state.get("google_picked_file")
        if not current or not current.get("id"):
            return None
        st.caption(f"Selected: **{current.get('name') or 'Untitled'}**")
        return SourceHandle(
            editor_id=self.id,
            filename=str(current.get("name") or "resume"),
            google_file_id=str(current["id"]),
            google_file_name=str(current.get("name") or "resume"),
            google_mime_type=str(current.get("mimeType") or GOOGLE_DOC_MIME),
            google_credentials=dict(token_dict),
        )

    def run(
        self,
        source: SourceHandle,
        job_text: str,
        claude: ClaudeCustomizationService,
        settings: RunSettings,
    ) -> EditorRunResult:
        """Copy the Doc, apply replacements, and enforce the PDF page budget."""
        try:
            creds = credentials_from_dict(source.google_credentials)
            st.session_state.google_token = credentials_to_dict(creds)
            drive, docs = build_drive_and_docs(creds)
        except Exception as exc:
            return EditorRunResult(
                editor_id=self.id,
                errors=(f"Google authorization expired or is invalid. Connect Google again. ({exc})",),
            )

        with st.spinner("Customizing Google Doc (includes PDF page check)...", show_time=True):
            piped = run_google_customization(
                drive=drive,
                docs=docs,
                claude=claude,
                file_id=source.google_file_id,
                file_name=source.google_file_name or source.filename,
                job_text=job_text,
                settings=settings,
            )

        return EditorRunResult(
            editor_id=self.id,
            job_title=piped.job_title,
            usages=piped.usages,
            warnings=piped.warnings,
            errors=piped.errors,
            info_messages=piped.info_messages,
            captions=piped.captions,
            output_pdf=piped.output_pdf,
            download_base_name=piped.download_base_name,
            last_run_ok=piped.last_run_ok,
            google_doc_url=piped.google_doc_url,
            source_pages=piped.source_pages,
            output_pages=piped.output_pages,
            condense_succeeded=piped.condense_succeeded,
        )

    def render_outputs(self, result: EditorRunResult) -> None:
        """Open-in-Docs link and PDF download when available."""
        if result.google_doc_url:
            st.link_button("Open customized resume", result.google_doc_url, type="primary")
        if result.last_run_ok and result.output_pdf and result.download_base_name:
            st.download_button(
                label="Download customized resume (.pdf)",
                data=result.output_pdf,
                file_name=f"{result.download_base_name}.pdf",
                mime="application/pdf",
                type="primary",
                key="download_google_pdf",
            )
        if result.source_pages is not None and result.output_pages is not None:
            st.caption(
                f"Customized resume: **{result.output_pages}** PDF page(s) "
                f"(source **{result.source_pages}**)."
            )
