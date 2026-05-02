"""Tests for :mod:`resume_customizer.parsing`."""

from __future__ import annotations

import unittest

from resume_customizer.parsing import (
    CustomizationParseError,
    extract_json_object_text,
    parse_customization_payload,
)


class TestExtractJsonObjectText(unittest.TestCase):
    """Tests for :func:`extract_json_object_text`."""

    def test_raw_json(self) -> None:
        """Plain JSON is returned unchanged aside from strip."""
        raw = '{"job_title": "x", "customized_latex": "y"}'
        self.assertEqual(extract_json_object_text(raw), raw)

    def test_fenced_json(self) -> None:
        """Markdown fences are removed."""
        body = """
```json
{"job_title": "Role", "customized_latex": "\\\\begin{document}"}
```
"""
        inner = extract_json_object_text(body)
        self.assertTrue(inner.startswith("{"))
        self.assertIn("Role", inner)

    def test_empty_raises(self) -> None:
        """Empty assistant text raises :class:`CustomizationParseError`."""
        with self.assertRaises(CustomizationParseError):
            extract_json_object_text("")


class TestParseCustomizationPayload(unittest.TestCase):
    """Tests for :func:`parse_customization_payload`."""

    def test_parses_minimal_valid(self) -> None:
        """Valid keys produce a payload dataclass."""
        text = '{"job_title": "Engineer", "customized_latex": "\\\\documentclass{article}"}'
        payload = parse_customization_payload(text)
        self.assertEqual(payload.job_title, "Engineer")
        self.assertIn("documentclass", payload.customized_latex)

    def test_invalid_json_raises(self) -> None:
        """Malformed JSON raises :class:`CustomizationParseError`."""
        with self.assertRaises(CustomizationParseError):
            parse_customization_payload("{not json")

    def test_missing_keys_raises(self) -> None:
        """Missing required keys raises :class:`CustomizationParseError`."""
        with self.assertRaises(CustomizationParseError):
            parse_customization_payload('{"job_title": "" , "customized_latex": "x"}')


if __name__ == "__main__":
    unittest.main()
