"""Tests for :mod:`resume_customizer.pricing`."""

from __future__ import annotations

import unittest

from resume_customizer.pricing import (
    combine_estimated_run_cost_usd,
    estimate_message_cost_usd,
    format_usd_display,
    model_has_list_price,
)


class TestPricing(unittest.TestCase):
    """Tests for list-price helpers."""

    def test_sonnet_million_input_only(self) -> None:
        """Sonnet 4.6 base input is $3/MTok."""
        cost = estimate_message_cost_usd(
            "claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        self.assertEqual(cost, 3.0)

    def test_haiku_input_and_output(self) -> None:
        """Haiku 4.5 is $1/MTok in, $5/MTok out."""
        cost = estimate_message_cost_usd(
            "claude-haiku-4-5",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        self.assertEqual(cost, 6.0)

    def test_unknown_model_returns_none(self) -> None:
        """Models without a table entry have no estimate."""
        self.assertIsNone(
            estimate_message_cost_usd("claude-unknown", input_tokens=100, output_tokens=100)
        )
        self.assertFalse(model_has_list_price("claude-unknown"))

    def test_format_usd_display_two_decimals(self) -> None:
        """UI formatting uses two decimal places."""
        self.assertEqual(format_usd_display(1.2), "$1.20")
        self.assertEqual(format_usd_display(0.006), "$0.01")

    def test_combine_run_cost_single_call(self) -> None:
        total, partial = combine_estimated_run_cost_usd(
            first_cost=1.5, second_cost=None, two_calls=False
        )
        self.assertEqual(total, 1.5)
        self.assertFalse(partial)

    def test_combine_run_cost_two_calls(self) -> None:
        total, partial = combine_estimated_run_cost_usd(
            first_cost=1.0, second_cost=2.5, two_calls=True
        )
        self.assertEqual(total, 3.5)
        self.assertFalse(partial)

    def test_combine_run_cost_two_calls_partial(self) -> None:
        total, partial = combine_estimated_run_cost_usd(
            first_cost=1.0, second_cost=None, two_calls=True
        )
        self.assertEqual(total, 1.0)
        self.assertTrue(partial)


if __name__ == "__main__":
    unittest.main()
