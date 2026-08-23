"""Tests for Drive folder/copy helpers and the Google customization pipeline."""

from __future__ import annotations

import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from pypdf import PdfWriter

from resume_customizer.editors.base import RunSettings
from resume_customizer.google_pipeline import run_google_customization
from resume_customizer.google_workspace import copy_doc_into_folder, find_or_create_folder
from resume_customizer.parsing import CustomizationParseError


def _pdf_with_n_pages(n: int) -> bytes:
    writer = PdfWriter()
    for _ in range(n):
        writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


class _Exec:
    def __init__(self, value: Any) -> None:
        self._value = value

    def execute(self) -> Any:
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


class FakeDrive:
    """Minimal Drive v3 stand-in."""

    def __init__(self) -> None:
        self.folders: list[dict[str, str]] = []
        self.created_folders: list[dict[str, Any]] = []
        self.copies: list[tuple[str, dict[str, Any]]] = []
        self.exports: list[str] = []
        self.pdf_by_id: dict[str, bytes] = {"orig": _pdf_with_n_pages(1)}
        self.copy_pdf_pages: list[int] = [1]
        self._copy_export_i = 0

    def files(self) -> FakeDrive:
        return self

    def list(self, **_kwargs: Any) -> _Exec:
        return _Exec({"files": list(self.folders)})

    def create(self, body: dict[str, Any], fields: str = "") -> _Exec:
        self.created_folders.append(body)
        self.folders.append({"id": "folder-1", "name": body["name"]})
        return _Exec({"id": "folder-1"})

    def copy(self, fileId: str, body: dict[str, Any], fields: str = "") -> _Exec:
        self.copies.append((fileId, body))
        self.pdf_by_id["copy-1"] = _pdf_with_n_pages(self.copy_pdf_pages[0])
        return _Exec(
            {
                "id": "copy-1",
                "name": body["name"],
                "webViewLink": "https://docs.google.com/document/d/copy-1/edit",
            }
        )

    def export(self, fileId: str, mimeType: str) -> _Exec:
        self.exports.append(fileId)
        if fileId == "copy-1":
            idx = min(self._copy_export_i, len(self.copy_pdf_pages) - 1)
            self._copy_export_i += 1
            return _Exec(_pdf_with_n_pages(self.copy_pdf_pages[idx]))
        data = self.pdf_by_id.get(fileId)
        if data is None:
            return _Exec(RuntimeError("missing pdf"))
        return _Exec(data)


