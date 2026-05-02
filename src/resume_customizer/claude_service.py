"""Call the Anthropic Messages API to tailor a LaTeX resume to a job description."""

from __future__ import annotations

from dataclasses import dataclass

import anthropic
from anthropic.types import Message

from resume_customizer.parsing import CustomizationPayload, parse_customization_payload
from resume_customizer.pricing import estimate_message_cost_usd


@dataclass(frozen=True, slots=True)
class CustomizationUsage:
    """Token usage and estimated cost from a single Messages API call."""

    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None


_JSON_ONLY_SYSTEM_SUFFIX: str = (
    "\n\nYou MUST respond with ONLY a single JSON object and no other text or markdown. "
    'The object must have exactly two keys: "job_title" (a short string for a filename, '
    'describing the role) and "customized_latex" (the full standalone LaTeX source for '
    "the tailored resume)."
)

_CONDENSE_SYSTEM_SUFFIX: str = (
    "\n\nAdditional instructions for this turn only: The user message includes a LaTeX resume that "
    "compiles to too many PDF pages. Revise CUSTOMIZED_LATEX so that pdfLaTeX produces at most "
    "TARGET_PDF_PAGE_COUNT pages (see the user message for the exact target and current page count). "
    "Shorten by merging bullets, tightening phrasing, and removing non-essential words. Do not remove "
    "factual claims, employers, dates, degrees, or tools the candidate actually used; do not invent content. "
    "Prefer editing existing lines over adding new ones. Avoid changing \\documentclass, geometry, font size, "
    "or list spacing unless there is no other way to meet the page target."
)


@dataclass(frozen=True, slots=True)
class ClaudeCustomizationResult:
    """Successful model response after parsing structured JSON.

    Attributes:
        payload: Parsed ``job_title`` and ``customized_latex``.
        raw_response_text: Exact assistant text returned by the API (before JSON parsing).
        usage: Token counts and estimated USD from ``message.usage``.
    """

    payload: CustomizationPayload
    raw_response_text: str
    usage: CustomizationUsage


class ClaudeCustomizationService:
    """Thin wrapper around ``anthropic.Anthropic`` for resume customization."""

    def __init__(self, *, api_key: str) -> None:
        """Create a client using the given API key.

        Args:
            api_key: Anthropic API key (from app secrets).
        """
        self._client: anthropic.Anthropic = anthropic.Anthropic(api_key=api_key)

    def customize(
        self,
        *,
        system_prompt: str,
        job_description: str,
        resume_latex: str,
        model: str,
        max_tokens: int,
        temperature: float,
        source_pdf_page_count: int | None = None,
    ) -> ClaudeCustomizationResult:
        """Send job description and resume to the model and parse the JSON reply.

        Args:
            system_prompt: User-defined editing instructions (sidebar prompt).
            job_description: Full job posting text.
            resume_latex: Original LaTeX resume source.
            model: Anthropic model id (e.g. ``claude-sonnet-4-6``).
            max_tokens: Maximum tokens for the assistant reply.
            temperature: Sampling temperature in ``[0, 1]``.
            source_pdf_page_count: If set, included in the user message as the measured page count
                of the original resume PDF (from pdfLaTeX).

        Returns:
            Parsed :class:`ClaudeCustomizationResult`.

        Raises:
            anthropic.APIError: On transport or API-level failures from the SDK.
            resume_customizer.parsing.CustomizationParseError: If the reply is not valid JSON.
        """
        system_text = (system_prompt or "").strip() + _JSON_ONLY_SYSTEM_SUFFIX
        user_content = _build_user_message(
            job_description=job_description,
            resume_latex=resume_latex,
            source_pdf_page_count=source_pdf_page_count,
        )

        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_text,
            messages=[{"role": "user", "content": user_content}],
        )

        raw_text = _extract_text_block(message)
        payload = parse_customization_payload(raw_text)
        usage = _usage_from_message(model=model, message=message)
        return ClaudeCustomizationResult(payload=payload, raw_response_text=raw_text, usage=usage)

    def condense_resume_to_page_budget(
        self,
        *,
        system_prompt: str,
        job_description: str,
        customized_latex: str,
        target_pdf_page_count: int,
        measured_pdf_page_count: int,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> ClaudeCustomizationResult:
        """Second pass: shorten LaTeX so the compiled PDF fits the target page count.

        Args:
            system_prompt: User-defined editing instructions (sidebar prompt).
            job_description: Same job posting as the initial customization (for context).
            customized_latex: Current tailored LaTeX that compiles to too many pages.
            target_pdf_page_count: Measured page count of the original resume PDF.
            measured_pdf_page_count: Measured page count of ``customized_latex`` when compiled.
            model: Anthropic model id.
            max_tokens: Maximum tokens for the assistant reply.
            temperature: Sampling temperature in ``[0, 1]``.

        Returns:
            Parsed :class:`ClaudeCustomizationResult` with condensed LaTeX.

        Raises:
            anthropic.APIError: On transport or API-level failures from the SDK.
            resume_customizer.parsing.CustomizationParseError: If the reply is not valid JSON.
        """
        system_text = (system_prompt or "").strip() + _CONDENSE_SYSTEM_SUFFIX + _JSON_ONLY_SYSTEM_SUFFIX
        user_content = _build_condense_user_message(
            job_description=job_description,
            customized_latex=customized_latex,
            target_pdf_page_count=target_pdf_page_count,
            measured_pdf_page_count=measured_pdf_page_count,
        )

        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_text,
            messages=[{"role": "user", "content": user_content}],
        )

        raw_text = _extract_text_block(message)
        payload = parse_customization_payload(raw_text)
        usage = _usage_from_message(model=model, message=message)
        return ClaudeCustomizationResult(payload=payload, raw_response_text=raw_text, usage=usage)


