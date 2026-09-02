"""Tests for :mod:`resume_lib.auth_cookies`."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from resume_lib.auth_cookies import (
    APP_MAX_AGE_SECONDS,
    browser_credentials_from_token_dict,
    sign_app_cookie,
    sign_google_cookie,
    sign_oauth_handshake_state,
    sign_oauth_state_cookie,
    sign_payload,
    token_dict_from_browser_credentials,
    verify_app_cookie,
    verify_google_cookie,
    verify_oauth_handshake_state,
    verify_oauth_state_cookie,
    verify_payload,
)


class TestSignedCookies(unittest.TestCase):
    """HMAC cookie round-trips and rejection cases."""

    def test_app_cookie_roundtrip(self) -> None:
        value = sign_app_cookie("secret")
        self.assertTrue(verify_app_cookie(value, "secret"))
        self.assertFalse(verify_app_cookie(value, "other"))
        self.assertFalse(verify_app_cookie(value[:-1] + "x", "secret"))

    def test_oauth_handshake_state_roundtrip(self) -> None:
        verifier = "a" * 64
        value = sign_oauth_handshake_state(verifier, "secret")
        self.assertNotIn(".", value)
        self.assertEqual(verify_oauth_handshake_state(value, "secret"), verifier)
        self.assertIsNone(verify_oauth_handshake_state(value, "nope"))
        self.assertIsNone(verify_oauth_handshake_state("not-signed", "secret"))

    def test_oauth_handshake_state_rejects_short_verifier(self) -> None:
        value = sign_payload({"verifier": "short"}, "secret").replace(".", "~", 1)
        self.assertIsNone(verify_oauth_handshake_state(value, "secret"))

    def test_oauth_state_cookie_roundtrip(self) -> None:
        value = sign_oauth_state_cookie("abc123", "secret", code_verifier="pkce-verifier")
        self.assertEqual(
            verify_oauth_state_cookie(value, "secret"),
            {"state": "abc123", "verifier": "pkce-verifier"},
        )
        self.assertIsNone(verify_oauth_state_cookie(value, "nope"))

    def test_expired_payload_rejected(self) -> None:
        with patch("resume_lib.auth_cookies.time.time", return_value=1_000):
            value = sign_payload({"ok": True}, "secret")
        with patch("resume_lib.auth_cookies.time.time", return_value=1_000 + APP_MAX_AGE_SECONDS + 120):
            self.assertIsNone(verify_payload(value, "secret", max_age_seconds=APP_MAX_AGE_SECONDS))

    def test_google_cookie_omits_client_secret(self) -> None:
        token_dict = {
            "token": "access",
            "refresh_token": "refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "cid",
            "client_secret": "must-not-be-stored",
            "scopes": ["https://www.googleapis.com/auth/documents"],
            "expiry": "2026-01-01T00:00:00",
        }
        value = sign_google_cookie(token_dict, "user@example.com", "secret")
        payload = verify_google_cookie(value, "secret")
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["email"], "user@example.com")
        self.assertNotIn("client_secret", payload["creds"])
        self.assertEqual(payload["creds"]["token"], "access")
        self.assertEqual(payload["creds"]["refresh_token"], "refresh")
        rebuilt = token_dict_from_browser_credentials(payload["creds"], "server-secret")
        self.assertEqual(rebuilt["client_secret"], "server-secret")
        self.assertEqual(rebuilt["token"], "access")

    def test_pkce_verifier_length(self) -> None:
        from resume_customizer.google_auth import generate_pkce_verifier

        verifier = generate_pkce_verifier()
        self.assertEqual(len(verifier), 128)
        self.assertEqual(verify_oauth_handshake_state(sign_oauth_handshake_state(verifier, "s"), "s"), verifier)
        stripped = browser_credentials_from_token_dict({"token": "t", "client_secret": "s"})
        self.assertEqual(stripped["token"], "t")
        self.assertNotIn("client_secret", stripped)


if __name__ == "__main__":
    unittest.main()
