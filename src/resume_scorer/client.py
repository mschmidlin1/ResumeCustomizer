"""HTTP client for Textkernel Tx Platform v10 parse and bimetric score APIs."""

from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from typing import Any

import httpx

from resume_lib.secrets_config import TextkernelSecrets
from resume_scorer import settings as scorer_settings
from resume_scorer.mapping import call_info_from_response
from resume_scorer.models import TxCallInfo

_DATA_CENTER_BASE = {
    "US": "https://api.us.textkernel.com/tx/v10",
    "EU": "https://api.eu.textkernel.com/tx/v10",
    "AU": "https://api.au.textkernel.com/tx/v10",
}

_SUCCESS_CODES = frozenset(
    {
        "Success",
        "WarningsFoundDuringParsing",
        "PossibleTruncationFromTimeout",
        "SomeErrors",
    }
)


class TxApiError(Exception):
    """A Tx Platform request failed or returned an unsuccessful ``Info.Code``."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        call_info: TxCallInfo | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.call_info = call_info


class TxClient:
    """Thin REST wrapper for parse-resume, parse-job, and bimetric score-to-job."""

    def __init__(
        self,
        account_id: str,
        service_key: str,
        data_center: str = "US",
        *,
        normalize_skills: bool = True,
        normalize_job_titles: bool = False,
        timeout: float = 120.0,
        http: httpx.Client | None = None,
    ) -> None:
        dc = (data_center or "US").strip().upper()
        if dc not in _DATA_CENTER_BASE:
            dc = "US"
        self._base = _DATA_CENTER_BASE[dc]
        self._account_id = account_id
        self._service_key = service_key
        self._normalize_skills = normalize_skills
        self._normalize_job_titles = normalize_job_titles
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=timeout)

    @classmethod
    def from_secrets(cls, secrets: TextkernelSecrets, *, http: httpx.Client | None = None) -> TxClient:
        return cls(
            secrets["account_id"],
            secrets["service_key"],
            scorer_settings.DATA_CENTER,
            normalize_skills=scorer_settings.NORMALIZE_SKILLS,
            normalize_job_titles=scorer_settings.NORMALIZE_JOB_TITLES,
            http=http,
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> TxClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Tx-AccountId": self._account_id,
            "Tx-ServiceKey": self._service_key,
        }

    def _parse_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        # New Tx accounts default to V2 skills. Bimetric scoring rejects those
        # parses unless SkillsSettings.Normalize is true.
        if self._normalize_skills:
            options["SkillsSettings"] = {"Normalize": True, "TaxonomyVersion": "V2"}
        if self._normalize_job_titles:
            options["ProfessionsSettings"] = {"Normalize": True}
        return options

    def _post(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], TxCallInfo]:
        url = f"{self._base}{path}"
        try:
            response = self._http.post(url, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            raise TxApiError(f"Textkernel request failed: {exc}") from exc

        body: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                body = parsed
        except ValueError:
            body = {}

        info = call_info_from_response(body, endpoint=path)
        if response.status_code == 401:
            raise TxApiError(
                "Textkernel authentication failed. Check Tx-AccountId, Tx-ServiceKey, and data center.",
                status_code=401,
                call_info=info,
            )
        if response.status_code >= 400:
            message = _error_message(body) or f"Textkernel HTTP {response.status_code}"
            raise TxApiError(message, status_code=response.status_code, call_info=info)

        code = info.code or ""
        if code and code not in _SUCCESS_CODES:
            raise TxApiError(
                _error_message(body) or f"Textkernel error: {code}",
                status_code=response.status_code,
                call_info=info,
            )
        return body, info

    def parse_resume(self, pdf_bytes: bytes, *, last_modified: date | None = None) -> tuple[dict[str, Any], TxCallInfo]:
        """POST /parser/resume. Returns ``ResumeData`` and call credits."""
        if not pdf_bytes:
            raise TxApiError("Resume PDF is empty.")
        modified = last_modified or datetime.now(timezone.utc).date()
        payload: dict[str, Any] = {
            "DocumentAsBase64String": base64.b64encode(pdf_bytes).decode("ascii"),
            "DocumentLastModified": modified.isoformat(),
        }
        payload.update(self._parse_options())
        body, info = self._post("/parser/resume", payload)
        resume_data = (body.get("Value") or {}).get("ResumeData") if isinstance(body.get("Value"), dict) else None
        if not isinstance(resume_data, dict):
            raise TxApiError("Resume parse did not return ResumeData.", call_info=info)
        return resume_data, info

    def parse_job(self, job_text: str) -> tuple[dict[str, Any], TxCallInfo]:
        """POST /parser/joborder with pasted text encoded as a UTF-8 .txt."""
        text = (job_text or "").strip()
        if not text:
            raise TxApiError("Job description is empty.")
        payload: dict[str, Any] = {
            "DocumentAsBase64String": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        }
        payload.update(self._parse_options())
        body, info = self._post("/parser/joborder", payload)
        job_data = (body.get("Value") or {}).get("JobData") if isinstance(body.get("Value"), dict) else None
        if not isinstance(job_data, dict):
            raise TxApiError("Job parse did not return JobData.", call_info=info)
        return job_data, info

    def score_to_job(
        self,
        job_data: dict[str, Any],
        resume_data: dict[str, Any],
    ) -> tuple[dict[str, Any], TxCallInfo]:
        """POST /scorer/bimetric/joborder with parsed job as source and resume as target."""
        payload = {
            "SourceJob": {"Id": "job", "JobData": job_data},
            "TargetResumes": [{"Id": "resume", "ResumeData": resume_data}],
        }
        body, info = self._post("/scorer/bimetric/joborder", payload)
        return body, info


def _error_message(body: dict[str, Any]) -> str:
    info = body.get("Info") if isinstance(body, dict) else None
    if not isinstance(info, dict):
        return ""
    message = info.get("Message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    if isinstance(message, list):
        parts = [str(part).strip() for part in message if str(part).strip()]
        if parts:
            return " ".join(parts)
    code = info.get("Code")
    if code:
        return str(code)
    return ""
