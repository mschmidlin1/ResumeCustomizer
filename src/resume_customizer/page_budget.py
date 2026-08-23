"""Shared customize → optional condense control flow for page-count budgets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import anthropic

from resume_customizer.claude_service import CustomizationUsage
from resume_customizer.parsing import CustomizationParseError


@dataclass(frozen=True, slots=True)
class CondensePassResult:
    """Outcome of one format-specific condense attempt after the model returns.

    Attributes:
        output_pages: Measured pages after apply/remeasure, or the pre-condense
            count when remeasure did not succeed.
        usage: Token usage when the model call succeeded.
        warnings: Format-specific warnings (e.g. apply/compile failure).
        remeasured: True when a new page count was obtained after applying edits.
    """

    output_pages: int
    usage: CustomizationUsage | None = None
    warnings: tuple[str, ...] = ()
    remeasured: bool = True


@dataclass(frozen=True, slots=True)
class PageBudgetOutcome:
    """Result of :func:`enforce_page_budget`."""

    output_pages: int
    condense_succeeded: bool
    warnings: tuple[str, ...]
    usage: CustomizationUsage | None = None


def keep_first_version_warning(reason: str, *, output_pages: int, source_pages: int) -> str:
    """Standard warning when condense fails and the first customized version is kept."""
    return (
        f"{reason} "
        f"Keeping the first version (**{output_pages}** pages; target **{source_pages}**)."
    )


def still_over_budget_warning(*, output_pages: int, source_pages: int, manual_hint: str) -> str:
    """Standard warning when condense ran but the PDF is still over the page budget."""
    return (
        f"After the condense pass, the PDF still has **{output_pages}** page(s) "
        f"(target **{source_pages}**). {manual_hint}"
    )


def enforce_page_budget(
    *,
    source_pages: int,
    output_pages: int,
    attempt_condense: Callable[[], CondensePassResult],
    still_over_manual_hint: str,
) -> PageBudgetOutcome:
    """If ``output_pages`` exceeds ``source_pages``, run one condense attempt.

    ``attempt_condense`` performs the format-specific model call, apply, and
    remeasure. It may raise :class:`CustomizationParseError`,
    :class:`anthropic.APIError`, or other exceptions; those become keep-first
    warnings. When it returns successfully with ``remeasured`` and pages still
    over budget, a still-over warning is appended.
    """
    if output_pages <= source_pages:
        return PageBudgetOutcome(
            output_pages=output_pages,
            condense_succeeded=False,
            warnings=(),
        )

    try:
        result = attempt_condense()
    except CustomizationParseError as exc:
        return PageBudgetOutcome(
            output_pages=output_pages,
            condense_succeeded=False,
            warnings=(
                keep_first_version_warning(
                    f"Condense pass could not parse model output ({exc}).",
                    output_pages=output_pages,
                    source_pages=source_pages,
                ),
            ),
        )
    except anthropic.APIError as exc:
        return PageBudgetOutcome(
            output_pages=output_pages,
            condense_succeeded=False,
            warnings=(
                keep_first_version_warning(
                    f"Condense pass API error ({exc}).",
                    output_pages=output_pages,
                    source_pages=source_pages,
                ),
            ),
        )
    except Exception as exc:
        return PageBudgetOutcome(
            output_pages=output_pages,
            condense_succeeded=False,
            warnings=(
                keep_first_version_warning(
                    f"Condense pass failed ({exc}).",
                    output_pages=output_pages,
                    source_pages=source_pages,
                ),
            ),
        )

    warnings = list(result.warnings)
    condense_succeeded = result.usage is not None
    final_pages = result.output_pages
    if result.remeasured and final_pages > source_pages:
        warnings.append(
            still_over_budget_warning(
                output_pages=final_pages,
                source_pages=source_pages,
                manual_hint=still_over_manual_hint,
            )
        )
    return PageBudgetOutcome(
        output_pages=final_pages,
        condense_succeeded=condense_succeeded,
        warnings=tuple(warnings),
        usage=result.usage,
    )
