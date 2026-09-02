"""Map Textkernel bimetric JSON into :class:`ScoreResult`."""

from __future__ import annotations

from typing import Any

from resume_scorer.models import CategoryScore, EducationMatch, ScoreResult, TxCallInfo

_CATEGORY_ORDER = (
    "JobTitles",
    "Skills",
    "Education",
    "Languages",
    "Certifications",
    "Taxonomies",
    "Industries",
    "ManagementLevel",
    "ExecutiveType",
)

_CATEGORY_LABELS = {
    "JobTitles": "Job titles",
    "Skills": "Skills",
    "Education": "Education",
    "Languages": "Languages",
    "Certifications": "Certifications",
    "Taxonomies": "Industries",
    "Industries": "Industries",
    "ManagementLevel": "Management level",
    "ExecutiveType": "Executive type",
}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(round(number))


def call_info_from_response(payload: dict[str, Any], *, endpoint: str) -> TxCallInfo:
    """Extract credit fields from a Tx JSON body (success or error)."""
    info = _mapping(payload.get("Info") if isinstance(payload, dict) else None)
    customer = _mapping(info.get("CustomerDetails"))
    return TxCallInfo(
        endpoint=endpoint,
        transaction_cost=_as_float(info.get("TransactionCost")) or 0.0,
        credits_remaining=_as_float(customer.get("CreditsRemaining")),
        transaction_id=_str_or_none(info.get("TransactionId")),
        code=_str_or_none(info.get("Code")),
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _term_names(items: Any) -> list[str]:
    """Flatten Found/NotFound arrays of strings or ``{Skill, RawTerm, Name}`` objects."""
    if not isinstance(items, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in items:
        name: str | None = None
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            for key in ("Skill", "RawTerm", "Name"):
                raw = item.get(key)
                if raw is not None and str(raw).strip():
                    name = str(raw).strip()
                    break
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _category_scores(enriched: dict[str, Any]) -> list[CategoryScore]:
    found: list[CategoryScore] = []
    seen_labels: set[str] = set()
    for key in _CATEGORY_ORDER:
        block = enriched.get(key)
        if not isinstance(block, dict):
            continue
        score = _as_float(block.get("UnweightedScore"))
        if score is None:
            continue
        label = _CATEGORY_LABELS.get(key, key)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        found.append(CategoryScore(key=key, label=label, score=score))
    return found


def _education(enriched: dict[str, Any]) -> EducationMatch | None:
    block = enriched.get("Education")
    if not isinstance(block, dict):
        return None
    expected = _str_or_none(block.get("ExpectedEducation"))
    actual = _str_or_none(block.get("ActualEducation"))
    comparison = _str_or_none(block.get("Comparison"))
    score = _as_float(block.get("UnweightedScore"))
    if expected is None and actual is None and comparison is None and score is None:
        return None
    return EducationMatch(expected=expected, actual=actual, comparison=comparison, score=score)


def map_bimetric_response(
    payload: dict[str, Any],
    *,
    calls: list[TxCallInfo],
) -> ScoreResult:
    """Map ``POST /v10/scorer/bimetric/joborder`` JSON into a display DTO."""
    value = _mapping(payload.get("Value"))
    matches = value.get("Matches")
    match = matches[0] if isinstance(matches, list) and matches else {}
    match = _mapping(match)
    enriched = _mapping(match.get("EnrichedScoreData"))
    skills = _mapping(enriched.get("Skills"))

    credits_used = sum(c.transaction_cost for c in calls)
    remaining: float | None = None
    for call in reversed(calls):
        if call.credits_remaining is not None:
            remaining = call.credits_remaining
            break

    overall = _as_int(match.get("SovScore"))
    if overall is None:
        overall = 0

    return ScoreResult(
        overall_score=max(0, min(100, overall)),
        weighted_score=_as_int(match.get("WeightedScore")),
        reverse_score=_as_int(match.get("ReverseCompatibilityScore")),
        categories=_category_scores(enriched),
        matched_skills=_term_names(skills.get("Found")),
        missing_skills=_term_names(skills.get("NotFound")),
        education=_education(enriched),
        credits_used=credits_used,
        credits_remaining=remaining,
        transaction_ids=[c.transaction_id for c in calls if c.transaction_id],
        calls=list(calls),
    )
