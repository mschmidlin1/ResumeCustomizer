"""Shared types for resume editor plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from resume_customizer.claude_service import ClaudeCustomizationService


@dataclass(frozen=True, slots=True)
class RunSettings:
    """Model settings from the Streamlit sidebar."""

    system_prompt: str
    model: str
    temperature: float
    max_tokens: int
    api_key: str


@dataclass(frozen=True, slots=True)
class LedgerUsage:
    """One Anthropic call to persist on the cost ledger."""

    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None


@dataclass(frozen=True, slots=True)
class SourceHandle:
    """Opaque resume source selected in the UI."""

    editor_id: str
    filename: str = ""
    upload_bytes: bytes = b""
    google_file_id: str = ""
    google_file_name: str = ""
    google_mime_type: str = ""
    google_credentials: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EditorRunResult:
    """Outcome of one editor ``run``, including artifacts for ``render_outputs``."""

    editor_id: str
    job_title: str = ""
    usages: tuple[LedgerUsage, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    info_messages: tuple[str, ...] = ()
    captions: tuple[str, ...] = ()
    output_tex: str = ""
    output_pdf: bytes = b""
    download_base_name: str = ""
    compile_failed: bool = False
    last_run_ok: bool = False
    google_doc_url: str = ""
    source_pages: int | None = None
    output_pages: int | None = None
    condense_succeeded: bool = False


class SourceResolutionError(ValueError):
    """User-facing problem selecting a resume source."""


class SourceConflictError(SourceResolutionError):
    """Both a Drive Doc and an upload were provided."""


class NoSourceError(SourceResolutionError):
    """Neither a Drive Doc nor an upload was provided."""


class UnsupportedUploadError(SourceResolutionError):
    """Uploaded file extension is not a supported resume format."""


class EditorNotImplementedError(RuntimeError):
    """Registry entry exists but the editor module is not implemented yet."""


class ResumeEditor(Protocol):
    """Plugin that customizes one resume format."""

    id: str
    label: str

    def render_source_controls(self) -> SourceHandle | None:
        """Optional Streamlit widgets for this editor (Google Connect + Picker)."""

    def run(
        self,
        source: SourceHandle,
        job_text: str,
        claude: ClaudeCustomizationService,
        settings: RunSettings,
    ) -> EditorRunResult:
        """Extract text, call Claude, apply edits, return usage and artifacts."""

    def render_outputs(self, result: EditorRunResult) -> None:
        """Downloads or an Open-in-Docs link."""
