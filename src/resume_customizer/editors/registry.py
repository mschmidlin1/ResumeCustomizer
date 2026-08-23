"""Look up a resume editor plugin by id."""

from __future__ import annotations

from resume_customizer.editors.base import EditorNotImplementedError, ResumeEditor


def get_editor(editor_id: str) -> ResumeEditor:
    """Return the editor implementation for ``editor_id``.

    Args:
        editor_id: ``latex``, ``google``, or ``docx``.

    Returns:
        Editor instance.

    Raises:
        EditorNotImplementedError: Word editor is not implemented yet.
        KeyError: Unknown ``editor_id``.
    """
    if editor_id == "latex":
        from resume_customizer.editors.latex import LatexEditor

        return LatexEditor()
    if editor_id == "google":
        from resume_customizer.editors.google import GoogleEditor

        return GoogleEditor()
    if editor_id == "docx":
        raise EditorNotImplementedError("Word (.docx) editor is not implemented yet.")
    raise KeyError(f"Unknown editor {editor_id!r}")
