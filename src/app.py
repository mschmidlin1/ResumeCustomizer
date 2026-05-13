"""Streamlit entrypoint: resume customizer UI backed by Claude and pdfLaTeX validation."""

from __future__ import annotations

import os
from pathlib import Path

import anthropic
import streamlit as st

from resume_customizer import (
    DEFAULT_FILENAME_BASE,
    ClaudeCustomizationService,
    CustomizationParseError,
    TexCompileError,
    TexCompiler,
    count_pdf_pages,
    safe_filename_base,
    with_download_disambiguation,
)
from resume_customizer.cost_ledger import CostLedgerEntry, ledger_entry_now
from resume_customizer.cost_ledger_mongo import CostLedgerMongoService
from resume_customizer.pricing import combine_estimated_run_cost_usd, format_usd_display, model_has_list_price

DEFAULT_PROMPT = """You are an expert resume editor. Given a LaTeX resume and a job description,
rewrite the resume to highlight the most relevant experience while preserving truthfulness and valid LaTeX.

The user message includes SOURCE_PDF_PAGE_COUNT: that value was measured by compiling RESUME_LATEX with pdfLaTeX.
Your customized_latex must compile to exactly that many PDF pages in the same environment—do not rely on guessing
from the source alone.

Truth and emphasis:
- The summary/professional profile must match the scope and emphasis of the experience section: do not promote
  occasional or partial work to a primary career narrative.
- Do not introduce claims, themes, or implied career emphasis in the summary that are not clearly supported by the
  rest of the resume (roles, bullets, tenure).
- Do not imply years of focus or end-to-end ownership for themes that appear only lightly in the body; use
  proportionate phrasing (e.g. exposure to, supported, contributions to, some experience with) or soften rather than
  stretch.
- If in doubt, soften the summary rather than stretch it.

Operational rules:
- In the skills/technical section, actively incorporate relevant job-description terminology and standard phrasing by
  rephrasing or reordering existing skills; do not add skills the resume does not support. Only use terms already
  reflected in experience or clearly implied by listed tools.
- Weave the most relevant job-description terms by rephrasing existing lines; avoid appending new lines or bullets
  unless you remove or shorten other material of comparable length so the net vertical space does not grow.
- Do not add new sections, extra \\vspace, or other devices that increase vertical stretch.
- Prefer tightening wording over adding clauses. If you add a keyword, swap or compress nearby text to compensate.
- Do not change \\documentclass, page geometry, font size, or list spacing to “cheat” the page count unless the user’s
  template already implies such edits; prefer content edits in the body.
"""

# Anthropic Messages API model ids (aliases). Older dated Claude 3.5 ids return 404.
MODEL_OPTIONS: list[str] = [
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "claude-opus-4-6",
]


@st.cache_resource
def _cached_cost_ledger_mongo(uri: str, db: str) -> CostLedgerMongoService:
    return CostLedgerMongoService.from_uri(uri, db)


def _ledger_mongo_service() -> CostLedgerMongoService | None:
    uri = (os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or "").strip()
    if not uri:
        return None
    db = (os.environ.get("RESUME_CUSTOMIZER_DB") or "resume_customizer").strip()
    return _cached_cost_ledger_mongo(uri, db)


def _persist_ledger_entry(entry: CostLedgerEntry) -> None:
    mongo = _ledger_mongo_service()
    if mongo is not None:
        mongo.add_document(entry)


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
    if "last_run_ok" not in st.session_state:
        st.session_state.last_run_ok = False
    if "compile_failed" not in st.session_state:
        st.session_state.compile_failed = False
    if "output_tex" not in st.session_state:
        st.session_state.output_tex = ""
    if "output_pdf" not in st.session_state:
        st.session_state.output_pdf = b""
    if "download_base_name" not in st.session_state:
        st.session_state.download_base_name = ""
    if "last_source_name" not in st.session_state:
        st.session_state.last_source_name = ""
    if st.session_state.settings_model not in MODEL_OPTIONS:
        st.session_state.settings_model = MODEL_OPTIONS[0]


