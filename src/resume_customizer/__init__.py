"""Resume customization: Claude API client, LaTeX compile, and parsing helpers."""

from __future__ import annotations

from resume_customizer.claude_service import ClaudeCustomizationResult, ClaudeCustomizationService
from resume_customizer.filenames import DEFAULT_FILENAME_BASE, safe_filename_base, with_download_disambiguation
from resume_customizer.pdf_pages import count_pdf_pages
from resume_customizer.parsing import CustomizationParseError, CustomizationPayload, parse_customization_payload
from resume_customizer.tex_workspace import TexCompileError, TexCompiler

__all__ = [
    "ClaudeCustomizationResult",
    "ClaudeCustomizationService",
    "DEFAULT_FILENAME_BASE",
    "CustomizationParseError",
    "CustomizationPayload",
    "TexCompileError",
    "TexCompiler",
    "count_pdf_pages",
    "parse_customization_payload",
    "safe_filename_base",
    "with_download_disambiguation",
]
