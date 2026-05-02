"""Tests for :mod:`resume_customizer.cost_ledger`."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from resume_customizer.cost_ledger import (
    CostLedgerEntry,
    append_entry,
    default_ledger_path,
    load_ledger,
    total_estimated_cost_usd,
)


class TestCostLedger(unittest.TestCase):
    """Tests for JSON ledger read/write."""

    def test_append_and_total(self) -> None:
        """Two appends preserve full-precision floats and sum correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "cost_data" / "customization_cost_ledger.json"
            e1 = CostLedgerEntry(
                ts="2026-01-01T00:00:00+00:00",
                model="claude-sonnet-4-6",
                input_tokens=10,
                output_tokens=20,
                estimated_cost_usd=0.000123456789,
            )
            e2 = CostLedgerEntry(
                ts="2026-01-02T00:00:00+00:00",
                model="claude-haiku-4-5",
                input_tokens=1,
                output_tokens=1,
                estimated_cost_usd=0.000006,
            )
            append_entry(path, e1)
            append_entry(path, e2)
            entries = load_ledger(path)
            self.assertEqual(len(entries), 2)
            self.assertAlmostEqual(entries[0].estimated_cost_usd or 0.0, 0.000123456789)
            self.assertAlmostEqual(total_estimated_cost_usd(entries), 0.000129456789)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["version"], 1)
            self.assertEqual(len(raw["entries"]), 2)

    def test_total_skips_none_cost(self) -> None:
        """Entries with unknown pricing do not add to the total."""
        entries = [
            CostLedgerEntry(
                ts="t",
                model="x",
                input_tokens=1,
                output_tokens=1,
                estimated_cost_usd=None,
            ),
            CostLedgerEntry(
                ts="t2",
                model="claude-haiku-4-5",
                input_tokens=1,
                output_tokens=0,
                estimated_cost_usd=1e-6,
            ),
        ]
        self.assertAlmostEqual(total_estimated_cost_usd(entries), 1e-6)

    def test_default_ledger_path_ends_with_cost_data_json(self) -> None:
        """Default path uses ``cost_data`` directory and fixed filename."""
        p = default_ledger_path()
        self.assertEqual(p.name, "customization_cost_ledger.json")
        self.assertEqual(p.parent.name, "cost_data")


if __name__ == "__main__":
    unittest.main()
