"""Tests for :mod:`resume_customizer.google_docs_ops`."""

from __future__ import annotations

import unittest

from resume_customizer.google_docs_ops import (
    GoogleDocsApplyError,
    extract_text_blocks,
    format_blocks_for_model,
    replacement_batch_requests,
)
from resume_customizer.parsing import TextReplacement


def _doc() -> dict:
    return {
        "body": {
            "content": [
                {"sectionBreak": {}, "startIndex": 0, "endIndex": 1},
                {
                    "startIndex": 1,
                    "endIndex": 10,
                    "paragraph": {
                        "elements": [
                            {
                                "startIndex": 1,
                                "endIndex": 10,
                                "textRun": {"content": "Jane Doe\n"},
                            }
                        ]
                    },
                },
                {
                    "startIndex": 10,
                    "endIndex": 22,
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {
                                        "content": [
                                            {
                                                "paragraph": {
                                                    "elements": [
                                                        {
                                                            "startIndex": 12,
                                                            "endIndex": 18,
                                                            "textRun": {"content": "Cell\n"},
                                                        }
                                                    ]
                                                }
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                },
                {
                    "startIndex": 22,
                    "endIndex": 23,
                    "paragraph": {
                        "elements": [
                            {
                                "startIndex": 22,
                                "endIndex": 23,
                                "textRun": {"content": "\n"},
                            }
                        ]
                    },
                },
            ]
        }
    }


class TestExtractTextBlocks(unittest.TestCase):
    """Block extraction from Docs JSON."""

    def test_paragraphs_and_table_cells(self) -> None:
        blocks = extract_text_blocks(_doc())
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].text, "Jane Doe")
        self.assertEqual(blocks[0].start_index, 1)
        self.assertEqual(blocks[0].end_index, 9)
        self.assertEqual(blocks[1].text, "Cell")
        self.assertEqual(blocks[1].block_id, 1)

    def test_empty_paragraphs_skipped(self) -> None:
        texts = [b.text for b in extract_text_blocks(_doc())]
        self.assertNotIn("", texts)

    def test_format_for_model(self) -> None:
        text = format_blocks_for_model(extract_text_blocks(_doc()))
        self.assertIn("BLOCK 0: Jane Doe", text)
        self.assertIn("BLOCK 1: Cell", text)


class TestReplacementBatchRequests(unittest.TestCase):
    """batchUpdate request order and unknown ids."""

    def test_later_ranges_first(self) -> None:
        blocks = extract_text_blocks(_doc())
        reqs = replacement_batch_requests(
            blocks,
            (
                TextReplacement(block_id=0, text="John Doe"),
                TextReplacement(block_id=1, text="Box"),
            ),
        )
        self.assertEqual(len(reqs), 4)
        self.assertEqual(reqs[0]["deleteContentRange"]["range"]["startIndex"], 12)
        self.assertEqual(reqs[2]["deleteContentRange"]["range"]["startIndex"], 1)
        self.assertEqual(reqs[3]["insertText"]["text"], "John Doe")

    def test_unknown_block_id(self) -> None:
        blocks = extract_text_blocks(_doc())
        with self.assertRaises(GoogleDocsApplyError):
            replacement_batch_requests(blocks, (TextReplacement(block_id=99, text="x"),))


if __name__ == "__main__":
    unittest.main()
