# Architecture

Resume Customizer is a **Streamlit** app (not a REST API). Implemented resume sources are **LaTeX (`.tex`)** and **Google Docs**. Word (`.docx`) is planned only — see [worddocs_plan.md](worddocs_plan.md). The Google Docs plan ([gdocs_plan.md](gdocs_plan.md)) is **historical** (the feature has shipped).

## Flow

```text
src/app.py
  → editors/dispatch.py (resolve .tex upload vs Drive Doc)
  → editors/latex.py | editors/google.py
       → prompts.py (shared editorial policy + format prefixes)
       → claude_service.py (Messages API via complete_json)
       → page_budget.py (optional condense when over page count)
       → tex_workspace.py (pdfLaTeX)  |  google_pipeline.py + google_* (Drive/Docs)
  → cost_ledger_mongo.py (spend ledger; MongoDB required at runtime)
```

| Area | Modules |
|------|---------|
| UI / auth | `src/app.py`, `browser_auth.py`, `auth_cookies.py` |
| Editor plugins | `editors/base.py`, `registry.py`, `dispatch.py`, `latex.py`, `google.py` |
| Shared editing policy | `prompts.py`, `page_budget.py` |
| Claude | `claude_service.py`, `parsing.py`, `pricing.py` |
| LaTeX | `tex_workspace.py`, `pdf_pages.py` |
| Google | `google_auth.py`, `google_docs_ops.py`, `google_workspace.py`, `google_pipeline.py` |
| Ledger | `cost_ledger_mongo.py` (live); `cost_ledger.py` JSON helpers are import/migration-only |

## Package façade

`resume_customizer/__init__.py` re-exports a subset of LaTeX/Claude helpers for convenience. It does **not** export the editor plugins or Google APIs — import those from their modules (or `resume_customizer.editors`).
