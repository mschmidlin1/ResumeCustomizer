"""Tests for :mod:`resume_customizer.claude_service` with mocked Anthropic client."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from resume_customizer.claude_service import ClaudeCustomizationService


def _fake_message(
    text: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> SimpleNamespace:
    """Build a minimal object matching the shape read by the service.

    Args:
        text: Simulated assistant plain-text body.
        input_tokens: Simulated ``message.usage.input_tokens``.
        output_tokens: Simulated ``message.usage.output_tokens``.

    Returns:
        Namespace with ``content`` text blocks and ``usage``.
    """
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=[block], usage=usage)


class TestClaudeCustomizationService(unittest.TestCase):
    """Tests for :class:`ClaudeCustomizationService`."""

    @patch("resume_customizer.claude_service.anthropic.Anthropic")
    def test_customize_parses_json_response(self, mock_anthropic: MagicMock) -> None:
        """``customize`` forwards model settings and returns parsed payload."""
        api_response = _fake_message(
            '{"job_title": "Widget Engineer", "customized_latex": "\\\\documentclass{article}"}',
            input_tokens=1_000_000,
            output_tokens=0,
        )
        instance = mock_anthropic.return_value
        instance.messages.create.return_value = api_response

        service = ClaudeCustomizationService(api_key="test-key")
        result = service.customize(
            system_prompt="Be helpful.",
            job_description="We need widgets.",
            resume_latex="\\documentclass{article}",
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0.2,
        )

        instance.messages.create.assert_called_once()
        call_kw = instance.messages.create.call_args.kwargs
        self.assertEqual(call_kw["model"], "claude-sonnet-4-6")
        self.assertEqual(call_kw["max_tokens"], 1024)
        self.assertEqual(call_kw["temperature"], 0.2)
        self.assertIn("Be helpful.", call_kw["system"])
        self.assertEqual(result.payload.job_title, "Widget Engineer")
        self.assertIn("documentclass", result.payload.customized_latex)
        self.assertEqual(result.usage.model, "claude-sonnet-4-6")
        self.assertEqual(result.usage.input_tokens, 1_000_000)
        self.assertEqual(result.usage.output_tokens, 0)
        self.assertEqual(result.usage.estimated_cost_usd, 3.0)

    @patch("resume_customizer.claude_service.anthropic.Anthropic")
    def test_customize_includes_source_pdf_page_count(self, mock_anthropic: MagicMock) -> None:
        """When ``source_pdf_page_count`` is set, the user message includes it."""
        instance = mock_anthropic.return_value
        instance.messages.create.return_value = _fake_message(
            '{"job_title": "A", "customized_latex": "B"}',
        )

        service = ClaudeCustomizationService(api_key="k")
        service.customize(
            system_prompt="S",
            job_description="J",
            resume_latex="L",
            model="claude-sonnet-4-6",
            max_tokens=100,
            temperature=0.0,
            source_pdf_page_count=1,
        )

        user_text = instance.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("SOURCE_PDF_PAGE_COUNT: 1", user_text)

    @patch("resume_customizer.claude_service.anthropic.Anthropic")
    def test_condense_resume_to_page_budget(self, mock_anthropic: MagicMock) -> None:
        """``condense_resume_to_page_budget`` sends target and measured page counts."""
        instance = mock_anthropic.return_value
        instance.messages.create.return_value = _fake_message(
            '{"job_title": "A", "customized_latex": "\\\\documentclass{article}"}',
        )

        service = ClaudeCustomizationService(api_key="k")
        service.condense_resume_to_page_budget(
            system_prompt="S",
            job_description="Build widgets.",
            customized_latex="\\documentclass{article}",
            target_pdf_page_count=1,
            measured_pdf_page_count=2,
            model="claude-sonnet-4-6",
            max_tokens=512,
            temperature=0.1,
        )

        call_kw = instance.messages.create.call_args.kwargs
        self.assertIn("Additional instructions for this turn only", call_kw["system"])
        user_text = call_kw["messages"][0]["content"]
        self.assertIn("TARGET_PDF_PAGE_COUNT: 1", user_text)
        self.assertIn("MEASURED_CUSTOMIZED_PDF_PAGE_COUNT: 2", user_text)
        self.assertIn("CUSTOMIZED_LATEX:", user_text)

    @patch("resume_customizer.claude_service.anthropic.Anthropic")
    def test_customize_accepts_fenced_json(self, mock_anthropic: MagicMock) -> None:
        """Fenced JSON in the assistant reply is accepted."""
        fenced = """```json
{"job_title": "X", "customized_latex": "Y"}
```"""
        instance = mock_anthropic.return_value
        instance.messages.create.return_value = _fake_message(
            fenced,
            input_tokens=100,
            output_tokens=200,
        )

        service = ClaudeCustomizationService(api_key="k")
        result = service.customize(
            system_prompt="S",
            job_description="J",
            resume_latex="L",
            model="unknown-model-id",
            max_tokens=100,
            temperature=0.0,
        )
        self.assertEqual(result.payload.job_title, "X")
        self.assertEqual(result.payload.customized_latex, "Y")
        self.assertEqual(result.usage.input_tokens, 100)
        self.assertEqual(result.usage.output_tokens, 200)
        self.assertIsNone(result.usage.estimated_cost_usd)

    @patch("resume_customizer.claude_service.anthropic.Anthropic")
    def test_complete_json_maps_temperature_when_sdk_rejects_kwarg(self, mock_anthropic: MagicMock) -> None:
        """Anthropic SDK 1.x dropped ``temperature=``; send it in ``extra_body``."""
        instance = mock_anthropic.return_value
        captured: dict[str, object] = {}

        def _sdk1_create(
            *,
            max_tokens: int,
            messages: object,
            model: str,
            system: str = "",
            extra_body: dict | None = None,
        ) -> SimpleNamespace:
            captured["extra_body"] = extra_body
            return _fake_message('{"job_title": "A", "customized_latex": "B"}')

        instance.messages.create = _sdk1_create

        service = ClaudeCustomizationService(api_key="k")
        raw, usage = service.complete_json(
            system_text="S",
            user_content="U",
            model="claude-sonnet-4-6",
            max_tokens=100,
            temperature=0.45,
        )

        self.assertEqual(raw, '{"job_title": "A", "customized_latex": "B"}')
        self.assertEqual(usage.model, "claude-sonnet-4-6")
        extra_body = captured["extra_body"]
        assert isinstance(extra_body, dict)
        self.assertEqual(extra_body["temperature"], 0.45)

    @patch("resume_customizer.claude_service.anthropic.Anthropic")
    def test_complete_json_sends_output_config_schema(self, mock_anthropic: MagicMock) -> None:
        """Google replacements pass a JSON schema when the SDK supports it."""
        instance = mock_anthropic.return_value
        instance.messages.create.return_value = _fake_message(
            '{"job_title": "A", "replacements": []}',
        )

        service = ClaudeCustomizationService(api_key="k")
        service.complete_json(
            system_text="S",
            user_content="U",
            model="claude-sonnet-4-6",
            max_tokens=100,
            temperature=0.2,
            json_schema={"type": "object"},
        )

        call_kw = instance.messages.create.call_args.kwargs
        self.assertEqual(call_kw["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(call_kw["output_config"]["format"]["schema"], {"type": "object"})


if __name__ == "__main__":
    unittest.main()
