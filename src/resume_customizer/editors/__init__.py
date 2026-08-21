"""Resume source editors (LaTeX, Google Docs, Word)."""

from __future__ import annotations

from resume_customizer.editors.base import (
    EditorNotImplementedError,
    EditorRunResult,
    LedgerUsage,
    RunSettings,
    SourceConflictError,
    SourceHandle,
    SourceResolutionError,
    UnsupportedUploadError,
)
from resume_customizer.editors.dispatch import resolve_resume_source
from resume_customizer.editors.registry import get_editor

__all__ = [
    "EditorNotImplementedError",
    "EditorRunResult",
    "LedgerUsage",
    "RunSettings",
    "SourceConflictError",
    "SourceHandle",
    "SourceResolutionError",
    "UnsupportedUploadError",
    "get_editor",
    "resolve_resume_source",
]
