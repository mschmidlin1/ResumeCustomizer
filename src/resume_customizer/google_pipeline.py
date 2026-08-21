"""Google Docs customization pipeline (no Streamlit): page budget via Drive PDF export."""

from __future__ import annotations

from dataclasses import dataclass

import anthropic

from resume_customizer.claude_service import ClaudeCustomizationService, CustomizationUsage
from resume_customizer.editors.base import LedgerUsage, RunSettings
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
from resume_customizer.parsing import CustomizationParseError, ReplacementPayload, parse_replacement_payload
from resume_customizer.pdf_pages import count_pdf_pages

GOOGLE_SYSTEM_PROMPT = """You are an expert resume editor. Given numbered text blocks from a Google Doc
resume and a job description, rewrite block wording to highlight the most relevant experience while
preserving truthfulness. Do not add or delete blocks. Do not change layout.

The user message includes SOURCE_PDF_PAGE_COUNT: that value was measured by exporting the original
Google Doc to PDF. After your replacements are applied, the customized Doc must export to at most
that many PDF pages—do not rely on guessing from the source alone.

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
- Only reword existing blocks; do not add or delete blocks.
- In skills lines, weave relevant job-description terminology by rephrasing existing text; do not add skills the
  resume does not support.
- Prefer tightening wording over adding clauses. If you add a keyword, swap or compress nearby text to compensate.
- Never invent employers, dates, degrees, or tools.
- Omit unchanged blocks from replacements (identity replacements are allowed).
"""

_JSON_REPLACEMENTS_SUFFIX = (
    "\n\nYou MUST respond with ONLY a single JSON object and no other text or markdown. "
    'The object must have exactly two keys: "job_title" (a short string for a filename, '
    'describing the role) and "replacements" (an array of objects, each with integer "block_id" '
    'and non-empty string "text").'
)

_CONDENSE_SUFFIX = (
    "\n\nAdditional instructions for this turn only: The Google Doc currently exports to too many PDF pages. "
    "Revise RESUME_BLOCKS so that a PDF export has at most TARGET_PDF_PAGE_COUNT pages "
    "(see the user message for the exact target and current page count). "
    "Shorten by merging bullets, tightening phrasing, and removing non-essential words. Do not remove "
    "factual claims, employers, dates, degrees, or tools the candidate actually used; do not invent content. "
    "Do not add or delete blocks."
)


@dataclass(frozen=True, slots=True)
class GooglePipelineResult:
    """Artifacts from a Google Docs customization run."""

    job_title: str = ""
    usages: tuple[LedgerUsage, ...] = ()
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


