"""Tests for :mod:`resume_customizer.filenames`."""

from __future__ import annotations

import unittest

from resume_customizer.filenames import (
    DEFAULT_FILENAME_BASE,
    download_base_from_job_title,
    download_disambiguation_suffix,
    safe_filename_base,
    with_download_disambiguation,
)


class TestSafeFilenameBase(unittest.TestCase):
    """Tests for :func:`safe_filename_base`."""

    def test_strips_unsafe_characters(self) -> None:
        """Replaces characters that are invalid in Windows file names."""
        raw = 'Senior / Dev: <foo> "bar" \\baz|?*'
        out = safe_filename_base(raw)
        self.assertNotIn("/", out)
        self.assertNotIn(":", out)
        self.assertIn("foo", out.lower())

    def test_empty_falls_back(self) -> None:
        """Blank input yields the package fallback stem."""
        self.assertEqual(safe_filename_base(""), "resume_customized")
        self.assertEqual(safe_filename_base("   "), "resume_customized")

    def test_reserved_windows_name_falls_back(self) -> None:
        """Reserved device names map to the fallback stem."""
        self.assertEqual(safe_filename_base("CON"), "resume_customized")
        self.assertEqual(safe_filename_base("com1"), "resume_customized")

    def test_truncates_long_title(self) -> None:
        """Long titles are truncated to ``max_len``."""
        long = "A" * 500
        out = safe_filename_base(long, max_len=20)
        self.assertEqual(len(out), 20)


class TestDownloadBaseFromJobTitle(unittest.TestCase):
    """Tests for :func:`download_base_from_job_title`."""

    def test_uses_job_title_when_not_fallback(self) -> None:
        self.assertEqual(download_base_from_job_title("Widget Engineer", "resume.tex"), "Widget Engineer")

    def test_uses_upload_stem_when_title_is_default(self) -> None:
        self.assertEqual(
            download_base_from_job_title(DEFAULT_FILENAME_BASE, "my_resume.tex"),
            "my_resume",
        )


class TestDownloadDisambiguation(unittest.TestCase):
    """Tests for download stem disambiguation helpers."""

    def test_suffix_format_and_decode(self) -> None:
        """Suffix is ``_`` plus seven base-36 digits; decodes to Unix second."""
        s = download_disambiguation_suffix(1_700_000_000.0)
        self.assertEqual(len(s), 8)
        self.assertTrue(s.startswith("_"))
        tag = s[1:]
        self.assertEqual(len(tag), 7)
        self.assertTrue(all(c in "0123456789abcdefghijklmnopqrstuvwxyz" for c in tag))
        self.assertEqual(int(tag, 36), 1_700_000_000)

    def test_suffix_zero_timestamp(self) -> None:
        """Epoch zero maps to seven zeros after underscore."""
        self.assertEqual(download_disambiguation_suffix(0.0), "_0000000")

    def test_with_disambiguation_respects_max_len(self) -> None:
        """Long stems are trimmed so stem + suffix does not exceed ``max_len``."""
        long_stem = "A" * 120
        out = with_download_disambiguation(long_stem, now=100.0, max_len=120)
        self.assertEqual(len(out), 120)
        self.assertTrue(out.endswith(download_disambiguation_suffix(100.0)))

    def test_with_disambiguation_short_stem_unchanged_length(self) -> None:
        """Short stems grow only by the suffix length."""
        out = with_download_disambiguation("Engineer", now=0.0)
        self.assertEqual(out, "Engineer_0000000")
