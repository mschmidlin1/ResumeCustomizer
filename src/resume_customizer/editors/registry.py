"""Look up a resume editor plugin by id."""

from __future__ import annotations

from resume_customizer.editors.base import EditorNotImplementedError, ResumeEditor


def get_editor(kind: str) -> ResumeEditor:
    """Return the editor implementation for ``kind``.

    Args:
        kind: ``latex``, ``google``, or ``docx``.

    Returns:
        Editor instance.

    Raises:
        EditorNotImplementedError: Word editor is not implemented yet.
        KeyError: Unknown ``kind``.
    """
    if kind == "latex":
        from resume_customizer.editors.latex import LatexEditor

        return LatexEditor()
    if kind == "google":
        from resume_customizer.editors.google import GoogleEditor

        return GoogleEditor()
    if kind == "docx":
        raise EditorNotImplementedError("Word (.docx) editor is not implemented yet.")
    raise KeyError(f"Unknown editor {kind!r}")
