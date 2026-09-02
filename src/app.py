"""Streamlit entrypoint: resume customizer and Textkernel score tabs."""

from __future__ import annotations

import os

import streamlit as st

from resume_lib.browser_auth import restore_from_cookies, sync_cookies
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
from resume_customizer.editors.registry import get_editor
from resume_customizer.pricing import combine_estimated_run_cost_usd, format_usd_display, model_has_list_price
from resume_customizer.prompts import DEFAULT_SYSTEM_PROMPT
from resume_lib.secrets_config import get_anthropic_api_key, get_auth_password, get_textkernel_secrets
from resume_scorer.ledger import ScorerLedgerMongoService
from resume_scorer.ui import render_score_tab

MODEL_OPTIONS: list[str] = [
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "claude-opus-4-6",
]


@st.cache_resource
def _cached_cost_ledger_mongo(uri: str, db: str) -> CostLedgerMongoService:
    return CostLedgerMongoService.from_uri(uri, db)


@st.cache_resource
def _cached_scorer_ledger_mongo(uri: str, db: str) -> ScorerLedgerMongoService:
    return ScorerLedgerMongoService.from_uri(uri, db)


def _ledger_mongo_service() -> CostLedgerMongoService:
    uri = os.environ["MONGODB_URI"].strip()
    db = (os.environ.get("RESUME_CUSTOMIZER_DB") or "resume_customizer").strip()
    return _cached_cost_ledger_mongo(uri, db)


def _scorer_ledger_mongo_service() -> ScorerLedgerMongoService:
    uri = os.environ["MONGODB_URI"].strip()
    db = (os.environ.get("RESUME_SCORER_DB") or "resume_scorer").strip()
    return _cached_scorer_ledger_mongo(uri, db)


def _persist_ledger_entry(entry: CostLedgerEntry) -> None:
    _ledger_mongo_service().add_document(entry)