def _ledger(usage: CustomizationUsage) -> LedgerUsage:
    return LedgerUsage(
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        estimated_cost_usd=usage.estimated_cost_usd,
    )


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
    )
    return parse_replacement_payload(raw), usage


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
    captions: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    info: list[str] = []
    usages: list[LedgerUsage] = []

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

    captions.append(
        f"Source resume: **{source_pages}** PDF page(s) (measured via Google PDF export)."
    )

    try:
        original_doc = get_document(docs, file_id)
    except GoogleWorkspaceError as exc:
        return GooglePipelineResult(captions=tuple(captions), errors=(str(exc),))

    original_blocks = extract_text_blocks(original_doc)
    if not original_blocks:
        return GooglePipelineResult(
            captions=tuple(captions),
            errors=("This Google Doc has no extractable text blocks.",),
        )

    blocks_text = format_blocks_for_model(original_blocks)
    try:
        payload, usage = _call_replacements(
            claude,
            system_text=GOOGLE_SYSTEM_PROMPT + _JSON_REPLACEMENTS_SUFFIX,
            user_content=_blocks_user_message(
                job_description=job_text,
                blocks_text=blocks_text,
                source_pdf_page_count=source_pages,
            ),
            settings=settings,
        )
    except CustomizationParseError as exc:
        return GooglePipelineResult(
            captions=tuple(captions),
            errors=(f"Could not parse model output: {exc}",),
        )
    except anthropic.APIError as exc:
        return GooglePipelineResult(
            captions=tuple(captions),
            errors=(f"Anthropic API error: {exc}",),
        )
    except Exception as exc:
        return GooglePipelineResult(
            captions=tuple(captions),
            errors=(f"Unexpected error: {exc}",),
        )

    usages.append(_ledger(usage))
    job_title = payload.job_title
    download_base = with_download_disambiguation(
        download_base_from_job_title(job_title, file_name)
    )
    copy_url = ""
    copy_id = ""
    output_pdf = b""
    output_pages: int | None = None
    condense_succeeded = False
    last_run_ok = False

    try:
        folder_id = find_or_create_folder(drive)
        copied = copy_doc_into_folder(
            drive,
            file_id=file_id,
            folder_id=folder_id,
            name=download_base,
        )
        copy_id = copied["id"]
        copy_url = copied["webViewLink"]
        copy_doc = get_document(docs, copy_id)
        copy_blocks = extract_text_blocks(copy_doc)
        requests = replacement_batch_requests(copy_blocks, payload.replacements)
        batch_update(docs, copy_id, requests)
    except (GoogleWorkspaceError, GoogleDocsApplyError) as exc:
        errors.append(str(exc))
        if copy_url:
            warnings.append(
                "A copy may exist in Google Drive, but customization did not finish. "
                "The original Doc was not changed."
            )
        return GooglePipelineResult(
            job_title=job_title,
            usages=tuple(usages),
            warnings=tuple(warnings),
            errors=tuple(errors),
            captions=tuple(captions),
            google_doc_url=copy_url,
            download_base_name=download_base,
        )

    try:
        output_pdf = export_pdf(drive, copy_id)
        output_pages = count_pdf_pages(output_pdf)
    except (GoogleWorkspaceError, ValueError) as exc:
        warnings.append(
            "The customized Google Doc was created, but PDF export failed so the page count "
            f"could not be verified. You can still open the Doc to review. {exc}"
        )
        return GooglePipelineResult(
            job_title=job_title,
            usages=tuple(usages),
            warnings=tuple(warnings),
            captions=tuple(captions),
            info_messages=("Resume customized. Open the Google Doc to review.",),
            google_doc_url=copy_url,
            download_base_name=download_base,
            last_run_ok=True,
            source_pages=source_pages,
        )

    if output_pages > source_pages:
        try:
            after_doc = get_document(docs, copy_id)
            after_blocks = extract_text_blocks(after_doc)
            after_text = format_blocks_for_model(after_blocks)
            repair_payload, repair_usage = _call_replacements(
                claude,
                system_text=GOOGLE_SYSTEM_PROMPT + _CONDENSE_SUFFIX + _JSON_REPLACEMENTS_SUFFIX,
                user_content=_blocks_user_message(
                    job_description=job_text,
                    blocks_text=after_text,
                    target_pdf_page_count=source_pages,
                    measured_pdf_page_count=output_pages,
                ),
                settings=settings,
            )
        except CustomizationParseError as exc:
            warnings.append(
                f"Condense pass could not parse model output ({exc}). "
                f"Keeping the first version (**{output_pages}** pages; target **{source_pages}**)."
            )
        except anthropic.APIError as exc:
            warnings.append(
                f"Condense pass API error ({exc}). "
                f"Keeping the first version (**{output_pages}** pages; target **{source_pages}**)."
            )
        except Exception as exc:
            warnings.append(
                f"Condense pass failed ({exc}). "
                f"Keeping the first version (**{output_pages}** pages; target **{source_pages}**)."
            )
        else:
            usages.append(_ledger(repair_usage))
            condense_succeeded = True
            job_title = repair_payload.job_title
            download_base = with_download_disambiguation(
                download_base_from_job_title(job_title, file_name)
            )
            try:
                fresh = get_document(docs, copy_id)
                fresh_blocks = extract_text_blocks(fresh)
                batch_update(
                    docs,
                    copy_id,
                    replacement_batch_requests(fresh_blocks, repair_payload.replacements),
                )
                output_pdf = export_pdf(drive, copy_id)
                output_pages = count_pdf_pages(output_pdf)
            except (GoogleWorkspaceError, GoogleDocsApplyError, ValueError) as exc:
                warnings.append(
                    f"Condense edits could not be applied or re-exported ({exc}). "
                    "Keeping the first customized version. The original Doc was not changed."
                )
            else:
                if output_pages > source_pages:
                    warnings.append(
                        f"After the condense pass, the PDF still has **{output_pages}** page(s) "
                        f"(target **{source_pages}**). Review or tighten the Google Doc manually."
                    )

    last_run_ok = True
    info.append("Resume customized and PDF page check finished.")
    return GooglePipelineResult(
        job_title=job_title,
        usages=tuple(usages),
        warnings=tuple(warnings),
        errors=tuple(errors),
        captions=tuple(captions),
        info_messages=tuple(info),
        google_doc_url=copy_url,
        output_pdf=output_pdf,
        download_base_name=download_base,
        last_run_ok=last_run_ok,
        source_pages=source_pages,
        output_pages=output_pages,
        condense_succeeded=condense_succeeded,
    )
