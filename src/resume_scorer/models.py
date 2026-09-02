"""Display models for Textkernel bimetric score results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TxCallInfo:
    """Credits and ids from a single Tx API ``Info`` object."""

    endpoint: str
    transaction_cost: float
    credits_remaining: float | None
    transaction_id: str | None
    code: str | None = None


@dataclass(frozen=True, slots=True)
class CategoryScore:
    """One bimetric category with a 0–100 unweighted score."""

    key: str
    label: str
    score: float


@dataclass(frozen=True, slots=True)
class EducationMatch:
    """Education expected vs actual from EnrichedScoreData."""

    expected: str | None
    actual: str | None
    comparison: str | None
    score: float | None


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """Mapped fields the Score tab renders."""

    overall_score: int
    weighted_score: int | None
    reverse_score: int | None
    categories: list[CategoryScore]
    matched_skills: list[str]
    missing_skills: list[str]
    education: EducationMatch | None
    credits_used: float
    credits_remaining: float | None
    transaction_ids: list[str] = field(default_factory=list)
    calls: list[TxCallInfo] = field(default_factory=list)
