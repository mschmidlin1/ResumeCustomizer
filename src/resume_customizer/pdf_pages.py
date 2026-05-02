"""Count pages in PDF files from raw bytes."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


def count_pdf_pages(pdf_bytes: bytes) -> int:
    """Return the number of pages in a PDF.

    Args:
        pdf_bytes: Raw PDF file contents.

    Returns:
        Page count (at least 1 for any valid non-empty document).

    Raises:
        ValueError: If ``pdf_bytes`` is empty or not a readable PDF.
    """
    if not pdf_bytes:
        raise ValueError("PDF bytes are empty.")
    reader = PdfReader(BytesIO(pdf_bytes))
    n = len(reader.pages)
    if n < 1:
        raise ValueError("PDF contains no pages.")
    return n
