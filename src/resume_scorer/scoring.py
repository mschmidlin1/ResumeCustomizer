"""Orchestrate parse-resume, parse-job, and bimetric score-to-job."""

from __future__ import annotations

from resume_scorer.client import TxApiError, TxClient
from resume_scorer.mapping import map_bimetric_response
from resume_scorer.models import ScoreResult, TxCallInfo


def score_resume_against_job(
    client: TxClient,
    pdf_bytes: bytes,
    job_text: str,
) -> ScoreResult:
    """Run the three Tx calls and map the bimetric payload.

    Credits from successful (or billed-error) calls are attached to the result
    when mapping succeeds. If a later call fails, ``TxApiError.call_info`` plus
    ``partial_calls`` on the exception are not used; the caller should catch
    :class:`TxApiError` and read ``call_info``. This function stores every
    completed call on ``ScoreRunError.calls`` when raising.
    """
    calls: list[TxCallInfo] = []
    try:
        resume_data, resume_info = client.parse_resume(pdf_bytes)
        calls.append(resume_info)
        job_data, job_info = client.parse_job(job_text)
        calls.append(job_info)
        payload, score_info = client.score_to_job(job_data, resume_data)
        calls.append(score_info)
    except TxApiError as exc:
        if exc.call_info is not None and all(c.endpoint != exc.call_info.endpoint for c in calls):
            calls.append(exc.call_info)
        raise ScoreRunError(str(exc), calls=calls, status_code=exc.status_code) from exc
    return map_bimetric_response(payload, calls=calls)


class ScoreRunError(Exception):
    """Scoring pipeline failed after zero or more billed Tx calls."""

    def __init__(
        self,
        message: str,
        *,
        calls: list[TxCallInfo],
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.calls = list(calls)
        self.status_code = status_code
        self.credits_used = sum(c.transaction_cost for c in calls)
        remaining = None
        for call in reversed(calls):
            if call.credits_remaining is not None:
                remaining = call.credits_remaining
                break
        self.credits_remaining = remaining
