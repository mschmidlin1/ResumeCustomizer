"""Tests for :mod:`resume_customizer.page_budget`."""

from __future__ import annotations

import unittest

import anthropic

from resume_customizer.claude_service import CustomizationUsage
from resume_customizer.page_budget import (
    CondensePassResult,
    enforce_page_budget,
    keep_first_version_warning,
)
from resume_customizer.parsing import CustomizationParseError


def _usage() -> CustomizationUsage:
    return CustomizationUsage(
        model="claude-sonnet-4-6",
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=0.01,
    )


class TestEnforcePageBudget(unittest.TestCase):
    def test_under_budget_skips_condense(self) -> None:
        called = False

        def attempt() -> CondensePassResult:
            nonlocal called
            called = True
            return CondensePassResult(output_pages=1, usage=_usage())

        outcome = enforce_page_budget(
            source_pages=2,
            output_pages=1,
            attempt_condense=attempt,
            still_over_manual_hint="Tighten manually.",
        )
        self.assertFalse(called)
        self.assertFalse(outcome.condense_succeeded)
        self.assertEqual(outcome.output_pages, 1)
        self.assertEqual(outcome.warnings, ())

    def test_condense_success_still_over(self) -> None:
        def attempt() -> CondensePassResult:
            return CondensePassResult(output_pages=3, usage=_usage(), remeasured=True)

        outcome = enforce_page_budget(
            source_pages=1,
            output_pages=2,
            attempt_condense=attempt,
            still_over_manual_hint="Tighten manually.",
        )
        self.assertTrue(outcome.condense_succeeded)
        self.assertEqual(outcome.output_pages, 3)
        self.assertIsNotNone(outcome.usage)
        self.assertEqual(len(outcome.warnings), 1)
        self.assertIn("still has **3**", outcome.warnings[0])

    def test_parse_error_keeps_first(self) -> None:
        def attempt() -> CondensePassResult:
            raise CustomizationParseError("bad json")

        outcome = enforce_page_budget(
            source_pages=1,
            output_pages=2,
            attempt_condense=attempt,
            still_over_manual_hint="Tighten manually.",
        )
        self.assertFalse(outcome.condense_succeeded)
        self.assertEqual(outcome.output_pages, 2)
        self.assertIn("could not parse", outcome.warnings[0])
        self.assertIn("Keeping the first version", outcome.warnings[0])

    def test_api_error_keeps_first(self) -> None:
        def attempt() -> CondensePassResult:
            raise anthropic.APIError(
                message="boom",
                request=None,  # type: ignore[arg-type]
                body=None,
            )

        outcome = enforce_page_budget(
            source_pages=1,
            output_pages=2,
            attempt_condense=attempt,
            still_over_manual_hint="Tighten manually.",
        )
        self.assertFalse(outcome.condense_succeeded)
        self.assertIn("API error", outcome.warnings[0])

    def test_apply_failure_warning_no_still_over(self) -> None:
        def attempt() -> CondensePassResult:
            return CondensePassResult(
                output_pages=2,
                usage=_usage(),
                warnings=("apply failed",),
                remeasured=False,
            )

        outcome = enforce_page_budget(
            source_pages=1,
            output_pages=2,
            attempt_condense=attempt,
            still_over_manual_hint="Tighten manually.",
        )
        self.assertTrue(outcome.condense_succeeded)
        self.assertEqual(outcome.warnings, ("apply failed",))

    def test_keep_first_helper(self) -> None:
        text = keep_first_version_warning("Nope.", output_pages=4, source_pages=2)
        self.assertIn("**4**", text)
        self.assertIn("**2**", text)


if __name__ == "__main__":
    unittest.main()
