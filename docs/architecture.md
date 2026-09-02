# Architecture

Resume Customizer is a **Streamlit** app (not a REST API) with two signed-in tabs: **Customize** and **Score**. Implemented resume sources for Customize are **LaTeX (`.tex`)** and **Google Docs**. Word (`.docx`) is planned only — see [worddocs_plan.md](worddocs_plan.md). The Google Docs plan ([gdocs_plan.md](gdocs_plan.md)) is **historical** (the feature has shipped). Textkernel scoring setup is in [textkernel.md](textkernel.md).

## Flow

```text
src/app.py
  Customize tab
    → editors/dispatch.py (resolve .tex upload vs Drive Doc)
    → editors/latex.py | editors/google.py
         → prompts.py (shared editorial policy + format prefixes)
         → claude_service.py (Messages API via complete_json)
         → page_budget.py (optional condense when over page count)
         → tex_workspace.py (pdfLaTeX)  |  google_pipeline.py + google_* (Drive/Docs)
    → cost_ledger_mongo.py (Anthropic spend; MongoDB database resume_customizer)
  Score tab
    → resume_scorer/ui.py
    → resume_scorer/scoring.py
         → client.py POST /v10/parser/resume
         → client.py POST /v10/parser/joborder
         → client.py POST /v10/scorer/bimetric/joborder
    → resume_scorer/ledger.py (Textkernel credits; MongoDB database resume_scorer)
```

| Area | Modules |
|------|---------|
| UI / auth | `src/app.py`, `resume_lib/browser_auth.py`, `resume_lib/auth_cookies.py` |
| Secrets | `resume_lib/secrets_config.py` |
| Editor plugins | `editors/base.py`, `registry.py`, `dispatch.py`, `latex.py`, `google.py` |
| Shared editing policy | `prompts.py`, `page_budget.py` |
| Claude | `claude_service.py`, `parsing.py`, `pricing.py` |
| LaTeX | `tex_workspace.py`, `pdf_pages.py` |
| Google | `google_auth.py`, `google_docs_ops.py`, `google_workspace.py`, `google_pipeline.py` |
| Anthropic ledger | `cost_ledger_mongo.py` (live); `cost_ledger.py` JSON helpers are import/migration-only |
| Scoring | `src/resume_scorer/` (`client.py`, `mapping.py`, `scoring.py`, `ledger.py`, `ui.py`) |

## Package façade

`resume_customizer/__init__.py` re-exports a subset of LaTeX/Claude helpers for convenience. It does **not** export the editor plugins or Google APIs — import those from their modules (or `resume_customizer.editors`). Shared auth/secrets live in `resume_lib`. Scoring lives in `resume_scorer`.
