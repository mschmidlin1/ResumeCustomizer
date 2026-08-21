"""Streamlit entrypoint: resume customizer UI with LaTeX and Google Docs editors."""

from __future__ import annotations

import os

import streamlit as st

from resume_customizer.claude_service import ClaudeCustomizationService
from resume_customizer.cost_ledger import CostLedgerEntry, ledger_entry_now
from resume_customizer.cost_ledger_mongo import CostLedgerMongoService
from resume_customizer.editors.base import (
    EditorNotImplementedError,
    EditorRunResult,
    RunSettings,
    SourceResolutionError,
)
from resume_customizer.editors.dispatch import resolve_resume_source
from resume_customizer.editors.google import clear_google_session
from resume_customizer.editors.latex import DEFAULT_PROMPT
from resume_customizer.editors.registry import get_editor
from resume_customizer.pricing import combine_estimated_run_cost_usd, format_usd_display, model_has_list_price

MODEL_OPTIONS: list[str] = [
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "claude-opus-4-6",
]


@st.cache_resource
def _cached_cost_ledger_mongo(uri: str, db: str) -> CostLedgerMongoService:
    return CostLedgerMongoService.from_uri(uri, db)


def _ledger_mongo_service() -> CostLedgerMongoService:
    uri = os.environ["MONGODB_URI"].strip()
    db = (os.environ.get("RESUME_CUSTOMIZER_DB") or "resume_customizer").strip()
    return _cached_cost_ledger_mongo(uri, db)


def _persist_ledger_entry(entry: CostLedgerEntry) -> None:
    _ledger_mongo_service().add_document(entry)


