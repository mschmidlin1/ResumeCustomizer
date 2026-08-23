"""Google Docs customization pipeline (no Streamlit): page budget via Drive PDF export."""

from __future__ import annotations

from dataclasses import dataclass, field

import anthropic

from resume_customizer.claude_service import ClaudeCustomizationService, CustomizationUsage
from resume_customizer.editors.base import RunSettings
from resume_customizer.filenames import download_base_from_job_title, with_download_disambiguation
from resume_customizer.google_docs_ops import (
    GoogleDocsApplyError,
    format_blocks_for_model,
    extract_text_blocks,
    replacement_batch_requests,
)
from resume_customizer.google_workspace import (
    GoogleWorkspaceError,
    batch_update,
    copy_doc_into_folder,
    export_pdf,
    find_or_create_folder,
    get_document,
)
from resume_customizer.page_budget import CondensePassResult, enforce_page_budget
from resume_customizer.parsing import CustomizationParseError, ReplacementPayload, parse_replacement_payload
from resume_customizer.pdf_pages import count_pdf_pages
from resume_customizer.prompts import REPLACEMENT_JSON_SCHEMA, compose_google_system_prompt

# Re-export for callers/tests that imported the schema from this module.
__all__ = ["GooglePipelineResult", "REPLACEMENT_JSON_SCHEMA", "run_google_customization"]


