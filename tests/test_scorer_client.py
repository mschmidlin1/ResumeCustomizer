"""Tests for :mod:`resume_scorer.client` with mocked HTTP."""

from __future__ import annotations

import base64
import unittest
from unittest.mock import MagicMock, patch

import httpx

from resume_scorer.client import TxApiError, TxClient


def _response(status: int, payload: dict, url: str = "https://api.us.textkernel.com/tx/v10/x") -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("POST", url),
    )


class TestTxClient(unittest.TestCase):
    def setUp(self) -> None:
        self.http = MagicMock()
        self.client = TxClient("acct", "key", "US", http=self.http)

    def test_parse_resume_sends_base64_and_returns_resume_data(self) -> None:
        self.http.post.return_value = _response(
            200,
            {
                "Info": {
                    "Code": "Success",
                    "TransactionCost": 1.0,
                    "TransactionId": "t1",
                    "CustomerDetails": {"CreditsRemaining": 499},
                },
                "Value": {"ResumeData": {"ContactInformation": {}}},
            },
        )
        data, info = self.client.parse_resume(b"%PDF-1.4 fake")
        self.assertEqual(data, {"ContactInformation": {}})
        self.assertAlmostEqual(info.transaction_cost, 1.0)
        kwargs = self.http.post.call_args.kwargs
        self.assertIn("/parser/resume", self.http.post.call_args.args[0])
        self.assertEqual(kwargs["headers"]["Tx-AccountId"], "acct")
        encoded = kwargs["json"]["DocumentAsBase64String"]
        self.assertEqual(base64.b64decode(encoded), b"%PDF-1.4 fake")
        self.assertRegex(kwargs["json"]["DocumentLastModified"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(kwargs["json"]["SkillsSettings"], {"Normalize": True, "TaxonomyVersion": "V2"})
        self.assertNotIn("ProfessionsSettings", kwargs["json"])

    def test_parse_omits_skills_settings_when_disabled(self) -> None:
        client = TxClient("acct", "key", normalize_skills=False, http=self.http)
        self.http.post.return_value = _response(
            200,
            {"Info": {"Code": "Success", "TransactionCost": 1.0}, "Value": {"JobData": {"JobTitle": "X"}}},
        )
        client.parse_job("Need Python")
        payload = self.http.post.call_args.kwargs["json"]
        self.assertNotIn("SkillsSettings", payload)

    def test_parse_options_when_flags_enabled(self) -> None:
        client = TxClient(
            "acct",
            "key",
            normalize_skills=True,
            normalize_job_titles=True,
            http=self.http,
        )
        self.http.post.return_value = _response(
            200,
            {"Info": {"Code": "Success", "TransactionCost": 1.2}, "Value": {"JobData": {"JobTitle": "X"}}},
        )
        client.parse_job("Need Python")
        payload = self.http.post.call_args.kwargs["json"]
        self.assertEqual(payload["SkillsSettings"], {"Normalize": True, "TaxonomyVersion": "V2"})
        self.assertEqual(payload["ProfessionsSettings"], {"Normalize": True})
        self.assertEqual(base64.b64decode(payload["DocumentAsBase64String"]).decode("utf-8"), "Need Python")

    def test_401_raises(self) -> None:
        self.http.post.return_value = _response(
            401,
            {"Info": {"Code": "AuthenticationError", "Message": "bad key", "TransactionCost": 0}},
        )
        with self.assertRaises(TxApiError) as ctx:
            self.client.parse_job("hello")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIsNotNone(ctx.exception.call_info)

    def test_score_to_job_posts_parsed_documents(self) -> None:
        self.http.post.return_value = _response(
            200,
            {
                "Info": {"Code": "Success", "TransactionCost": 1.0},
                "Value": {"Matches": [{"SovScore": 10}]},
            },
        )
        body, info = self.client.score_to_job({"title": "job"}, {"name": "resume"})
        self.assertEqual(body["Value"]["Matches"][0]["SovScore"], 10)
        self.assertAlmostEqual(info.transaction_cost, 1.0)
        payload = self.http.post.call_args.kwargs["json"]
        self.assertEqual(payload["SourceJob"]["JobData"], {"title": "job"})
        self.assertEqual(payload["TargetResumes"][0]["ResumeData"], {"name": "resume"})
        self.assertIn("/scorer/bimetric/joborder", self.http.post.call_args.args[0])

    def test_non_success_info_code_raises(self) -> None:
        self.http.post.return_value = _response(
            200,
            {"Info": {"Code": "InvalidParameter", "Message": "nope", "TransactionCost": 0}},
        )
        with self.assertRaises(TxApiError) as ctx:
            self.client.parse_job("x")
        self.assertIn("nope", str(ctx.exception))

    def test_from_secrets_uses_settings(self) -> None:
        with (
            patch("resume_scorer.client.scorer_settings.DATA_CENTER", "EU"),
            patch("resume_scorer.client.scorer_settings.NORMALIZE_SKILLS", False),
            patch("resume_scorer.client.scorer_settings.NORMALIZE_JOB_TITLES", True),
        ):
            client = TxClient.from_secrets(
                {"account_id": "a", "service_key": "b"},
                http=self.http,
            )
        self.assertTrue(client._base.startswith("https://api.eu.textkernel.com"))
        self.assertTrue(client._normalize_job_titles)
        self.assertFalse(client._normalize_skills)


if __name__ == "__main__":
    unittest.main()
