"""Tests for :mod:`resume_customizer.cost_ledger_mongo`."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import mongomock

from resume_customizer.cost_ledger import CostLedgerEntry
from resume_customizer.cost_ledger_mongo import CostLedgerMongoService
from resume_customizer.import_ledger_to_mongo import main as import_main


class TestCostLedgerMongoService(unittest.TestCase):
    """Tests for Mongo-backed ledger using mongomock."""

    def setUp(self) -> None:
        client = mongomock.MongoClient()
        self._svc = CostLedgerMongoService.from_client(client, "test_resume_customizer")

    def test_add_document_and_get_total(self) -> None:
        e1 = CostLedgerEntry(
            ts="2026-01-01T00:00:00+00:00",
            model="m",
            input_tokens=10,
            output_tokens=20,
            estimated_cost_usd=0.5,
        )
        e2 = CostLedgerEntry(
            ts="2026-01-02T00:00:00+00:00",
            model="m",
            input_tokens=1,
            output_tokens=1,
            estimated_cost_usd=None,
        )
        self.assertTrue(self._svc.add_document(e1, source="app"))
        self.assertTrue(self._svc.add_document(e2, source="app"))
        self.assertAlmostEqual(self._svc.get_total(), 0.5)

    def test_add_document_duplicate_returns_false(self) -> None:
        e = CostLedgerEntry(
            ts="2026-01-01T12:00:00+00:00",
            model="x",
            input_tokens=1,
            output_tokens=1,
            estimated_cost_usd=0.1,
        )
        self.assertTrue(self._svc.add_document(e))
        self.assertFalse(self._svc.add_document(e))
        self.assertAlmostEqual(self._svc.get_total(), 0.1)

    def test_different_rows_both_insert(self) -> None:
        e1 = CostLedgerEntry(
            ts="2026-01-01T00:00:00+00:00",
            model="m",
            input_tokens=1,
            output_tokens=0,
            estimated_cost_usd=0.1,
        )
        e2 = CostLedgerEntry(
            ts="2026-01-01T00:01:00+00:00",
            model="m",
            input_tokens=1,
            output_tokens=0,
            estimated_cost_usd=0.1,
        )
        self.assertTrue(self._svc.add_document(e1))
        self.assertTrue(self._svc.add_document(e2))
        self.assertAlmostEqual(self._svc.get_total(), 0.2)

    def test_import_many_counts(self) -> None:
        entries = [
            CostLedgerEntry(
                ts="2026-03-01T00:00:00+00:00",
                model="a",
                input_tokens=1,
                output_tokens=0,
                estimated_cost_usd=0.01,
            ),
            CostLedgerEntry(
                ts="2026-03-02T00:00:00+00:00",
                model="b",
                input_tokens=2,
                output_tokens=0,
                estimated_cost_usd=0.02,
            ),
        ]
        ins, skip = self._svc.import_many(entries, source="json_import")
        self.assertEqual(ins, 2)
        self.assertEqual(skip, 0)
        ins2, skip2 = self._svc.import_many(entries, source="json_import")
        self.assertEqual(ins2, 0)
        self.assertEqual(skip2, 2)

    def test_ping_true_with_mongomock(self) -> None:
        self.assertTrue(self._svc.ping())

    @patch.dict(os.environ, {"MONGODB_URI": "", "MONGO_URI": ""}, clear=False)
    def test_from_env_returns_none_without_uri(self) -> None:
        self.assertIsNone(CostLedgerMongoService.from_env())


class TestImportLedgerCli(unittest.TestCase):
    """Smoke tests for import CLI exit codes."""

    @patch.dict(os.environ, {"MONGODB_URI": "", "MONGO_URI": ""}, clear=False)
    def test_main_returns_one_without_mongo_uri(self) -> None:
        self.assertEqual(import_main([]), 1)


if __name__ == "__main__":
    unittest.main()