def _build_user_message(
    *,
    job_description: str,
    resume_latex: str,
    source_pdf_page_count: int | None = None,
) -> str:
    """Format the user turn with clear delimiters for job and resume.

    Args:
        job_description: Job posting plain text.
        resume_latex: Original ``.tex`` source.
        source_pdf_page_count: Measured pages when ``resume_latex`` is compiled with pdfLaTeX.

    Returns:
        Single user message string for the Messages API.
    """
    header = ""
    if source_pdf_page_count is not None:
        header = f"SOURCE_PDF_PAGE_COUNT: {int(source_pdf_page_count)}\n\n"
    return (
        header
        + "JOB_DESCRIPTION:\n"
        + f"{job_description.strip()}\n\n"
        + "RESUME_LATEX:\n"
        + f"{resume_latex}"
    )


def _build_condense_user_message(
    *,
    job_description: str,
    customized_latex: str,
    target_pdf_page_count: int,
    measured_pdf_page_count: int,
) -> str:
    """User turn for the page-budget repair pass."""
    return (
        f"TARGET_PDF_PAGE_COUNT: {int(target_pdf_page_count)}\n"
        f"MEASURED_CUSTOMIZED_PDF_PAGE_COUNT: {int(measured_pdf_page_count)}\n\n"
        "JOB_DESCRIPTION:\n"
        f"{job_description.strip()}\n\n"
        "CUSTOMIZED_LATEX:\n"
        f"{customized_latex}"
    )


def _usage_from_message(*, model: str, message: Message) -> CustomizationUsage:
    """Build usage summary from the API message object."""
    usage = getattr(message, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage is not None else 0
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage is not None else 0
    estimated = estimate_message_cost_usd(model, input_tokens=input_tokens, output_tokens=output_tokens)
    return CustomizationUsage(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated,
    )


def _extract_text_block(message: Message) -> str:
    """Concatenate all text blocks from the first assistant message content.

    Args:
        message: Anthropic ``Message`` object from ``messages.create``.

    Returns:
        Combined plain text from ``text`` content blocks.

    Raises:
        ValueError: If there is no text content in the response.
    """
    parts: list[str] = []
    for block in message.content:
        if block.type == "text":
            parts.append(block.text)
    if not parts:
        raise ValueError("Anthropic response contained no text blocks.")
    return "".join(parts).strip()