class FakeDocs:
    """Minimal Docs v1 stand-in."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.gets: list[str] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []

    def documents(self) -> FakeDocs:
        return self

    def get(self, documentId: str) -> _Exec:
        self.gets.append(documentId)
        return _Exec(self.document)

    def batchUpdate(self, documentId: str, body: dict[str, Any]) -> _Exec:
        self.updates.append((documentId, body))
        return _Exec({})


def _simple_doc() -> dict[str, Any]:
    return {
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {
                                "startIndex": 1,
                                "endIndex": 8,
                                "textRun": {"content": "Hello\n"},
                            }
                        ]
                    }
                }
            ]
        }
    }


def _settings() -> RunSettings:
    return RunSettings(
        system_prompt="shared editorial policy",
        model="claude-sonnet-4-6",
        temperature=0.0,
        max_tokens=256,
        api_key="k",
    )


class TestFindOrCreateFolder(unittest.TestCase):
    """ResumeCustomizer folder reuse vs create."""

    def test_reuses_existing(self) -> None:
        drive = FakeDrive()
        drive.folders = [{"id": "existing", "name": "ResumeCustomizer"}]
        self.assertEqual(find_or_create_folder(drive), "existing")
        self.assertEqual(drive.created_folders, [])

    def test_creates_when_missing(self) -> None:
        drive = FakeDrive()
        self.assertEqual(find_or_create_folder(drive), "folder-1")
        self.assertEqual(len(drive.created_folders), 1)

    def test_copy_targets_folder(self) -> None:
        drive = FakeDrive()
        copied = copy_doc_into_folder(drive, file_id="orig", folder_id="folder-1", name="Role")
        self.assertEqual(copied["id"], "copy-1")
        self.assertEqual(drive.copies[0][0], "orig")
        self.assertEqual(drive.copies[0][1]["parents"], ["folder-1"])


class TestGooglePipeline(unittest.TestCase):
    """Page-budget loop and copy-not-overwrite."""

    def test_source_export_failure_skips_claude(self) -> None:
        drive = FakeDrive()
        drive.pdf_by_id["orig"] = b""
        claude = MagicMock()
        result = run_google_customization(
            drive=drive,
            docs=FakeDocs(_simple_doc()),
            claude=claude,
            file_id="orig",
            file_name="Resume",
            job_text="Job",
            settings=_settings(),
        )
        claude.complete_json.assert_not_called()
        self.assertTrue(result.errors)
        self.assertEqual(result.google_doc_url, "")

    def test_customize_without_condense(self) -> None:
        drive = FakeDrive()
        drive.copy_pdf_pages = [1]
        docs = FakeDocs(_simple_doc())
        claude = MagicMock()
        claude.complete_json.return_value = (
            json.dumps({"job_title": "Widget Engineer", "replacements": [{"block_id": 0, "text": "Hi"}]}),
            SimpleNamespace(model="claude-sonnet-4-6", input_tokens=1, output_tokens=1, estimated_cost_usd=0.0),
        )
        result = run_google_customization(
            drive=drive,
            docs=docs,
            claude=claude,
            file_id="orig",
            file_name="Resume",
            job_text="Job",
            settings=_settings(),
        )
        self.assertEqual(claude.complete_json.call_count, 1)
        system_text = claude.complete_json.call_args.kwargs["system_text"]
        self.assertIn("shared editorial policy", system_text)
        self.assertIn("numbered text blocks", system_text)
        self.assertTrue(result.last_run_ok)
        self.assertFalse(result.condense_succeeded)
        self.assertEqual(drive.copies[0][0], "orig")
        self.assertTrue(all(doc_id == "copy-1" for doc_id, _ in docs.updates))
        self.assertNotIn("orig", [doc_id for doc_id, _ in docs.updates])
        self.assertEqual(result.source_pages, 1)
        self.assertEqual(result.output_pages, 1)

    def test_condense_when_copy_has_more_pages(self) -> None:
        drive = FakeDrive()
        drive.copy_pdf_pages = [2, 1]
        docs = FakeDocs(_simple_doc())
        claude = MagicMock()
        usage = SimpleNamespace(
            model="claude-sonnet-4-6", input_tokens=1, output_tokens=1, estimated_cost_usd=0.0
        )
        claude.complete_json.side_effect = [
            (
                json.dumps({"job_title": "A", "replacements": [{"block_id": 0, "text": "Hi"}]}),
                usage,
            ),
            (
                json.dumps({"job_title": "A", "replacements": [{"block_id": 0, "text": "H"}]}),
                usage,
            ),
        ]
        result = run_google_customization(
            drive=drive,
            docs=docs,
            claude=claude,
            file_id="orig",
            file_name="Resume",
            job_text="Job",
            settings=_settings(),
        )
        self.assertEqual(claude.complete_json.call_count, 2)
        self.assertTrue(result.condense_succeeded)
        self.assertEqual(result.output_pages, 1)
        self.assertEqual(drive.exports.count("copy-1"), 2)

    def test_condense_parse_failure_keeps_first_copy(self) -> None:
        drive = FakeDrive()
        drive.copy_pdf_pages = [2]
        docs = FakeDocs(_simple_doc())
        claude = MagicMock()
        usage = SimpleNamespace(
            model="claude-sonnet-4-6", input_tokens=1, output_tokens=1, estimated_cost_usd=0.0
        )

        claude.complete_json.side_effect = [
            (
                json.dumps({"job_title": "A", "replacements": [{"block_id": 0, "text": "Hi"}]}),
                usage,
            ),
            CustomizationParseError("bad"),
        ]
        result = run_google_customization(
            drive=drive,
            docs=docs,
            claude=claude,
            file_id="orig",
            file_name="Resume",
            job_text="Job",
            settings=_settings(),
        )
        self.assertFalse(result.condense_succeeded)
        self.assertTrue(result.last_run_ok)
        self.assertTrue(any("Condense pass" in w for w in result.warnings))
        self.assertEqual(result.google_doc_url, "https://docs.google.com/document/d/copy-1/edit")
        self.assertEqual(len(docs.updates), 1)


if __name__ == "__main__":
    unittest.main()
