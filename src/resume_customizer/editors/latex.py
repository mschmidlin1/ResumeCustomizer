"""LaTeX resume editor: Claude rewrite, pdfLaTeX page budget, .tex/.pdf downloads."""

from __future__ import annotations

from pathlib import Path

import anthropic
import streamlit as st

from resume_customizer.claude_service import ClaudeCustomizationService
from resume_customizer.editors.base import EditorRunResult, LedgerUsage, RunSettings, SourceHandle
from resume_customizer.filenames import (
    download_base_from_job_title,
    safe_filename_base,
    with_download_disambiguation,
)
from resume_customizer.parsing import CustomizationParseError
from resume_customizer.pdf_pages import count_pdf_pages
from resume_customizer.tex_workspace import TexCompileError, TexCompiler

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


def _usage_to_ledger(usage: object) -> LedgerUsage:
    """Copy Claude usage into a ledger row."""
    return LedgerUsage(
        model=str(getattr(usage, "model", "")),
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        estimated_cost_usd=getattr(usage, "estimated_cost_usd", None),
    )


class LatexEditor:
    """Customize a self-contained ``.tex`` resume."""

    id = "latex"
    label = "LaTeX"

    def render_source_controls(self) -> SourceHandle | None:
        """LaTeX uses the shared file uploader in ``app.py``."""
        return None

    def run(
        self,
        source: SourceHandle,
        job_text: str,
        claude: ClaudeCustomizationService,
        settings: RunSettings,
    ) -> EditorRunResult:
        """Compile, customize, optionally condense, and return download artifacts."""
        raw = source.upload_bytes
        try:
            source_tex = raw.decode("utf-8")
        except UnicodeDecodeError:
            source_tex = raw.decode("utf-8", errors="replace")
        if source_tex.startswith("\ufeff"):
            source_tex = source_tex[1:]

        source_name = source.filename or "resume.tex"
        source_job = safe_filename_base(Path(source_name).stem)
        compiler = TexCompiler()
        captions: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []
        info: list[str] = []
        usages: list[LedgerUsage] = []

        try:
            with st.spinner("Measuring source PDF page count...", show_time=True):
                source_pdf_bytes = compiler.compile_to_pdf(source_tex, jobname=source_job)
        except TexCompileError as exc:
            errors.append(
                "Could not compile your uploaded `.tex` to PDF, so the source page count is unknown. "
                "Use a self-contained document and ensure pdfLaTeX (MiKTeX or TeX Live) is on PATH."
            )
            errors.append(f"pdfLaTeX: {exc}")
            excerpt = getattr(exc, "log_excerpt", "") or ""
            if excerpt.strip():
                errors.append(excerpt)
            return EditorRunResult(
                editor_id=self.id,
                errors=tuple(errors),
                compile_failed=True,
            )

        try:
            source_pages = count_pdf_pages(source_pdf_bytes)
        except ValueError as exc:
            return EditorRunResult(
                editor_id=self.id,
                errors=(f"Could not read page count from the source PDF: {exc}",),
            )

        captions.append(f"Source resume: **{source_pages}** PDF page(s) (measured via pdfLaTeX).")

        try:
            with st.spinner("Customizing resume...", show_time=True):
                result = claude.customize(
                    system_prompt=settings.system_prompt,
                    job_description=job_text.strip(),
                    resume_latex=source_tex,
                    model=settings.model,
                    max_tokens=int(settings.max_tokens),
                    temperature=float(settings.temperature),
                    source_pdf_page_count=source_pages,
                )
        except CustomizationParseError as exc:
            return EditorRunResult(
                editor_id=self.id,
                captions=tuple(captions),
                errors=(f"Could not parse model output: {exc}",),
            )
        except anthropic.APIError as exc:
            return EditorRunResult(
                editor_id=self.id,
                captions=tuple(captions),
                errors=(f"Anthropic API error: {exc}",),
            )
        except Exception as exc:
            return EditorRunResult(
                editor_id=self.id,
                captions=tuple(captions),
                errors=(f"Unexpected error: {exc}",),
            )

        usages.append(_usage_to_ledger(result.usage))
        customized_latex = result.payload.customized_latex
        job_title_for_base = result.payload.job_title
        condense_succeeded = False
        compile_failed = False
        last_run_ok = False
        pdf_bytes = b""
        download_base = with_download_disambiguation(
            download_base_from_job_title(job_title_for_base, source_name)
        )

        try:
            pdf_bytes = compiler.compile_to_pdf(customized_latex)
        except TexCompileError as exc:
            compile_failed = True
            errors.append(f"PDF compile check failed: {exc}")
            excerpt = getattr(exc, "log_excerpt", "") or ""
            if excerpt.strip():
                errors.append(excerpt)
            warnings.append(
                "The model returned LaTeX, but pdfLaTeX did not produce a PDF. "
                "You can still download the customized `.tex` below to fix locally."
            )
        else:
            out_pages = count_pdf_pages(pdf_bytes)
            if out_pages > source_pages:
                try:
                    with st.spinner("Condensing to match original page count...", show_time=True):
                        repair = claude.condense_resume_to_page_budget(
                            system_prompt=settings.system_prompt,
                            job_description=job_text.strip(),
                            customized_latex=customized_latex,
                            target_pdf_page_count=source_pages,
                            measured_pdf_page_count=out_pages,
                            model=settings.model,
                            max_tokens=int(settings.max_tokens),
                            temperature=float(settings.temperature),
                        )
                except CustomizationParseError as exc:
                    warnings.append(
                        f"Condense pass could not parse model output ({exc}). "
                        f"Keeping the first version (**{out_pages}** pages; target **{source_pages}**)."
                    )
                except anthropic.APIError as exc:
                    warnings.append(
                        f"Condense pass API error ({exc}). "
                        f"Keeping the first version (**{out_pages}** pages; target **{source_pages}**)."
                    )
                else:
                    usages.append(_usage_to_ledger(repair.usage))
                    condense_succeeded = True
                    customized_latex = repair.payload.customized_latex
                    job_title_for_base = repair.payload.job_title
                    download_base = with_download_disambiguation(
                        download_base_from_job_title(job_title_for_base, source_name)
                    )
                    try:
                        pdf_bytes = compiler.compile_to_pdf(customized_latex)
                    except TexCompileError as exc:
                        compile_failed = True
                        pdf_bytes = b""
                        errors.append(f"PDF compile failed after condense pass: {exc}")
                        excerpt = getattr(exc, "log_excerpt", "") or ""
                        if excerpt.strip():
                            errors.append(excerpt)
                        warnings.append(
                            "The condensed LaTeX did not compile. "
                            "You can still download the `.tex` below to fix locally."
                        )
                    else:
                        out_pages = count_pdf_pages(pdf_bytes)
                        if out_pages > source_pages:
                            warnings.append(
                                f"After the condense pass, the PDF still has **{out_pages}** page(s) "
                                f"(target **{source_pages}**). Review or tighten the `.tex` manually."
                            )

            if not compile_failed:
                last_run_ok = True
                info.append("Resume customized and PDF compile check passed.")

        out_pages_final: int | None = None
        if pdf_bytes:
            try:
                out_pages_final = count_pdf_pages(pdf_bytes)
            except ValueError:
                out_pages_final = None

        return EditorRunResult(
            editor_id=self.id,
            job_title=job_title_for_base,
            usages=tuple(usages),
            warnings=tuple(warnings),
            errors=tuple(errors),
            info_messages=tuple(info),
            captions=tuple(captions),
            output_tex=customized_latex,
            output_pdf=pdf_bytes,
            download_base_name=download_base,
            compile_failed=compile_failed,
            last_run_ok=last_run_ok,
            source_pages=source_pages,
            output_pages=out_pages_final,
            condense_succeeded=condense_succeeded,
        )

    def render_outputs(self, result: EditorRunResult) -> None:
        """Show `.tex` and `.pdf` download buttons when artifacts exist."""
        if not result.output_tex or not result.download_base_name:
            return
        base = result.download_base_name
        tex_name = f"{base}.tex"
        pdf_ready = result.last_run_ok and bool(result.output_pdf)
        col_tex, col_pdf = st.columns(2)
        with col_tex:
            st.download_button(
                label="Download customized resume (.tex)",
                data=result.output_tex.encode("utf-8"),
                file_name=tex_name,
                mime="text/plain",
                type="primary",
                key="download_tex",
            )
        with col_pdf:
            if pdf_ready:
                st.download_button(
                    label="Download customized resume (.pdf)",
                    data=result.output_pdf,
                    file_name=f"{base}.pdf",
                    mime="application/pdf",
                    type="primary",
                    key="download_pdf",
                )