def _init_session_state() -> None:
    """Initialize Streamlit session keys used by auth, settings, and run output."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
        restore_from_cookies()
    if "settings_prompt" not in st.session_state:
        st.session_state.settings_prompt = DEFAULT_SYSTEM_PROMPT
    if "settings_model" not in st.session_state:
        st.session_state.settings_model = MODEL_OPTIONS[0]
    if "settings_temperature" not in st.session_state:
        st.session_state.settings_temperature = 0.45
    if "settings_max_tokens" not in st.session_state:
        st.session_state.settings_max_tokens = 4096
    if "last_editor_result" not in st.session_state:
        st.session_state.last_editor_result = None
    if "last_score_result" not in st.session_state:
        st.session_state.last_score_result = None
    if st.session_state.settings_model not in MODEL_OPTIONS:
        st.session_state.settings_model = MODEL_OPTIONS[0]


def _reset_outputs() -> None:
    """Clear customization and score outputs (used on sign-out)."""
    st.session_state.last_editor_result = None
    st.session_state.last_score_result = None


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


def render_public_home() -> None:
    """Public landing and password form (must be readable without signing in)."""
    st.title("Resume Customizer")
    st.write(
        "Resume Customizer is a small web app that tailors an existing resume to a job "
        "description using Anthropic’s Claude models, and can score a PDF resume against "
        "a job posting using Textkernel."
    )
    st.write(
        "You can upload a LaTeX `.tex` resume, or connect Google and pick a Google Doc. "
        "The app rewrites wording to match the posting, keeps claims grounded in the source "
        "resume, and checks that the result does not grow past the original page count."
    )
    st.write(
        "If you connect Google, Resume Customizer only uses Docs and Drive files you pick "
        "or that it creates (copies in a Drive folder named ResumeCustomizer). It does not "
        "replace your original Doc. A shared app password is required to use the tool."
    )
    st.markdown("[Privacy policy](?privacy=1)")

    st.subheader("Sign in")
    expected = get_auth_password()
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


def render_privacy_policy() -> None:
    """Public privacy policy for OAuth branding (no login required)."""
    st.title("Resume Customizer")
    st.subheader("Privacy policy")
    st.markdown("[Back to home](/)")
    st.write(
        "Resume Customizer is a password-protected tool. It is not a public consumer product "
        "and does not sell personal data."
    )
    st.write(
        "**What you provide.** The app password, a job description, and a resume you upload "
        "or a Google Doc you pick. Optional Google sign-in uses Google’s OAuth screen."
    )
    st.write(
        "**Google.** If you click Connect Google, the app can read and edit only files you "
        "select in the picker and files it creates on your behalf (a ResumeCustomizer folder "
        "and customized copies). Tokens stay in your browser session or a short-lived cookie "
        "on this site. Disconnect or Sign out clears them. The original Doc is not overwritten."
    )
    st.write(
        "**Claude (Anthropic).** Resume text and the job description are sent to Anthropic "
        "to generate the customized wording. Do not paste secrets you do not want processed "
        "by that API."
    )
    st.write(
        "**Textkernel.** On the Score tab, the PDF resume and job description are sent to "
        "Textkernel’s Tx Platform to parse and score the match. Do not upload documents you "
        "do not want processed by that API."
    )
    st.write(
        "**Logs and cost records.** Estimated Claude usage and Textkernel credit counts may "
        "be stored to track spend. Google account tokens are not stored in those ledgers."
    )
    st.write("Questions: use the support email listed on the Google sign-in screen for this app.")


def render_sidebar() -> None:
    """Render navigation, sign-out, and model settings."""
    with st.sidebar:
        st.header("Resume Customizer")
        if st.button("Sign out", type="secondary"):
            st.session_state.authenticated = False
            _reset_outputs()
            clear_google_session()
            st.rerun()

        api_key_ok = get_anthropic_api_key() is not None
        if not api_key_ok:
            st.warning("Add `[anthropic]` `api_key` to `.streamlit/secrets.toml` to run customization.")
        if get_textkernel_secrets() is None:
            st.warning("Add `[textkernel]` `account_id` and `service_key` to `.streamlit/secrets.toml` to run scoring.")

        with st.expander("Settings", expanded=False):
            st.session_state.settings_prompt = st.text_area(
                "Prompt",
                value=st.session_state.settings_prompt,
                height=180,
                help=(
                    "Shared editorial policy for LaTeX and Google Docs. Each editor prepends "
                    "format-specific rules and a fixed JSON-only response requirement."
                ),
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

        ledger = _ledger_mongo_service()
        total_spend = ledger.get_total()
        st.metric("Total est. API spend", format_usd_display(total_spend))
        st.caption("Estimated from each run’s token usage and list prices (MongoDB).")

        scorer_ledger = _scorer_ledger_mongo_service()
        tx_used = scorer_ledger.get_total_credits()
        st.metric("Textkernel credits used", f"{tx_used:g}")
        remaining = scorer_ledger.get_latest_credits_remaining()
        if remaining is not None:
            st.caption(f"Last known Textkernel remaining: {remaining:g} (from the most recent score run).")
        else:
            st.caption("Sum of credits charged by this tool’s score runs (MongoDB).")


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
        st.caption("Drag and drop a **.tex** resume onto the bordered area, or click **Browse files**.")
        uploaded_files = st.file_uploader(
            "Resume (.tex)",
            type=["tex"],
            accept_multiple_files=True,
            help="Self-contained .tex for LaTeX. Multiple files: Run uses the first.",
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
        st.session_state.last_editor_result = None
        api_key = get_anthropic_api_key()
        if api_key is None:
            st.error("Anthropic API key is not configured. Set `[anthropic]` `api_key` in `.streamlit/secrets.toml`.")
        elif not (job_text or "").strip():
            st.warning("Please paste a job description.")
        else:
            _run_customization(google_handle, uploaded, job_text.strip(), api_key)

    last: EditorRunResult | None = st.session_state.last_editor_result
    if last is not None:
        get_editor(last.editor_id).render_outputs(last)


def _run_customization(google_handle, uploaded, job_text: str, api_key: str) -> None:
    """Resolve source, run editor, persist usage. Early-return on each failure."""
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
        return

    try:
        editor = get_editor(source.editor_id)
    except EditorNotImplementedError as exc:
        st.error(str(exc))
        return
    except KeyError as exc:
        st.error(str(exc))
        return

    settings = RunSettings(
        system_prompt=st.session_state.settings_prompt,
        model=st.session_state.settings_model,
        temperature=float(st.session_state.settings_temperature),
        max_tokens=int(st.session_state.settings_max_tokens),
        api_key=api_key,
    )
    claude = ClaudeCustomizationService(api_key=api_key)
    result = editor.run(source, job_text, claude, settings)
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


def main() -> None:
    """Configure the page, initialize session state, and route to sign-in or main UI."""
    st.set_page_config(
        page_title="Resume Customizer",
        page_icon="📄",
        layout="wide",
    )
    _init_session_state()

    privacy = st.query_params.get("privacy")
    if str(privacy or "").strip().lower() in ("1", "true", "yes"):
        render_privacy_policy()
        sync_cookies()
        return

    if not st.session_state.authenticated:
        render_public_home()
        sync_cookies()
        return

    tab_customize, tab_score = st.tabs(["Customize", "Score"])
    with tab_customize:
        render_main()
    with tab_score:
        render_score_tab(_scorer_ledger_mongo_service())
    render_sidebar()
    sync_cookies()


if __name__ == "__main__":
    main()
