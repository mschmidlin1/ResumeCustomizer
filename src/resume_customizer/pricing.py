"""Estimated USD from Anthropic Messages API usage using published list prices.

Rates match https://docs.anthropic.com/en/about-claude/pricing (base input + output,
no prompt caching). Update when Anthropic changes pricing.
"""

from __future__ import annotations

# Per-million-token USD rates: (base input, output).
_MODEL_RATES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-6": (5.0, 25.0),
}


def model_has_list_price(model: str) -> bool:
    """Return True if ``model`` has a configured input/output price estimate."""
    return model in _MODEL_RATES_PER_MTOK


def estimate_message_cost_usd(model: str, *, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate request cost in USD from token usage and model id.

    Args:
        model: Anthropic model id passed to the Messages API.
        input_tokens: Value from ``message.usage.input_tokens``.
        output_tokens: Value from ``message.usage.output_tokens``.

    Returns:
        Estimated cost in USD, or ``None`` when the model has no pricing entry.
    """
    rates = _MODEL_RATES_PER_MTOK.get(model)
    if rates is None:
        return None
    inp_rate, out_rate = rates
    return (input_tokens / 1_000_000) * inp_rate + (output_tokens / 1_000_000) * out_rate


def format_usd_display(amount: float) -> str:
    """Format a dollar amount for UI (two decimal places)."""
    return f"${amount:.2f}"


def combine_estimated_run_cost_usd(
    *,
    first_cost: float | None,
    second_cost: float | None,
    two_calls: bool,
) -> tuple[float | None, bool]:
    """Combine per-call estimates for one user Run. Returns ``(total, is_partial)``.

    When ``two_calls`` is True, missing estimate for either call yields a partial total
    (sum of known parts only).
    """
    if not two_calls:
        return (first_cost, first_cost is None)
    if first_cost is not None and second_cost is not None:
        return (first_cost + second_cost, False)
    if first_cost is not None:
        return (first_cost, True)
    if second_cost is not None:
        return (second_cost, True)
    return (None, True)