def _get_expected_password() -> str | None:
    """Return the configured sign-in password, or ``None`` if unset.

    Returns:
        Plain-text password from secrets, or ``None`` when misconfigured.
    """
    try:
        auth = st.secrets.get("auth", {})
        pwd = auth.get("password")
        if pwd is not None and str(pwd).strip() != "":
            return str(pwd)
    except Exception:
        return None
    return None


def _get_anthropic_api_key() -> str | None:
    """Return the Anthropic API key from Streamlit secrets.

    Returns:
        API key string, or ``None`` if missing or blank.
    """
    try:
        block = st.secrets.get("anthropic", {})
        key = block.get("api_key")
        if key is not None and str(key).strip() != "":
            return str(key).strip()
    except Exception:
        return None
    return None


def _resolve_download_base(job_title: str, source_filename: str) -> str:
    """Pick a sanitized download basename from the model title or upload name.

    Args:
        job_title: ``job_title`` field from the model JSON (already non-empty from parsing).
        source_filename: Original uploaded file name (used when the title maps to the default).

    Returns:
        Filesystem-safe stem without extension.
    """
    title_base = safe_filename_base(job_title)
    upload_base = safe_filename_base(Path(source_filename or "resume.tex").stem)
    if title_base != DEFAULT_FILENAME_BASE:
        return title_base
    return upload_base


