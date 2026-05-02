"""Parse structured JSON customization responses from model text."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


class CustomizationParseError(ValueError):
    """Raised when model output cannot be parsed into the expected JSON shape."""


_JSON_FENCE_PATTERN: re.Pattern[str] = re.compile(
    r"```(?:json)?\s*([\s\S]*?)\s*```",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CustomizationPayload:
    """Structured customization result extracted from model output.

    Attributes:
        job_title: Short title for filename generation (may still need sanitization).
        customized_latex: Full LaTeX document source.
    """

    job_title: str
    customized_latex: str


def extract_json_object_text(text: str) -> str:
    """Strip optional Markdown code fences and surrounding whitespace from model text.

    Args:
        text: Raw assistant message body, optionally wrapped in a fenced code block.

    Returns:
        A string expected to be a single JSON object.

    Raises:
        CustomizationParseError: If ``text`` is empty after trimming.
    """
    raw = (text or "").strip()
    if not raw:
        raise CustomizationParseError("Model returned empty text.")

    fence = _JSON_FENCE_PATTERN.search(raw)
    if fence:
        return fence.group(1).strip()

    return raw


def parse_customization_payload(text: str) -> CustomizationPayload:
    """Parse ``job_title`` and ``customized_latex`` from model output.

    Args:
        text: Raw assistant message; may be JSON only or fenced JSON.

    Returns:
        Validated :class:`CustomizationPayload`.

    Raises:
        CustomizationParseError: If JSON is invalid or required keys are missing/empty.
    """
    json_text = extract_json_object_text(text)
    try:
        data: Any = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise CustomizationParseError(f"Invalid JSON in model response: {exc}") from exc

    if not isinstance(data, Mapping):
        raise CustomizationParseError("Model JSON must be an object.")

    title_raw = data.get("job_title")
    latex_raw = data.get("customized_latex")

    if not isinstance(title_raw, str) or not title_raw.strip():
        raise CustomizationParseError("Missing or invalid non-empty string 'job_title'.")
    if not isinstance(latex_raw, str) or not latex_raw.strip():
        raise CustomizationParseError("Missing or invalid non-empty string 'customized_latex'.")

    return CustomizationPayload(
        job_title=title_raw.strip(),
        customized_latex=latex_raw.strip(),
    )
