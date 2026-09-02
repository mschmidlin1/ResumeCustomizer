"""Tests for :mod:`resume_scorer.ledger` using mongomock."""

from __future__ import annotations

import unittest

import mongomock

from resume_scorer.ledger import ScorerLedgerMongoService
from resume_scorer.models import ScoreResult, TxCallInfo


class TestScorerLedgerMongoService(unittest.TestCase):
    def setUp(self) -> None:
        client = mongomock.MongoClient()
        self._svc = ScorerLedgerMongoService.from_client(client, "test_resume_scorer")

    def test_add_run_and_totals(self) -> None:
        calls = [
            TxCallInfo("/parser/resume", 1.0, 499.0, "a", "Success"),
            TxCallInfo("/parser/joborder", 1.0, 498.0, "b", "Success"),
            TxCallInfo("/scorer/bimetric/joborder", 1.0, 497.0, "c", "Success"),
        ]
        self._svc.add_run(
            credits_used=3.0,
            credits_remaining=497.0,
            transaction_ids=["a", "b", "c"],
            calls=calls,
        )
        self._svc.add_run(
            credits_used=1.0,
            credits_remaining=496.0,
            transaction_ids=["d"],
            calls=[TxCallInfo("/parser/resume", 1.0, 496.0, "d", "Success")],
            succeeded=False,
            error="job parse failed",
        )
        self.assertAlmostEqual(self._svc.get_total_credits(), 4.0)
        self.assertAlmostEqual(self._svc.get_latest_credits_remaining() or 0.0, 496.0)

    def test_add_score_result(self) -> None:
        result = ScoreResult(
            overall_score=80,
            weighted_score=75,
            reverse_score=70,
            categories=[],
            matched_skills=["Python"],
            missing_skills=[],
            education=None,
            credits_used=3.2,
            credits_remaining=490.0,
            transaction_ids=["x"],
            calls=[TxCallInfo("/parser/resume", 1.0, 490.0, "x", "Success")],
        )
        self._svc.add_score_result(result)
        self.assertAlmostEqual(self._svc.get_total_credits(), 3.2)

    def test_empty_ledger(self) -> None:
        self.assertEqual(self._svc.get_total_credits(), 0.0)
        self.assertIsNone(self._svc.get_latest_credits_remaining())
