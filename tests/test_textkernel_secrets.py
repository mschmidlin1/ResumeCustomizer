"""Tests for Textkernel secrets helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from resume_lib.secrets_config import get_textkernel_secrets


class TestGetTextkernelSecrets(unittest.TestCase):
    def test_missing_keys_returns_none(self) -> None:
        with patch("resume_lib.secrets_config._secrets_block", return_value={"account_id": "a"}):
            self.assertIsNone(get_textkernel_secrets())

    def test_credentials_only(self) -> None:
        with patch(
            "resume_lib.secrets_config._secrets_block",
            return_value={
                "account_id": "a",
                "service_key": "b",
                "data_center": "EU",
                "normalize_skills": "true",
            },
        ):
            secrets = get_textkernel_secrets()
        self.assertEqual(secrets, {"account_id": "a", "service_key": "b"})


if __name__ == "__main__":
    unittest.main()
