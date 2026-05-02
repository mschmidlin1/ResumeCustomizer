"""Tests for :mod:`resume_customizer.pdf_pages`."""

from __future__ import annotations

import unittest
from io import BytesIO

from pypdf import PdfWriter

from resume_customizer.pdf_pages import count_pdf_pages


def _pdf_with_n_pages(n: int) -> bytes:
    writer = PdfWriter()
    for _ in range(n):
        writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestCountPdfPages(unittest.TestCase):
    """Tests for :func:`count_pdf_pages`."""

    def test_single_page(self) -> None:
        self.assertEqual(count_pdf_pages(_pdf_with_n_pages(1)), 1)

    def test_three_pages(self) -> None:
        self.assertEqual(count_pdf_pages(_pdf_with_n_pages(3)), 3)

    def test_empty_bytes_raises(self) -> None:
        with self.assertRaises(ValueError):
            count_pdf_pages(b"")


if __name__ == "__main__":
    unittest.main()
