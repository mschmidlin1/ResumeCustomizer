"""LaTeX resume editor: Claude rewrite, pdfLaTeX page budget, .tex/.pdf downloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import anthropic
import streamlit as st

from resume_customizer.claude_service import ClaudeCustomizationService, CustomizationUsage
from resume_customizer.editors.base import EditorRunResult, RunSettings, SourceHandle
from resume_customizer.filenames import (
    download_base_from_job_title,
    safe_filename_base,
    with_download_disambiguation,
)
from resume_customizer.page_budget import CondensePassResult, enforce_page_budget
from resume_customizer.parsing import CustomizationParseError
from resume_customizer.pdf_pages import count_pdf_pages
from resume_customizer.prompts import DEFAULT_SYSTEM_PROMPT
from resume_customizer.tex_workspace import TexCompileError, TexCompiler

# Back-compat alias for imports that still expect DEFAULT_PROMPT.
DEFAULT_PROMPT = DEFAULT_SYSTEM_PROMPT


@dataclass
class _LatexRunContext:
    """Mutable state for one LaTeX customize → condense run."""

    source_tex: str
    source_name: str
    source_pages: int
    compiler: TexCompiler
    captions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    usages: list[CustomizationUsage] = field(default_factory=list)
    customized_latex: str = ""
    job_title: str = ""
    download_base: str = ""
    output_pdf: bytes = b""
    output_pages: int | None = None
    compile_failed: bool = False
    last_run_ok: bool = False
    condense_succeeded: bool = False


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
        source_tex = _decode_tex(source.upload_bytes)
        source_name = source.filename or "resume.tex"
        source_job = safe_filename_base(Path(source_name).stem)
        compiler = TexCompiler()

        measured = _measure_source(compiler, source_tex, source_job)
        if isinstance(measured, EditorRunResult):
            return measured

        source_pages, captions = measured
        ctx = _LatexRunContext(
            source_tex=source_tex,
            source_name=source_name,
            source_pages=source_pages,
            compiler=compiler,
            captions=list(captions),
        )

        first = _first_pass(ctx, claude, job_text, settings)
        if first is not None:
            return first

        _compile_and_maybe_condense(ctx, claude, job_text, settings)
        return _build_result(self.id, ctx)

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


def _decode_tex(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def _measure_source(
    compiler: TexCompiler,
    source_tex: str,
    source_job: str,
) -> tuple[int, tuple[str, ...]] | EditorRunResult:
    """Compile the upload and return page count, or an early error result."""
    try:
        with st.spinner("Measuring source PDF page count...", show_time=True):
            source_pdf_bytes = compiler.compile_to_pdf(source_tex, jobname=source_job)
    except TexCompileError as exc:
        errors = [
            "Could not compile your uploaded `.tex` to PDF, so the source page count is unknown. "
            "Use a self-contained document and ensure pdfLaTeX (MiKTeX or TeX Live) is on PATH.",
            f"pdfLaTeX: {exc}",
        ]
        excerpt = getattr(exc, "log_excerpt", "") or ""
        if excerpt.strip():
            errors.append(excerpt)
        return EditorRunResult(editor_id="latex", errors=tuple(errors), compile_failed=True)

    try:
        source_pages = count_pdf_pages(source_pdf_bytes)
    except ValueError as exc:
        return EditorRunResult(
            editor_id="latex",
            errors=(f"Could not read page count from the source PDF: {exc}",),
        )

    caption = f"Source resume: **{source_pages}** PDF page(s) (measured via pdfLaTeX)."
    return source_pages, (caption,)


def _first_pass(
    ctx: _LatexRunContext,
    claude: ClaudeCustomizationService,
    job_text: str,
    settings: RunSettings,
) -> EditorRunResult | None:
    """Call Claude customize; return an early EditorRunResult on failure."""
    try:
        with st.spinner("Customizing resume...", show_time=True):
            result = claude.customize(
                system_prompt=settings.system_prompt,
                job_description=job_text.strip(),
                resume_latex=ctx.source_tex,
                model=settings.model,
                max_tokens=int(settings.max_tokens),
                temperature=float(settings.temperature),
                source_pdf_page_count=ctx.source_pages,
            )
    except CustomizationParseError as exc:
        return EditorRunResult(
            editor_id="latex",
            captions=tuple(ctx.captions),
            errors=(f"Could not parse model output: {exc}",),
        )
    except anthropic.APIError as exc:
        return EditorRunResult(
            editor_id="latex",
            captions=tuple(ctx.captions),
            errors=(f"Anthropic API error: {exc}",),
        )
    except Exception as exc:
        return EditorRunResult(
            editor_id="latex",
            captions=tuple(ctx.captions),
            errors=(f"Unexpected error: {exc}",),
        )

    ctx.usages.append(result.usage)
    ctx.customized_latex = result.payload.customized_latex
    ctx.job_title = result.payload.job_title
    ctx.download_base = with_download_disambiguation(
        download_base_from_job_title(ctx.job_title, ctx.source_name)
    )
    return None


def _compile_and_maybe_condense(
    ctx: _LatexRunContext,
    claude: ClaudeCustomizationService,
    job_text: str,
    settings: RunSettings,
) -> None:
    """Compile customized LaTeX and run the shared page-budget condense loop if needed."""
    try:
        ctx.output_pdf = ctx.compiler.compile_to_pdf(ctx.customized_latex)
    except TexCompileError as exc:
        ctx.compile_failed = True
        ctx.errors.append(f"PDF compile check failed: {exc}")
        excerpt = getattr(exc, "log_excerpt", "") or ""
        if excerpt.strip():
            ctx.errors.append(excerpt)
        ctx.warnings.append(
            "The model returned LaTeX, but pdfLaTeX did not produce a PDF. "
            "You can still download the customized `.tex` below to fix locally."
        )
        return

    ctx.output_pages = count_pdf_pages(ctx.output_pdf)
    if ctx.output_pages is None:
        return

    def attempt_condense() -> CondensePassResult:
        with st.spinner("Condensing to match original page count...", show_time=True):
            repair = claude.condense_resume_to_page_budget(
                system_prompt=settings.system_prompt,
                job_description=job_text.strip(),
                customized_latex=ctx.customized_latex,
                target_pdf_page_count=ctx.source_pages,
                measured_pdf_page_count=ctx.output_pages or 0,
                model=settings.model,
                max_tokens=int(settings.max_tokens),
                temperature=float(settings.temperature),
            )
        ctx.customized_latex = repair.payload.customized_latex
        ctx.job_title = repair.payload.job_title
        ctx.download_base = with_download_disambiguation(
            download_base_from_job_title(ctx.job_title, ctx.source_name)
        )
        try:
            ctx.output_pdf = ctx.compiler.compile_to_pdf(ctx.customized_latex)
        except TexCompileError as exc:
            ctx.compile_failed = True
            ctx.output_pdf = b""
            ctx.errors.append(f"PDF compile failed after condense pass: {exc}")
            excerpt = getattr(exc, "log_excerpt", "") or ""
            if excerpt.strip():
                ctx.errors.append(excerpt)
            return CondensePassResult(
                output_pages=ctx.output_pages or 0,
                usage=repair.usage,
                warnings=(
                    "The condensed LaTeX did not compile. "
                    "You can still download the `.tex` below to fix locally.",
                ),
                remeasured=False,
            )
        pages = count_pdf_pages(ctx.output_pdf)
        return CondensePassResult(output_pages=pages, usage=repair.usage, remeasured=True)

    budget = enforce_page_budget(
        source_pages=ctx.source_pages,
        output_pages=ctx.output_pages,
        attempt_condense=attempt_condense,
        still_over_manual_hint="Review or tighten the `.tex` manually.",
    )
    ctx.output_pages = budget.output_pages
    ctx.warnings.extend(budget.warnings)
    if budget.usage is not None:
        ctx.usages.append(budget.usage)
    ctx.condense_succeeded = budget.condense_succeeded

    if not ctx.compile_failed:
        ctx.last_run_ok = True
        ctx.info.append("Resume customized and PDF compile check passed.")


def _build_result(editor_id: str, ctx: _LatexRunContext) -> EditorRunResult:
    output_pages = ctx.output_pages
    if output_pages is None and ctx.output_pdf:
        try:
            output_pages = count_pdf_pages(ctx.output_pdf)
        except ValueError:
            output_pages = None
    return EditorRunResult(
        editor_id=editor_id,
        job_title=ctx.job_title,
        usages=tuple(ctx.usages),
        warnings=tuple(ctx.warnings),
        errors=tuple(ctx.errors),
        info_messages=tuple(ctx.info),
        captions=tuple(ctx.captions),
        output_tex=ctx.customized_latex,
        output_pdf=ctx.output_pdf,
        download_base_name=ctx.download_base,
        compile_failed=ctx.compile_failed,
        last_run_ok=ctx.last_run_ok,
        source_pages=ctx.source_pages,
        output_pages=output_pages,
        condense_succeeded=ctx.condense_succeeded,
    )
