"""Extract and replace text blocks in a Google Docs document JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from resume_customizer.parsing import TextReplacement

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
RESUME_CUSTOMIZER_FOLDER = "ResumeCustomizer"


class GoogleDocsApplyError(ValueError):
    """Replacement list does not match extracted blocks."""


@dataclass(frozen=True, slots=True)
class TextBlock:
    """One text-bearing paragraph or table cell."""

    block_id: int
    text: str
    start_index: int
    end_index: int


def _paragraph_text_and_range(paragraph: Mapping[str, Any]) -> tuple[str, int, int] | None:
    """Return visible text and exclusive replace range, or ``None`` if there is no text run."""
    elements = paragraph.get("elements")
    if not isinstance(elements, list):
        return None
    parts: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for el in elements:
        if not isinstance(el, Mapping):
            continue
        run = el.get("textRun")
        if not isinstance(run, Mapping):
            continue
        content = run.get("content")
        if not isinstance(content, str):
            continue
        start = el.get("startIndex")
        end = el.get("endIndex")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        parts.append(content)
        starts.append(start)
        ends.append(end)
    if not parts or not starts:
        return None
    raw = "".join(parts)
    start = starts[0]
    end = ends[-1]
    if raw.endswith("\n"):
        text = raw[:-1]
        end = end - 1
    else:
        text = raw
    return text, start, end


def _walk_content(content: Sequence[Any], blocks: list[TextBlock]) -> None:
    """Append non-empty paragraph/cell blocks from a structural-element list."""
    for el in content:
        if not isinstance(el, Mapping):
            continue
        paragraph = el.get("paragraph")
        if isinstance(paragraph, Mapping):
            parsed = _paragraph_text_and_range(paragraph)
            if parsed is None:
                continue
            text, start, end = parsed
            if not text.strip():
                continue
            blocks.append(
                TextBlock(block_id=len(blocks), text=text, start_index=start, end_index=end)
            )
            continue
        table = el.get("table")
        if isinstance(table, Mapping):
            rows = table.get("tableRows")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                cells = row.get("tableCells")
                if not isinstance(cells, list):
                    continue
                for cell in cells:
                    if not isinstance(cell, Mapping):
                        continue
                    nested = cell.get("content")
                    if isinstance(nested, list):
                        _walk_content(nested, blocks)


def extract_text_blocks(document: Mapping[str, Any]) -> list[TextBlock]:
    """Collect numbered text blocks from a ``documents.get`` body.

    Args:
        document: Google Docs API document resource.

    Returns:
        Blocks in document order. Empty paragraphs are skipped.
    """
    body = document.get("body")
    if not isinstance(body, Mapping):
        return []
    content = body.get("content")
    if not isinstance(content, list):
        return []
    blocks: list[TextBlock] = []
    _walk_content(content, blocks)
    return blocks


def format_blocks_for_model(blocks: Sequence[TextBlock]) -> str:
    """Render blocks as ``BLOCK n: text`` lines for the model user message."""
    lines = [f"BLOCK {b.block_id}: {b.text}" for b in blocks]
    return "\n".join(lines)


def replacement_batch_requests(
    blocks: Sequence[TextBlock],
    replacements: Sequence[TextReplacement],
) -> list[dict[str, Any]]:
    """Build Docs ``batchUpdate`` delete+insert requests, last block first.

    Args:
        blocks: Extracted blocks (indices must match the document being edited).
        replacements: Model rewrites.

    Returns:
        Requests safe to send in one ``batchUpdate`` (later ranges first).

    Raises:
        GoogleDocsApplyError: Unknown ``block_id``.
    """
    by_id = {b.block_id: b for b in blocks}
    ordered: list[tuple[TextBlock, str]] = []
    for item in replacements:
        block = by_id.get(item.block_id)
        if block is None:
            raise GoogleDocsApplyError(f"Unknown block_id {item.block_id}.")
        ordered.append((block, item.text))
    ordered.sort(key=lambda pair: pair[0].start_index, reverse=True)
    requests: list[dict[str, Any]] = []
    for block, new_text in ordered:
        if block.start_index >= block.end_index:
            continue
        requests.append(
            {
                "deleteContentRange": {
                    "range": {
                        "startIndex": block.start_index,
                        "endIndex": block.end_index,
                    }
                }
            }
        )
        requests.append(
            {
                "insertText": {
                    "location": {"index": block.start_index},
                    "text": new_text,
                }
            }
        )
    return requests