def _init_session_state() -> None:
    """Initialize Streamlit session keys used by auth, settings, and run output."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "settings_prompt" not in st.session_state:
        st.session_state.settings_prompt = DEFAULT_PROMPT
    if "settings_model" not in st.session_state:
        st.session_state.settings_model = MODEL_OPTIONS[0]
    if "settings_temperature" not in st.session_state:
        st.session_state.settings_temperature = 0.45
    if "settings_max_tokens" not in st.session_state:
        st.session_state.settings_max_tokens = 4096
    if "last_editor_result" not in st.session_state:
        st.session_state.last_editor_result = None
    if st.session_state.settings_model not in MODEL_OPTIONS:
        st.session_state.settings_model = MODEL_OPTIONS[0]


def _get_expected_password() -> str | None:
    """Return the configured sign-in password, or ``None`` if unset."""
    try:
        auth = st.secrets.get("auth", {})
        pwd = auth.get("password")
        if pwd is not None and str(pwd).strip() != "":
            return str(pwd)
    except Exception:
        return None
    return None


def _get_anthropic_api_key() -> str | None:
    """Return the Anthropic API key from Streamlit secrets."""
    try:
        block = st.secrets.get("anthropic", {})
        key = block.get("api_key")
        if key is not None and str(key).strip() != "":
            return str(key).strip()
    except Exception:
        return None
    return None


def _reset_outputs() -> None:
    """Clear the last editor run from session state."""
    st.session_state.last_editor_result = None


def _show_result_messages(result: EditorRunResult) -> None:
    """Render captions, errors, warnings, and info from an editor run."""
    for caption in result.captions:
        st.caption(caption)
    for err in result.errors:
        if "\n" in err.strip():
            st.code(err, language="text")
        else:
            st.error(err)
    for warning in result.warnings:
        st.warning(warning)
    for info in result.info_messages:
        st.success(info)


def _show_run_cost(result: EditorRunResult) -> None:
    """Display estimated Anthropic spend for this run."""
    if not result.usages:
        return
    first = result.usages[0]
    second = result.usages[1] if len(result.usages) > 1 else None
    run_cost_total, run_cost_partial = combine_estimated_run_cost_usd(
        first_cost=first.estimated_cost_usd,
        second_cost=second.estimated_cost_usd if second is not None else None,
        two_calls=result.condense_succeeded,
    )
    run_display = format_usd_display(run_cost_total if run_cost_total is not None else 0.0)
    st.info(f"Est. API cost this run: {run_display} (from token usage and list prices).")
    if run_cost_partial and result.condense_succeeded:
        st.caption(
            "Part of this run used two API calls; at least one has no list price in "
            "`pricing.py`, so the amount above may undercount actual spend."
        )
    pricing_gap = not model_has_list_price(first.model) or (
        result.condense_succeeded and second is not None and not model_has_list_price(second.model)
    )
    if pricing_gap:
        st.warning(
            "No list price is configured for one or more model ids used this run; spend may be "
            "missing from the estimate and sidebar total for those calls. Add rates in "
            "`resume_customizer/pricing.py` or pick a listed model."
        )


def render_sign_in() -> None:
    """Render the password gate when the user is not authenticated."""
    st.title("Resume customizer")
    st.caption("Sign in to continue.")

    expected = _get_expected_password()
    if expected is None:
        st.error(
            "Authentication is not configured. Copy `.streamlit/secrets.toml.example` to "
            "`.streamlit/secrets.toml` and set `[auth]` `password`."
        )
        return

    with st.form("sign_in_form"):
        password = st.text_input("Password", type="password", key="signin_password_input")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        if password == expected:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")


def render_sidebar() -> None:
    """Render navigation, sign-out, and model settings."""
    with st.sidebar:
        st.header("Resume customizer")
        if st.button("Sign out", type="secondary"):
            st.session_state.authenticated = False
            _reset_outputs()
            clear_google_session()
            st.rerun()

        api_key_ok = _get_anthropic_api_key() is not None
        if not api_key_ok:
            st.warning("Add `[anthropic]` `api_key` to `.streamlit/secrets.toml` to run customization.")

        with st.expander("Settings", expanded=False):
            st.session_state.settings_prompt = st.text_area(
                "Prompt",
                value=st.session_state.settings_prompt,
                height=180,
                help="System instructions for the LaTeX editor, plus a fixed JSON-only response rule.",
            )
            st.session_state.settings_model = st.selectbox(
                "Model",
                options=MODEL_OPTIONS,
                index=MODEL_OPTIONS.index(st.session_state.settings_model)
                if st.session_state.settings_model in MODEL_OPTIONS
                else 0,
                help="Anthropic model id passed to the Messages API.",
            )
            st.session_state.settings_temperature = st.slider(
                "Temperature",
                min_value=0.0,
                max_value=1.0,
                value=float(st.session_state.settings_temperature),
                step=0.05,
            )
            st.session_state.settings_max_tokens = st.number_input(
                "Max output tokens",
                min_value=256,
                max_value=32000,
                value=int(st.session_state.settings_max_tokens),
                step=256,
            )

        _mongo = _ledger_mongo_service()
        _total_spend = _mongo.get_total()
        st.metric("Total est. API spend", format_usd_display(_total_spend))
        st.caption("Estimated from each run’s token usage and list prices (MongoDB).")


def render_main() -> None:
    """Render two-column source controls, run action, and editor outputs."""
    st.title("Customize resume")
    st.write(
        "Pick a Google Doc or upload a `.tex` resume, paste the job description, then run "
        "to tailor the resume with Claude."
    )

    google_editor = get_editor("google")
    col_drive, col_upload = st.columns(2)
    with col_drive:
        google_handle = google_editor.render_source_controls()
    with col_upload:
        st.subheader("Upload")
        st.caption(
            "Drag and drop **.tex** (or **.docx**) onto the bordered area, or click **Browse files**. "
            "Word `.docx` is not implemented yet."
        )
        uploaded_files = st.file_uploader(
            "Resume (.tex or .docx)",
            type=["tex", "docx"],
            accept_multiple_files=True,
            help="Self-contained .tex for LaTeX. Multiple files: Run uses the first. .docx coming later.",
        )

    uploaded = uploaded_files[0] if uploaded_files else None
    if uploaded_files and len(uploaded_files) > 1:
        names = ", ".join(f.name or "(unnamed)" for f in uploaded_files)
        st.info(
            f"**{len(uploaded_files)} files selected.** Run uses the first: **{uploaded_files[0].name}**. ({names})"
        )

    job_text = st.text_area("Job description", height=220, placeholder="Paste the job posting here…")

    col1, _col2 = st.columns(2)
    with col1:
        run_clicked = st.button("Run", type="primary")

    if run_clicked:
        _reset_outputs()
        api_key = _get_anthropic_api_key()
        if api_key is None:
            st.error("Anthropic API key is not configured. Set `[anthropic]` `api_key` in `.streamlit/secrets.toml`.")
        elif not (job_text or "").strip():
            st.warning("Please paste a job description.")
        else:
            google_file = None
            google_creds = None
            if google_handle is not None:
                google_file = {
                    "id": google_handle.google_file_id,
                    "name": google_handle.google_file_name,
                    "mimeType": google_handle.google_mime_type,
                }
                google_creds = google_handle.google_credentials
            try:
                source = resolve_resume_source(
                    google_file=google_file,
                    uploaded_name=(uploaded.name if uploaded is not None else None),
                    uploaded_bytes=(uploaded.getvalue() if uploaded is not None else b""),
                    google_credentials=google_creds,
                )
            except SourceResolutionError as exc:
                st.warning(str(exc))
            else:
                try:
                    editor = get_editor(source.editor_id)
                except EditorNotImplementedError as exc:
                    st.error(str(exc))
                except KeyError as exc:
                    st.error(str(exc))
                else:
                    settings = RunSettings(
                        system_prompt=st.session_state.settings_prompt,
                        model=st.session_state.settings_model,
                        temperature=float(st.session_state.settings_temperature),
                        max_tokens=int(st.session_state.settings_max_tokens),
                        api_key=api_key,
                    )
                    claude = ClaudeCustomizationService(api_key=api_key)
                    result = editor.run(source, job_text.strip(), claude, settings)
                    st.session_state.last_editor_result = result
                    _show_result_messages(result)
                    for usage in result.usages:
                        _persist_ledger_entry(
                            ledger_entry_now(
                                model=usage.model,
                                input_tokens=usage.input_tokens,
                                output_tokens=usage.output_tokens,
                                estimated_cost_usd=usage.estimated_cost_usd,
                            )
                        )
                    _show_run_cost(result)

    last: EditorRunResult | None = st.session_state.last_editor_result
    if last is not None:
        get_editor(last.editor_id).render_outputs(last)


def main() -> None:
    """Configure the page, initialize session state, and route to sign-in or main UI."""
    st.set_page_config(
        page_title="Resume customizer",
        page_icon="📄",
        layout="wide",
    )
    _init_session_state()

    if not st.session_state.authenticated:
        render_sign_in()
        return

    render_main()
    render_sidebar()


if __name__ == "__main__":
    main()
