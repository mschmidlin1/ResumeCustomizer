"""Tests for :mod:`resume_customizer.parsing`."""

from __future__ import annotations

import unittest

from resume_customizer.parsing import (
    CustomizationParseError,
    extract_json_object_text,
    parse_customization_payload,
    parse_replacement_payload,
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

    def test_json_embedded_in_prose(self) -> None:
        """A JSON object wrapped in extra text is still extracted."""
        body = 'Sure, here you go:\n{"job_title": "Role", "replacements": []}\nThanks!'
        inner = extract_json_object_text(body)
        self.assertEqual(inner, '{"job_title": "Role", "replacements": []}')

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


class TestParseReplacementPayload(unittest.TestCase):
    """Tests for :func:`parse_replacement_payload`."""

    def test_parses_replacements(self) -> None:
        """Valid job_title and replacements produce a payload."""
        text = '{"job_title": "Engineer", "replacements": [{"block_id": 2, "text": "Hello"}]}'
        payload = parse_replacement_payload(text)
        self.assertEqual(payload.job_title, "Engineer")
        self.assertEqual(len(payload.replacements), 1)
        self.assertEqual(payload.replacements[0].block_id, 2)
        self.assertEqual(payload.replacements[0].text, "Hello")

    def test_empty_replacements_ok(self) -> None:
        """An empty replacements array is valid."""
        payload = parse_replacement_payload('{"job_title": "Role", "replacements": []}')
        self.assertEqual(payload.replacements, ())

    def test_missing_job_title_raises(self) -> None:
        with self.assertRaises(CustomizationParseError):
            parse_replacement_payload('{"job_title": "", "replacements": []}')

    def test_empty_text_raises(self) -> None:
        with self.assertRaises(CustomizationParseError):
            parse_replacement_payload(
                '{"job_title": "A", "replacements": [{"block_id": 0, "text": "  "}]}'
            )

    def test_non_int_block_id_raises(self) -> None:
        with self.assertRaises(CustomizationParseError):
            parse_replacement_payload(
                '{"job_title": "A", "replacements": [{"block_id": "0", "text": "x"}]}'
            )


if __name__ == "__main__":
    unittest.main()
