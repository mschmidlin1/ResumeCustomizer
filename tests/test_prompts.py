"""Tests for :mod:`resume_customizer.prompts`."""

from __future__ import annotations

import unittest

from resume_customizer.prompts import (
    DEFAULT_SYSTEM_PROMPT,
    SHARED_EDITORIAL_POLICY,
    compose_google_system_prompt,
    compose_latex_system_prompt,
)


class TestPrompts(unittest.TestCase):
    def test_default_is_shared_policy(self) -> None:
        self.assertEqual(DEFAULT_SYSTEM_PROMPT, SHARED_EDITORIAL_POLICY)
        self.assertIn("Truth and emphasis", DEFAULT_SYSTEM_PROMPT)

    def test_latex_compose_includes_prefix_sidebar_and_json(self) -> None:
        text = compose_latex_system_prompt("SIDEBAR_RULE")
        self.assertIn("LaTeX resume", text)
        self.assertIn("SIDEBAR_RULE", text)
        self.assertIn("customized_latex", text)
        self.assertNotIn("RESUME_BLOCKS", text)

    def test_google_compose_includes_prefix_sidebar_and_json(self) -> None:
        text = compose_google_system_prompt("SIDEBAR_RULE", condense=True)
        self.assertIn("numbered text blocks", text)
        self.assertIn("SIDEBAR_RULE", text)
        self.assertIn("replacements", text)
        self.assertIn("TARGET_PDF_PAGE_COUNT", text)


if __name__ == "__main__":
    unittest.main()