def _reset_outputs() -> None:
    """Clear run output flags and artifacts from session state."""
    st.session_state.last_run_ok = False
    st.session_state.compile_failed = False
    st.session_state.output_tex = ""
    st.session_state.output_pdf = b""
    st.session_state.download_base_name = ""


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
            st.rerun()

        api_key_ok = _get_anthropic_api_key() is not None
        if not api_key_ok:
            st.warning("Add `[anthropic]` `api_key` to `.streamlit/secrets.toml` to run customization.")

        with st.expander("Settings", expanded=False):
            st.session_state.settings_prompt = st.text_area(
                "Prompt",
                value=st.session_state.settings_prompt,
                height=180,
                help="System instructions for the model, plus a fixed JSON-only response rule.",
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
        if _mongo is not None:
            if not _mongo.ping():
                st.warning("MongoDB is configured but not reachable; spend total may be unavailable.")
            try:
                _total_spend = _mongo.get_total()
            except Exception as exc:
                st.warning(f"Could not read spend total from MongoDB: {exc}")
                _total_spend = 0.0
            _src = "MongoDB"
        else:
            st.warning("Set **MONGODB_URI** or **MONGO_URI** to record and display API spend.")
            _total_spend = 0.0
            _src = "not configured"
        st.metric("Total est. API spend", format_usd_display(_total_spend))
        st.caption(f"Estimated from each run’s token usage and list prices ({_src}).")


def render_main() -> None:
    """Render upload controls, run action, and download buttons."""
    st.title("Customize resume")
    st.write("Upload your LaTeX resume, paste the job description, then run to tailor the resume with Claude.")
    st.caption(
        "Drag and drop **.tex** file(s) onto the bordered upload area, or click **Browse files**. "
        "The whole rectangle is the drop target—not only the button."
    )

    uploaded_files = st.file_uploader(
        "Resume (.tex)",
        type=["tex"],
        accept_multiple_files=True,
        help="Self-contained .tex only for now. Multiple files: Run uses the first.",
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
        elif uploaded is None:
            st.warning("Please upload a .tex resume before running.")
        elif not (job_text or "").strip():
            st.warning("Please paste a job description.")
        else:
            raw = uploaded.getvalue()
            try:
                source_tex = raw.decode("utf-8")
            except UnicodeDecodeError:
                source_tex = raw.decode("utf-8", errors="replace")
            if source_tex.startswith("\ufeff"):
                source_tex = source_tex[1:]

            source_name = uploaded.name or "resume.tex"
            st.session_state.last_source_name = source_name
            source_job = safe_filename_base(Path(source_name).stem)

            compiler = TexCompiler()
            try:
                with st.spinner("Measuring source PDF page count...", show_time=True):
                    source_pdf_bytes = compiler.compile_to_pdf(source_tex, jobname=source_job)
            except TexCompileError as exc:
                st.session_state.compile_failed = True
                st.error(
                    "Could not compile your uploaded `.tex` to PDF, so the source page count is unknown. "
                    "Use a self-contained document and ensure pdfLaTeX (MiKTeX or TeX Live) is on PATH."
                )
                st.error(f"pdfLaTeX: {exc}")
                if exc.log_excerpt.strip():
                    st.code(exc.log_excerpt, language="text")
            else:
                try:
                    source_pages = count_pdf_pages(source_pdf_bytes)
                except ValueError as exc:
                    st.error(f"Could not read page count from the source PDF: {exc}")
                else:
                    st.caption(f"Source resume: **{source_pages}** PDF page(s) (measured via pdfLaTeX).")

                    try:
                        service = ClaudeCustomizationService(api_key=api_key)
                        with st.spinner("Customizing resume...", show_time=True):
                            result = service.customize(
                                system_prompt=st.session_state.settings_prompt,
                                job_description=job_text.strip(),
                                resume_latex=source_tex,
                                model=st.session_state.settings_model,
                                max_tokens=int(st.session_state.settings_max_tokens),
                                temperature=float(st.session_state.settings_temperature),
                                source_pdf_page_count=source_pages,
                            )
                    except CustomizationParseError as exc:
                        st.error(f"Could not parse model output: {exc}")
                    except anthropic.APIError as exc:
                        st.error(f"Anthropic API error: {exc}")
                    except Exception as exc:
                        st.error(f"Unexpected error: {exc}")
                    else:
                        customized_latex = result.payload.customized_latex
                        job_title_for_base = result.payload.job_title
                        condense_succeeded = False
                        repair_cost: float | None = None
                        repair_model: str | None = None

                        _persist_ledger_entry(
                            ledger_entry_now(
                                model=result.usage.model,
                                input_tokens=result.usage.input_tokens,
                                output_tokens=result.usage.output_tokens,
                                estimated_cost_usd=result.usage.estimated_cost_usd,
                            ),
                        )

                        try:
                            pdf_bytes = compiler.compile_to_pdf(customized_latex)
                        except TexCompileError as exc:
                            st.session_state.compile_failed = True
                            st.session_state.last_run_ok = False
                            st.session_state.output_tex = customized_latex
                            st.session_state.download_base_name = with_download_disambiguation(
                                _resolve_download_base(job_title_for_base, source_name)
                            )
                            st.error(f"PDF compile check failed: {exc}")
                            if exc.log_excerpt.strip():
                                st.code(exc.log_excerpt, language="text")
                            st.warning(
                                "The model returned LaTeX, but pdfLaTeX did not produce a PDF. "
                                "You can still download the customized `.tex` below to fix locally."
                            )
                        else:
                            out_pages = count_pdf_pages(pdf_bytes)
                            if out_pages > source_pages:
                                try:
                                    with st.spinner(
                                        "Condensing to match original page count...", show_time=True
                                    ):
                                        repair = service.condense_resume_to_page_budget(
                                            system_prompt=st.session_state.settings_prompt,
                                            job_description=job_text.strip(),
                                            customized_latex=customized_latex,
                                            target_pdf_page_count=source_pages,
                                            measured_pdf_page_count=out_pages,
                                            model=st.session_state.settings_model,
                                            max_tokens=int(st.session_state.settings_max_tokens),
                                            temperature=float(st.session_state.settings_temperature),
                                        )
                                except CustomizationParseError as exc:
                                    st.warning(
                                        f"Condense pass could not parse model output ({exc}). "
                                        f"Keeping the first version (**{out_pages}** pages; target **{source_pages}**)."
                                    )
                                except anthropic.APIError as exc:
                                    st.warning(
                                        f"Condense pass API error ({exc}). "
                                        f"Keeping the first version (**{out_pages}** pages; target **{source_pages}**)."
                                    )
                                else:
                                    _persist_ledger_entry(
                                        ledger_entry_now(
                                            model=repair.usage.model,
                                            input_tokens=repair.usage.input_tokens,
                                            output_tokens=repair.usage.output_tokens,
                                            estimated_cost_usd=repair.usage.estimated_cost_usd,
                                        ),
                                    )
                                    condense_succeeded = True
                                    repair_cost = repair.usage.estimated_cost_usd
                                    repair_model = repair.usage.model

                                    customized_latex = repair.payload.customized_latex
                                    job_title_for_base = repair.payload.job_title
                                    try:
                                        pdf_bytes = compiler.compile_to_pdf(customized_latex)
                                    except TexCompileError as exc:
                                        st.session_state.compile_failed = True
                                        st.session_state.last_run_ok = False
                                        st.session_state.output_tex = customized_latex
                                        st.session_state.download_base_name = with_download_disambiguation(
                                            _resolve_download_base(job_title_for_base, source_name)
                                        )
                                        st.error(f"PDF compile failed after condense pass: {exc}")
                                        if exc.log_excerpt.strip():
                                            st.code(exc.log_excerpt, language="text")
                                        st.warning(
                                            "The condensed LaTeX did not compile. "
                                            "You can still download the `.tex` below to fix locally."
                                        )
                                    else:
                                        out_pages = count_pdf_pages(pdf_bytes)
                                        if out_pages > source_pages:
                                            st.warning(
                                                f"After the condense pass, the PDF still has **{out_pages}** page(s) "
                                                f"(target **{source_pages}**). Review or tighten the `.tex` manually."
                                            )

                            if not st.session_state.compile_failed:
                                st.session_state.output_tex = customized_latex
                                st.session_state.output_pdf = pdf_bytes
                                st.session_state.download_base_name = with_download_disambiguation(
                                    _resolve_download_base(job_title_for_base, source_name)
                                )
                                st.session_state.last_run_ok = True
                                st.session_state.compile_failed = False
                                st.success("Resume customized and PDF compile check passed.")

                        run_cost_total, run_cost_partial = combine_estimated_run_cost_usd(
                            first_cost=result.usage.estimated_cost_usd,
                            second_cost=repair_cost,
                            two_calls=condense_succeeded,
                        )
                        run_display = format_usd_display(
                            run_cost_total if run_cost_total is not None else 0.0
                        )
                        st.info(f"Est. API cost this run: {run_display} (from token usage and list prices).")
                        if run_cost_partial and condense_succeeded:
                            st.caption(
                                "Part of this run used two API calls; at least one has no list price in "
                                "`pricing.py`, so the amount above may undercount actual spend."
                            )
                        pricing_gap = not model_has_list_price(result.usage.model) or (
                            condense_succeeded
                            and repair_model is not None
                            and not model_has_list_price(repair_model)
                        )
                        if pricing_gap:
                            st.warning(
                                "No list price is configured for one or more model ids used this run; spend may be "
                                "missing from the estimate and sidebar total for those calls. Add rates in "
                                "`resume_customizer/pricing.py` or pick a listed model."
                            )

    if st.session_state.output_tex and st.session_state.download_base_name:
        base = st.session_state.download_base_name
        tex_name = f"{base}.tex"
        pdf_ready = (
            st.session_state.last_run_ok
            and bool(st.session_state.output_pdf)
            and st.session_state.download_base_name
        )
        col_tex, col_pdf = st.columns(2)
        with col_tex:
            st.download_button(
                label="Download customized resume (.tex)",
                data=st.session_state.output_tex.encode("utf-8"),
                file_name=tex_name,
                mime="text/plain",
                type="primary",
                key="download_tex",
            )
        with col_pdf:
            if pdf_ready:
                pdf_name = f"{base}.pdf"
                st.download_button(
                    label="Download customized resume (.pdf)",
                    data=st.session_state.output_pdf,
                    file_name=pdf_name,
                    mime="application/pdf",
                    type="primary",
                    key="download_pdf",
                )


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

    # Main first so a successful Run persists spend to MongoDB before the sidebar reads totals.
    render_main()
    render_sidebar()


if __name__ == "__main__":
    main()
