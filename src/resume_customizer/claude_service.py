"""Call the Anthropic Messages API to tailor a resume to a job description.

LaTeX customize/condense routes through :meth:`ClaudeCustomizationService.complete_json`
(with a JSON schema when the installed SDK supports ``output_config``).
``_create_message`` reshuffles kwargs for Anthropic SDK 0.x vs 1.x differences.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Mapping

import anthropic
from anthropic.types import Message

from resume_customizer.parsing import CustomizationPayload, parse_customization_payload
from resume_customizer.pricing import estimate_message_cost_usd
from resume_customizer.prompts import LATEX_JSON_SCHEMA, compose_latex_system_prompt


@dataclass(frozen=True, slots=True)
class CustomizationUsage:
    """Token usage and estimated cost from a single Messages API call."""

    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None


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
        system_text = compose_latex_system_prompt(system_prompt, condense=False)
        user_content = _build_user_message(
            job_description=job_description,
            resume_latex=resume_latex,
            source_pdf_page_count=source_pdf_page_count,
        )
        raw_text, usage = self.complete_json(
            system_text=system_text,
            user_content=user_content,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            json_schema=LATEX_JSON_SCHEMA,
        )
        payload = parse_customization_payload(raw_text)
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
        system_text = compose_latex_system_prompt(system_prompt, condense=True)
        user_content = _build_condense_user_message(
            job_description=job_description,
            customized_latex=customized_latex,
            target_pdf_page_count=target_pdf_page_count,
            measured_pdf_page_count=measured_pdf_page_count,
        )
        raw_text, usage = self.complete_json(
            system_text=system_text,
            user_content=user_content,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            json_schema=LATEX_JSON_SCHEMA,
        )
        payload = parse_customization_payload(raw_text)
        return ClaudeCustomizationResult(payload=payload, raw_response_text=raw_text, usage=usage)

    def complete_json(
        self,
        *,
        system_text: str,
        user_content: str,
        model: str,
        max_tokens: int,
        temperature: float,
        json_schema: Mapping[str, Any] | None = None,
    ) -> tuple[str, CustomizationUsage]:
        """Call the Messages API and return assistant text plus usage.

        Args:
            system_text: Full system prompt (including JSON-only rules).
            user_content: User turn body.
            model: Anthropic model id.
            max_tokens: Maximum tokens for the assistant reply.
            temperature: Sampling temperature in ``[0, 1]``.
            json_schema: Optional JSON Schema to constrain the reply (SDK 1.x
                ``output_config``). Ignored when the installed SDK has no such parameter.

        Returns:
            Raw assistant text and usage summary.

        Raises:
            anthropic.APIError: On transport or API-level failures from the SDK.
            ValueError: If the reply has no text blocks.
        """
        try:
            return self._complete_json_once(
                system_text=system_text,
                user_content=user_content,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                json_schema=json_schema,
            )
        except anthropic.APIError as exc:
            if json_schema is not None and int(getattr(exc, "status_code", 0) or 0) == 400:
                return self._complete_json_once(
                    system_text=system_text,
                    user_content=user_content,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_schema=None,
                )
            raise

    def _complete_json_once(
        self,
        *,
        system_text: str,
        user_content: str,
        model: str,
        max_tokens: int,
        temperature: float,
        json_schema: Mapping[str, Any] | None,
    ) -> tuple[str, CustomizationUsage]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_text,
            "messages": [{"role": "user", "content": user_content}],
        }
        if json_schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": dict(json_schema)},
            }
        message = _create_message(self._client, **kwargs)
        raw_text = _extract_text_block(message)
        usage = _usage_from_message(model=model, message=message)
        return raw_text, usage


def _create_message(client: anthropic.Anthropic, **kwargs: Any) -> Message:
    """Call ``messages.create``, moving unsupported kwargs into ``extra_body``.

    SDK 0.x accepts ``temperature=`` on ``messages.create``. SDK 1.x removed that
    keyword; the Messages HTTP API still accepts it via ``extra_body``.
    """
    create = client.messages.create
    extra = dict(kwargs.pop("extra_body", None) or {})
    try:
        parameters = inspect.signature(create).parameters
        named = {
            name
            for name, param in parameters.items()
            if param.kind
            not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        }
        accepts_var = any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()
        )
    except (TypeError, ValueError):
        named = set()
        accepts_var = True
    if not accepts_var:
        for key in list(kwargs):
            if key not in named:
                extra[key] = kwargs.pop(key)
    if extra:
        kwargs["extra_body"] = extra
    return create(**kwargs)


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
    thinking_parts: list[str] = []
    for block in message.content:
        btype = getattr(block, "type", None)
        if btype == "text" and getattr(block, "text", None):
            parts.append(block.text)
        elif btype == "thinking" and getattr(block, "thinking", None):
            thinking_parts.append(str(block.thinking))
    if parts:
        return "".join(parts).strip()
    if thinking_parts:
        return "".join(thinking_parts).strip()
    raise ValueError("Anthropic response contained no text blocks.")
