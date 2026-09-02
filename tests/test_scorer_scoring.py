"""Tests for :mod:`resume_scorer.scoring` with a fake client."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from resume_scorer.client import TxApiError
from resume_scorer.models import TxCallInfo
from resume_scorer.scoring import ScoreRunError, score_resume_against_job


class TestScoreResumeAgainstJob(unittest.TestCase):
    def test_happy_path_maps_result(self) -> None:
        client = MagicMock()
        client.parse_resume.return_value = (
            {"Resume": True},
            TxCallInfo("/parser/resume", 1.0, 498.0, "r", "Success"),
        )
        client.parse_job.return_value = (
            {"Job": True},
            TxCallInfo("/parser/joborder", 1.0, 497.0, "j", "Success"),
        )
        client.score_to_job.return_value = (
            {
                "Value": {
                    "Matches": [
                        {
                            "SovScore": 55,
                            "EnrichedScoreData": {"Skills": {"UnweightedScore": 40, "Found": ["Python"], "NotFound": []}},
                        }
                    ]
                }
            },
            TxCallInfo("/scorer/bimetric/joborder", 1.0, 496.0, "s", "Success"),
        )
        result = score_resume_against_job(client, b"pdf", "job text")
        self.assertEqual(result.overall_score, 55)
        self.assertEqual(result.matched_skills, ["Python"])
        self.assertAlmostEqual(result.credits_used, 3.0)
        client.score_to_job.assert_called_once_with({"Job": True}, {"Resume": True})

    def test_failure_after_first_call_keeps_credits(self) -> None:
        client = MagicMock()
        client.parse_resume.return_value = (
            {"Resume": True},
            TxCallInfo("/parser/resume", 1.0, 499.0, "r", "Success"),
        )
        client.parse_job.side_effect = TxApiError(
            "bad job",
            call_info=TxCallInfo("/parser/joborder", 1.0, 498.0, "j", "InvalidParameter"),
        )
        with self.assertRaises(ScoreRunError) as ctx:
            score_resume_against_job(client, b"pdf", "job")
        self.assertEqual(len(ctx.exception.calls), 2)
        self.assertAlmostEqual(ctx.exception.credits_used, 2.0)
        self.assertAlmostEqual(ctx.exception.credits_remaining, 498.0)


if __name__ == "__main__":
    unittest.main()
