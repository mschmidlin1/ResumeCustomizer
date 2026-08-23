"""Choose a resume editor from Drive selection vs uploaded filename."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from resume_customizer.editors.base import (
    NoSourceError,
    SourceConflictError,
    SourceHandle,
    UnsupportedUploadError,
)
from resume_customizer.google_docs_ops import GOOGLE_DOC_MIME


def resolve_resume_source(
    *,
    google_file: Mapping[str, str] | None,
    uploaded_name: str | None,
    uploaded_bytes: bytes = b"",
    google_credentials: Mapping[str, Any] | None = None,
) -> SourceHandle:
    """Return a single source handle or raise a user-facing resolution error.

    Args:
        google_file: Picker result with ``id``, ``name``, ``mimeType``, or ``None``.
        uploaded_name: First uploaded file name, or ``None`` if nothing was uploaded.
        uploaded_bytes: First uploaded file bytes.
        google_credentials: Session OAuth token dict for Drive/Docs clients.

    Returns:
        :class:`SourceHandle` for ``latex`` or ``google``.

    Raises:
        SourceConflictError: Both a Drive Doc and an upload are present.
        NoSourceError: Neither source is present.
        UnsupportedUploadError: Extension is not ``.tex``, or Drive MIME is not a Doc.
    """
    has_google = bool(google_file and google_file.get("id"))
    has_upload = bool(uploaded_name)

    if has_google and has_upload:
        raise SourceConflictError("Use a Google Doc or an uploaded file, not both.")
    if not has_google and not has_upload:
        raise NoSourceError("Pick a Google Doc or upload a resume file.")

    if has_google:
        if google_file is None:
            raise NoSourceError("Pick a Google Doc or upload a resume file.")
        mime = str(google_file.get("mimeType") or "")
        if mime and mime != GOOGLE_DOC_MIME:
            raise UnsupportedUploadError("Please pick a Google Doc (not Sheets, Slides, or a Drive file).")
        return SourceHandle(
            editor_id="google",
            filename=str(google_file.get("name") or "resume"),
            google_file_id=str(google_file["id"]),
            google_file_name=str(google_file.get("name") or "resume"),
            google_mime_type=mime or GOOGLE_DOC_MIME,
            google_credentials=dict(google_credentials or {}),
        )

    name = uploaded_name or "resume"
    ext = Path(name).suffix.lower()
    if ext == ".tex":
        return SourceHandle(editor_id="latex", filename=name, upload_bytes=uploaded_bytes)
    raise UnsupportedUploadError("Upload a .tex file, or pick a Google Doc.")