@dataclass(frozen=True, slots=True)
class GooglePipelineResult:
    """Artifacts from a Google Docs customization run."""

    job_title: str = ""
    usages: tuple[CustomizationUsage, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    captions: tuple[str, ...] = ()
    info_messages: tuple[str, ...] = ()
    google_doc_url: str = ""
    output_pdf: bytes = b""
    download_base_name: str = ""
    last_run_ok: bool = False
    source_pages: int | None = None
    output_pages: int | None = None
    condense_succeeded: bool = False


@dataclass
class _GoogleRunContext:
    """Mutable state for one Google Docs customize → condense run."""

    drive: object
    docs: object
    file_id: str
    file_name: str
    job_text: str
    settings: RunSettings
    claude: ClaudeCustomizationService
    source_pages: int
    captions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    usages: list[CustomizationUsage] = field(default_factory=list)
    job_title: str = ""
    download_base: str = ""
    copy_url: str = ""
    copy_id: str = ""
    output_pdf: bytes = b""
    output_pages: int | None = None
    condense_succeeded: bool = False
    last_run_ok: bool = False


def _blocks_user_message(
    *,
    job_description: str,
    blocks_text: str,
    source_pdf_page_count: int | None = None,
    target_pdf_page_count: int | None = None,
    measured_pdf_page_count: int | None = None,
) -> str:
    parts: list[str] = []
    if source_pdf_page_count is not None:
        parts.append(f"SOURCE_PDF_PAGE_COUNT: {int(source_pdf_page_count)}")
    if target_pdf_page_count is not None:
        parts.append(f"TARGET_PDF_PAGE_COUNT: {int(target_pdf_page_count)}")
    if measured_pdf_page_count is not None:
        parts.append(f"MEASURED_CUSTOMIZED_PDF_PAGE_COUNT: {int(measured_pdf_page_count)}")
    header = "\n".join(parts)
    if header:
        header += "\n\n"
    return (
        header
        + "JOB_DESCRIPTION:\n"
        + f"{job_description.strip()}\n\n"
        + "RESUME_BLOCKS:\n"
        + blocks_text
    )


def _call_replacements(
    claude: ClaudeCustomizationService,
    *,
    system_text: str,
    user_content: str,
    settings: RunSettings,
) -> tuple[ReplacementPayload, CustomizationUsage]:
    raw, usage = claude.complete_json(
        system_text=system_text,
        user_content=user_content,
        model=settings.model,
        max_tokens=int(settings.max_tokens),
        temperature=float(settings.temperature),
        json_schema=REPLACEMENT_JSON_SCHEMA,
    )
    return parse_replacement_payload(raw), usage


def _measure_source(drive: object, file_id: str) -> tuple[int, str] | GooglePipelineResult:
    try:
        source_pdf = export_pdf(drive, file_id)
        source_pages = count_pdf_pages(source_pdf)
    except (GoogleWorkspaceError, ValueError) as exc:
        return GooglePipelineResult(
            errors=(
                "Could not export the original Google Doc to PDF, so the source page count is unknown. "
                f"{exc}",
            ),
        )
    caption = f"Source resume: **{source_pages}** PDF page(s) (measured via Google PDF export)."
    return source_pages, caption


def _first_pass(ctx: _GoogleRunContext) -> GooglePipelineResult | None:
    """Customize via Claude, copy Doc, apply replacements. Return early result on failure."""
    try:
        original_doc = get_document(ctx.docs, ctx.file_id)
    except GoogleWorkspaceError as exc:
        return GooglePipelineResult(captions=tuple(ctx.captions), errors=(str(exc),))

    original_blocks = extract_text_blocks(original_doc)
    if not original_blocks:
        return GooglePipelineResult(
            captions=tuple(ctx.captions),
            errors=("This Google Doc has no extractable text blocks.",),
        )

    blocks_text = format_blocks_for_model(original_blocks)
    try:
        payload, usage = _call_replacements(
            ctx.claude,
            system_text=compose_google_system_prompt(ctx.settings.system_prompt, condense=False),
            user_content=_blocks_user_message(
                job_description=ctx.job_text,
                blocks_text=blocks_text,
                source_pdf_page_count=ctx.source_pages,
            ),
            settings=ctx.settings,
        )
    except CustomizationParseError as exc:
        return GooglePipelineResult(
            captions=tuple(ctx.captions),
            errors=(f"Could not parse model output: {exc}",),
        )
    except anthropic.APIError as exc:
        return GooglePipelineResult(
            captions=tuple(ctx.captions),
            errors=(f"Anthropic API error: {exc}",),
        )
    except Exception as exc:
        return GooglePipelineResult(
            captions=tuple(ctx.captions),
            errors=(f"Unexpected error: {exc}",),
        )

    ctx.usages.append(usage)
    ctx.job_title = payload.job_title
    ctx.download_base = with_download_disambiguation(
        download_base_from_job_title(ctx.job_title, ctx.file_name)
    )

    try:
        folder_id = find_or_create_folder(ctx.drive)
        copied = copy_doc_into_folder(
            ctx.drive,
            file_id=ctx.file_id,
            folder_id=folder_id,
            name=ctx.download_base,
        )
        ctx.copy_id = copied["id"]
        ctx.copy_url = copied["webViewLink"]
        copy_doc = get_document(ctx.docs, ctx.copy_id)
        copy_blocks = extract_text_blocks(copy_doc)
        requests = replacement_batch_requests(copy_blocks, payload.replacements)
        batch_update(ctx.docs, ctx.copy_id, requests)
    except (GoogleWorkspaceError, GoogleDocsApplyError) as exc:
        ctx.errors.append(str(exc))
        if ctx.copy_url:
            ctx.warnings.append(
                "A copy may exist in Google Drive, but customization did not finish. "
                "The original Doc was not changed."
            )
        return GooglePipelineResult(
            job_title=ctx.job_title,
            usages=tuple(ctx.usages),
            warnings=tuple(ctx.warnings),
            errors=tuple(ctx.errors),
            captions=tuple(ctx.captions),
            google_doc_url=ctx.copy_url,
            download_base_name=ctx.download_base,
        )
    return None


def _export_output_pages(ctx: _GoogleRunContext) -> GooglePipelineResult | None:
    """Export customized copy PDF; return early result if export fails."""
    try:
        ctx.output_pdf = export_pdf(ctx.drive, ctx.copy_id)
        ctx.output_pages = count_pdf_pages(ctx.output_pdf)
    except (GoogleWorkspaceError, ValueError) as exc:
        ctx.warnings.append(
            "The customized Google Doc was created, but PDF export failed so the page count "
            f"could not be verified. You can still open the Doc to review. {exc}"
        )
        return GooglePipelineResult(
            job_title=ctx.job_title,
            usages=tuple(ctx.usages),
            warnings=tuple(ctx.warnings),
            captions=tuple(ctx.captions),
            info_messages=("Resume customized. Open the Google Doc to review.",),
            google_doc_url=ctx.copy_url,
            download_base_name=ctx.download_base,
            last_run_ok=True,
            source_pages=ctx.source_pages,
        )
    return None


def _condense_if_needed(ctx: _GoogleRunContext) -> None:
    """Run shared page-budget loop when the customized export is over source pages."""
    if ctx.output_pages is None:
        return

    def attempt_condense() -> CondensePassResult:
        after_doc = get_document(ctx.docs, ctx.copy_id)
        after_blocks = extract_text_blocks(after_doc)
        after_text = format_blocks_for_model(after_blocks)
        repair_payload, repair_usage = _call_replacements(
            ctx.claude,
            system_text=compose_google_system_prompt(ctx.settings.system_prompt, condense=True),
            user_content=_blocks_user_message(
                job_description=ctx.job_text,
                blocks_text=after_text,
                target_pdf_page_count=ctx.source_pages,
                measured_pdf_page_count=ctx.output_pages,
            ),
            settings=ctx.settings,
        )
        ctx.job_title = repair_payload.job_title
        ctx.download_base = with_download_disambiguation(
            download_base_from_job_title(ctx.job_title, ctx.file_name)
        )
        try:
            fresh = get_document(ctx.docs, ctx.copy_id)
            fresh_blocks = extract_text_blocks(fresh)
            batch_update(
                ctx.docs,
                ctx.copy_id,
                replacement_batch_requests(fresh_blocks, repair_payload.replacements),
            )
            ctx.output_pdf = export_pdf(ctx.drive, ctx.copy_id)
            pages = count_pdf_pages(ctx.output_pdf)
        except (GoogleWorkspaceError, GoogleDocsApplyError, ValueError) as exc:
            return CondensePassResult(
                output_pages=ctx.output_pages or 0,
                usage=repair_usage,
                warnings=(
                    f"Condense edits could not be applied or re-exported ({exc}). "
                    "Keeping the first customized version. The original Doc was not changed.",
                ),
                remeasured=False,
            )
        return CondensePassResult(output_pages=pages, usage=repair_usage, remeasured=True)

    budget = enforce_page_budget(
        source_pages=ctx.source_pages,
        output_pages=ctx.output_pages,
        attempt_condense=attempt_condense,
        still_over_manual_hint="Review or tighten the Google Doc manually.",
    )
    ctx.output_pages = budget.output_pages
    ctx.warnings.extend(budget.warnings)
    if budget.usage is not None:
        ctx.usages.append(budget.usage)
    ctx.condense_succeeded = budget.condense_succeeded


def _build_result(ctx: _GoogleRunContext) -> GooglePipelineResult:
    ctx.last_run_ok = True
    ctx.info.append("Resume customized and PDF page check finished.")
    return GooglePipelineResult(
        job_title=ctx.job_title,
        usages=tuple(ctx.usages),
        warnings=tuple(ctx.warnings),
        errors=tuple(ctx.errors),
        captions=tuple(ctx.captions),
        info_messages=tuple(ctx.info),
        google_doc_url=ctx.copy_url,
        output_pdf=ctx.output_pdf,
        download_base_name=ctx.download_base,
        last_run_ok=ctx.last_run_ok,
        source_pages=ctx.source_pages,
        output_pages=ctx.output_pages,
        condense_succeeded=ctx.condense_succeeded,
    )


def run_google_customization(
    *,
    drive: object,
    docs: object,
    claude: ClaudeCustomizationService,
    file_id: str,
    file_name: str,
    job_text: str,
    settings: RunSettings,
) -> GooglePipelineResult:
    """Measure pages, customize a copy, condense if over budget.

    Never writes to ``file_id``. Failures after a successful copy still return the copy URL when possible.
    """
    measured = _measure_source(drive, file_id)
    if isinstance(measured, GooglePipelineResult):
        return measured
    source_pages, caption = measured

    ctx = _GoogleRunContext(
        drive=drive,
        docs=docs,
        file_id=file_id,
        file_name=file_name,
        job_text=job_text,
        settings=settings,
        claude=claude,
        source_pages=source_pages,
        captions=[caption],
    )

    early = _first_pass(ctx)
    if early is not None:
        return early

    early = _export_output_pages(ctx)
    if early is not None:
        return early

    _condense_if_needed(ctx)
    return _build_result(ctx)
