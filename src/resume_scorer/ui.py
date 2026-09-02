"""Streamlit Score tab: PDF + job description in, bimetric results out."""

from __future__ import annotations

import streamlit as st

from resume_lib.secrets_config import get_textkernel_secrets
from resume_scorer.client import TxClient
from resume_scorer.ledger import ScorerLedgerMongoService
from resume_scorer.models import ScoreResult
from resume_scorer.scoring import ScoreRunError, score_resume_against_job


def render_score_tab(ledger: ScorerLedgerMongoService) -> None:
    """PDF uploader, job description, Run, and mapped score display."""
    st.title("Score resume")
    st.write(
        "Upload a PDF resume and paste a job description. The app parses both with "
        "Textkernel and scores how well the resume fits the job."
    )

    uploaded = st.file_uploader(
        "Resume (PDF)",
        type=["pdf"],
        key="score_resume_pdf",
        help="One PDF resume to score against the job.",
    )
    job_text = st.text_area(
        "Job description",
        height=220,
        placeholder="Paste the job posting here…",
        key="score_job_description",
    )
    run_clicked = st.button("Run", type="primary", key="score_run")

    if run_clicked:
        st.session_state.last_score_result = None
        secrets = get_textkernel_secrets()
        if secrets is None:
            st.error(
                "Textkernel is not configured. Set `[textkernel]` `account_id` and "
                "`service_key` in `.streamlit/secrets.toml`."
            )
        elif uploaded is None:
            st.warning("Please upload a PDF resume.")
        elif not (job_text or "").strip():
            st.warning("Please paste a job description.")
        else:
            _run_score(uploaded.getvalue(), job_text.strip(), secrets, ledger)

    last: ScoreResult | None = st.session_state.get("last_score_result")
    if last is not None:
        render_score_result(last)


def _run_score(pdf_bytes: bytes, job_text: str, secrets, ledger: ScorerLedgerMongoService) -> None:
    client = TxClient.from_secrets(secrets)
    try:
        with st.spinner("Calculating..."):
            result = score_resume_against_job(client, pdf_bytes, job_text)
    except ScoreRunError as exc:
        if exc.credits_used > 0 or exc.calls:
            ledger.add_run(
                credits_used=exc.credits_used,
                credits_remaining=exc.credits_remaining,
                transaction_ids=[c.transaction_id for c in exc.calls if c.transaction_id],
                calls=exc.calls,
                succeeded=False,
                error=str(exc),
            )
        st.error(str(exc))
        return
    finally:
        client.close()

    ledger.add_score_result(result)
    st.session_state.last_score_result = result


def render_score_result(result: ScoreResult) -> None:
    """Overall bar, category bars, skills checks, education, credits caption."""
    st.subheader("Overall match")
    st.metric("SovScore", f"{result.overall_score}")
    st.progress(_bar_value(result.overall_score))
    parts: list[str] = []
    if result.weighted_score is not None:
        parts.append(f"Resume → job (weighted): {result.weighted_score}")
    if result.reverse_score is not None:
        parts.append(f"Job → resume (reverse): {result.reverse_score}")
    if parts:
        st.caption(" · ".join(parts) + ". Reverse is lower when the role is a step down from the resume.")

    if result.categories:
        st.subheader("Category scores")
        for category in result.categories:
            st.markdown(f"**{category.label}** — {int(round(category.score))}")
            st.progress(_bar_value(category.score))

    st.subheader("Skills")
    col_ok, col_miss = st.columns(2)
    with col_ok:
        st.markdown("**Matched**")
        if result.matched_skills:
            for name in result.matched_skills:
                st.markdown(f"- {name} :white_check_mark:")
        else:
            st.caption("None listed.")
    with col_miss:
        st.markdown("**Missing**")
        if result.missing_skills:
            for name in result.missing_skills:
                st.markdown(f"- {name} :x:")
        else:
            st.caption("None listed.")

    if result.education is not None:
        st.subheader("Education")
        edu = result.education
        if edu.expected:
            st.write(f"Expected: {edu.expected}")
        if edu.actual:
            st.write(f"On resume: {edu.actual}")
        if edu.comparison:
            met = edu.comparison != "DoesNotMeetExpected"
            mark = ":white_check_mark:" if met else ":x:"
            st.markdown(f"{mark} {edu.comparison}")

    credits = result.credits_used
    remaining = result.credits_remaining
    credit_line = f"Credits this run: {credits:g}"
    if remaining is not None:
        credit_line += f" · Textkernel remaining: {remaining:g}"
    st.caption(credit_line)


def _bar_value(score: float) -> float:
    return max(0.0, min(1.0, float(score) / 100.0))
