"""Tests for :mod:`resume_scorer.mapping`."""

from __future__ import annotations

import unittest

from resume_scorer.mapping import call_info_from_response, map_bimetric_response
from resume_scorer.models import TxCallInfo


def _sample_bimetric_payload() -> dict:
    return {
        "Info": {
            "Code": "Success",
            "TransactionId": "score-1",
            "TransactionCost": 1.0,
            "CustomerDetails": {"CreditsRemaining": 496.0},
        },
        "Value": {
            "Matches": [
                {
                    "Id": "resume",
                    "SovScore": 82,
                    "WeightedScore": 80,
                    "ReverseCompatibilityScore": 70,
                    "EnrichedScoreData": {
                        "JobTitles": {
                            "UnweightedScore": 90,
                            "Found": [{"RawTerm": "Software Engineer", "VariationOf": "Engineer"}],
                            "NotFound": ["Staff Engineer"],
                        },
                        "Skills": {
                            "UnweightedScore": 75,
                            "Found": [
                                {"Skill": "Python", "IsCurrent": True},
                                {"Skill": "SQL"},
                                "OpenCV",
                            ],
                            "NotFound": ["Kubernetes", {"Skill": "AWS"}],
                        },
                        "Education": {
                            "UnweightedScore": 100,
                            "ExpectedEducation": "Bachelors",
                            "ActualEducation": "Masters",
                            "Comparison": "ExceedsExpected",
                        },
                        "Languages": {"UnweightedScore": 50},
                        "Taxonomies": {"UnweightedScore": 40},
                    },
                }
            ]
        },
    }


class TestCallInfoFromResponse(unittest.TestCase):
    def test_extracts_credits(self) -> None:
        info = call_info_from_response(
            {
                "Info": {
                    "Code": "Success",
                    "TransactionId": "abc",
                    "TransactionCost": 1.1,
                    "CustomerDetails": {"CreditsRemaining": 10},
                }
            },
            endpoint="/parser/resume",
        )
        self.assertEqual(info.endpoint, "/parser/resume")
        self.assertAlmostEqual(info.transaction_cost, 1.1)
        self.assertAlmostEqual(info.credits_remaining, 10.0)
        self.assertEqual(info.transaction_id, "abc")
        self.assertEqual(info.code, "Success")

    def test_missing_info_is_zero_cost(self) -> None:
        info = call_info_from_response({}, endpoint="/x")
        self.assertEqual(info.transaction_cost, 0.0)
        self.assertIsNone(info.credits_remaining)


class TestMapBimetricResponse(unittest.TestCase):
    def test_maps_scores_skills_and_education(self) -> None:
        calls = [
            TxCallInfo("/parser/resume", 1.0, 498.0, "r1", "Success"),
            TxCallInfo("/parser/joborder", 1.0, 497.0, "j1", "Success"),
            TxCallInfo("/scorer/bimetric/joborder", 1.0, 496.0, "s1", "Success"),
        ]
        result = map_bimetric_response(_sample_bimetric_payload(), calls=calls)
        self.assertEqual(result.overall_score, 82)
        self.assertEqual(result.weighted_score, 80)
        self.assertEqual(result.reverse_score, 70)
        labels = [c.label for c in result.categories]
        self.assertEqual(labels[:3], ["Job titles", "Skills", "Education"])
        self.assertIn("Industries", labels)
        skills = next(c for c in result.categories if c.key == "Skills")
        self.assertAlmostEqual(skills.score, 75)
        self.assertEqual(result.matched_skills, ["Python", "SQL", "OpenCV"])
        self.assertEqual(result.missing_skills, ["Kubernetes", "AWS"])
        self.assertIsNotNone(result.education)
        assert result.education is not None
        self.assertEqual(result.education.comparison, "ExceedsExpected")
        self.assertEqual(result.education.expected, "Bachelors")
        self.assertEqual(result.education.actual, "Masters")
        self.assertAlmostEqual(result.credits_used, 3.0)
        self.assertAlmostEqual(result.credits_remaining, 496.0)
        self.assertEqual(result.transaction_ids, ["r1", "j1", "s1"])

    def test_empty_matches_defaults_overall_zero(self) -> None:
        result = map_bimetric_response({"Value": {"Matches": []}}, calls=[])
        self.assertEqual(result.overall_score, 0)
        self.assertEqual(result.matched_skills, [])
        self.assertEqual(result.credits_used, 0.0)


if __name__ == "__main__":
    unittest.main()
