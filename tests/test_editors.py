"""Tests for :mod:`resume_customizer.editors.dispatch` and registry."""

from __future__ import annotations

import unittest

from resume_customizer.editors.base import (
    EditorNotImplementedError,
    NoSourceError,
    SourceConflictError,
    UnsupportedUploadError,
)
from resume_customizer.editors.dispatch import resolve_resume_source
from resume_customizer.editors.registry import get_editor


class TestResolveResumeSource(unittest.TestCase):
    """Source column dispatch."""

    def test_tex_upload(self) -> None:
        handle = resolve_resume_source(
            google_file=None,
            uploaded_name="resume.tex",
            uploaded_bytes=b"\\documentclass{article}",
        )
        self.assertEqual(handle.editor_id, "latex")
        self.assertEqual(handle.upload_bytes, b"\\documentclass{article}")

    def test_docx_upload(self) -> None:
        handle = resolve_resume_source(google_file=None, uploaded_name="cv.docx", uploaded_bytes=b"PK")
        self.assertEqual(handle.editor_id, "docx")

    def test_google_only(self) -> None:
        handle = resolve_resume_source(
            google_file={
                "id": "abc",
                "name": "Resume",
                "mimeType": "application/vnd.google-apps.document",
            },
            uploaded_name=None,
            google_credentials={"token": "t"},
        )
        self.assertEqual(handle.editor_id, "google")
        self.assertEqual(handle.google_file_id, "abc")
        self.assertEqual(handle.google_credentials["token"], "t")

    def test_both_rejected(self) -> None:
        with self.assertRaises(SourceConflictError):
            resolve_resume_source(
                google_file={"id": "abc", "name": "R", "mimeType": "application/vnd.google-apps.document"},
                uploaded_name="resume.tex",
            )

    def test_neither_rejected(self) -> None:
        with self.assertRaises(NoSourceError):
            resolve_resume_source(google_file=None, uploaded_name=None)

    def test_sheet_rejected(self) -> None:
        with self.assertRaises(UnsupportedUploadError):
            resolve_resume_source(
                google_file={
                    "id": "s",
                    "name": "Sheet",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                },
                uploaded_name=None,
            )


class TestRegistry(unittest.TestCase):
    """Editor lookup."""

    def test_latex(self) -> None:
        editor = get_editor("latex")
        self.assertEqual(editor.id, "latex")

    def test_google(self) -> None:
        editor = get_editor("google")
        self.assertEqual(editor.id, "google")

    def test_docx_not_implemented(self) -> None:
        with self.assertRaises(EditorNotImplementedError):
            get_editor("docx")


if __name__ == "__main__":
    unittest.main()
