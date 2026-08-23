# Code review — 2026-08-23

## Scope

Application source under `src/` (`app.py`, `resume_customizer/` package including `editors/`), plus how it relates to package docs in `README.md` and `docs/`. Tests, vendored deps, `.venv`, and Kubernetes/Docker config were used only for context, not as primary review targets.

## Summary

ResumeCustomizer is a well-factored Streamlit app with a clear editor-plugin boundary (`ResumeEditor` protocol, registry, dispatch), solid typed dataclasses, and thoughtful helpers for filenames, parsing, cookies, and pricing. The main improvement themes are **parallel LaTeX vs Google customize→condense pipelines** (and near-duplicate prompts), **overlapping usage/ledger types**, and **tightening long run methods / shared constants** so the next format (e.g. Word) does not copy-paste another 300-line path. Documentation is strong at the README/ops layer but light on package architecture for new contributors.

## Findings

### Code structure and duplication

- **[Severity: high]** Customize → measure pages → optional condense is implemented twice with nearly the same control flow in `LatexEditor.run` (`editors/latex.py`) and `run_google_customization` (`google_pipeline.py`).
  - Why it matters: Bug fixes and UX changes (warning wording, cost attribution, condense failure handling) must be applied in two places; drift is already visible (Google’s condense path catches a broad `Exception`; LaTeX’s does not).
  - Suggestion: Extract a small shared “page budget loop” (or strategy hooks: measure / apply / remeasure) that both editors call, keeping format-specific I/O in `TexCompiler` vs Drive/Docs helpers.

- **[Severity: high]** Editorial prompt text for “Truth and emphasis” (and much of the operational rules) is duplicated between `DEFAULT_PROMPT` in `editors/latex.py` and `GOOGLE_SYSTEM_PROMPT` in `google_pipeline.py`.
  - Why it matters: Policy edits will diverge; Google already ignores the sidebar `settings.system_prompt` and hard-codes `GOOGLE_SYSTEM_PROMPT`, so shared product rules live in two constants.
  - Suggestion: Move shared resume-editing policy into one module (e.g. `prompts.py`) with format-specific suffixes (LaTeX JSON keys vs block replacements). Document that the sidebar prompt applies only to LaTeX, or wire Google to honor `RunSettings.system_prompt` if that is intended.

- **[Severity: medium]** `CustomizationUsage` (`claude_service.py`) and `LedgerUsage` (`editors/base.py`) are structurally identical; LaTeX converts with `_usage_to_ledger(usage: object)` while Google uses typed `_ledger(usage: CustomizationUsage)`.
  - Why it matters: Two types and two converters increase noise for no behavioral gain.
  - Suggestion: Use one frozen usage dataclass (or alias) end-to-end, or give `_usage_to_ledger` a `CustomizationUsage` parameter and share one converter.

- **[Severity: medium]** Google Doc MIME string is defined as `GOOGLE_DOC_MIME` in `google_docs_ops.py` and again as `_GOOGLE_DOC_MIME` in `editors/dispatch.py` (picker HTML hard-codes the same value too).
  - Why it matters: Easy to update one site and leave another inconsistent.
  - Suggestion: Import `GOOGLE_DOC_MIME` from `google_docs_ops` (or a tiny `constants` module) in `dispatch.py`; keep the HTML string in sync via a comment or build step if needed.

- **[Severity: low]** Streamlit secrets reading is repeated with the same try/except pattern in `app.py` (`_get_expected_password`, `_get_anthropic_api_key`), `browser_auth.signing_secret`, and `editors/google._google_secrets`.
  - Why it matters: Minor duplication and inconsistent null-handling details.
  - Suggestion: One `secrets` helper module returning typed optional config blocks.

### Readability and simpler syntax

- **[Severity: medium]** `LatexEditor.run` (~190 lines) and `run_google_customization` (~200 lines) nest many try/except/else branches for compile, customize, condense, and re-export.
  - Why it matters: Hard to scan, hard to unit-test mid-steps in isolation, and easy to miss resetting fields like `compile_failed` / `condense_succeeded`.
  - Suggestion: Split into named helpers (`_measure_source`, `_first_pass`, `_condense_if_needed`, `_build_result`) that each return a small result object or update a mutable run-context dataclass.

- **[Severity: medium]** `render_main` in `app.py` nests source resolution, editor lookup, and run/persist inside deep `try`/`else`/`except` chains.
  - Why it matters: The happy path is indented several levels; early-return style would match the clearer patterns already used in `render_public_home`.
  - Suggestion: Prefer early `return` / continue-after-error after each guard (`api_key`, job text, `resolve_resume_source`, `get_editor`) instead of nested `else` blocks.

- **[Severity: low]** `_create_message` in `claude_service.py` uses `inspect.signature` to reshuffle kwargs into `extra_body` for SDK version differences.
  - Why it matters: Correct and useful, but dense for readers unfamiliar with Anthropic SDK churn.
  - Suggestion: Keep the shim; optionally pin a supported SDK major in `requirements.txt` and document “why this exists” in a one-line module comment near the top (already partly documented on the function).

- **[Severity: low]** No significant broader readability issues: modern `from __future__ import annotations`, frozen/`slots` dataclasses, and keyword-only args are used consistently and help clarity.

### Variable names

- **[Severity: medium]** In `GoogleEditor.run`, the pipeline result is bound as `piped`, which does not say what it holds.
  - Why it matters: Obscures the type (`GooglePipelineResult`) at the call site.
  - Suggestion: Rename to `pipeline_result` or `google_result`.

- **[Severity: medium]** Page-count locals mix `out_pages`, `out_pages_final`, `output_pages`, and `source_pages` across LaTeX and Google paths.
  - Why it matters: Same concept, different names, makes cross-editor reading harder.
  - Suggestion: Standardize on `source_pages` / `output_pages` everywhere (including intermediate reassignments).

- **[Severity: low]** Locals `_mongo` and `_total_spend` in `render_sidebar` use a leading underscore usually reserved for “private” module/class members.
  - Why it matters: Mild style inconsistency with the rest of the app.
  - Suggestion: Prefer `ledger` / `total_spend` for function locals.

- **[Severity: low]** Registry parameter `kind` (`get_editor(kind)`) vs field `editor_id` on `SourceHandle` / `EditorRunResult`.
  - Why it matters: Same idea, two names.
  - Suggestion: Rename the parameter to `editor_id` for consistency.

### Language best practices

- **[Severity: medium]** Broad `except Exception` appears in UI/auth paths (`app.py` secrets, `editors/google.py` OAuth/token refresh, `browser_auth.restore_from_cookies` with bare `pass`).
  - Why it matters: Appropriate for Streamlit secrets quirks in some cases, but silent failures (especially cookie restore) hide misconfiguration.
  - Suggestion: Catch the narrowest practical exceptions; at least log or surface a caption when Google token restore fails instead of `pass`.

- **[Severity: medium]** Dual Claude call styles: LaTeX uses `customize` / `condense_resume_to_page_budget` (prompt-enforced JSON); Google uses `complete_json` with `REPLACEMENT_JSON_SCHEMA` and a 400 fallback.
  - Why it matters: Two maintenance surfaces for the same “call model → parse JSON → usage” concern; LaTeX does not benefit from schema constraints.
  - Suggestion: Route LaTeX through `complete_json` + a LaTeX JSON schema (mirroring `REPLACEMENT_JSON_SCHEMA`), or document why LaTeX must stay on the dedicated methods.

- **[Severity: medium]** `resolve_resume_source` accepts `.docx` and `get_editor("docx")` raises `EditorNotImplementedError`, while the uploader in `app.py` only allows `type=["tex"]`.
  - Why it matters: Dead/half-wired Word path increases cognitive load and can confuse future UI work (`docs/worddocs_plan.md` vs current behavior).
  - Suggestion: Either remove `.docx` from dispatch until implemented, or add a stub editor module and align the uploader with the plan.

- **[Severity: low]** `dispatch.resolve_resume_source` uses `assert google_file is not None` for type narrowing and annotates `google_credentials: dict | None` without value types.
  - Why it matters: `assert` can be stripped with `-O`; untyped dicts hide credential shape.
  - Suggestion: Use an explicit `if google_file is None: raise ...` (or early structure) and `Mapping[str, Any]` / a TypedDict for credentials.

- **[Severity: low]** `cost_ledger.append_entry` / full JSON write path is unused by the live app (Mongo via `CostLedgerMongoService`); JSON remains for import CLI only.
  - Why it matters: Fine historically, but `append_entry` looks like a second persistence strategy.
  - Suggestion: Mark JSON helpers as import/migration-only in the module docstring, or move them next to `import_ledger_to_mongo.py`.

### File and folder organization

- **[Severity: medium]** Google functionality is split across many top-level modules (`google_auth`, `google_docs_ops`, `google_workspace`, `google_pipeline`) plus `editors/google.py` and `editors/google_picker.py`.
  - Why it matters: The split is mostly sensible (auth vs Docs JSON vs Drive I/O vs pipeline vs Streamlit), but the flat package root is crowded and `RESUME_CUSTOMIZER_FOLDER` lives in `google_docs_ops` while used by `google_workspace`.
  - Suggestion: Optional `resume_customizer/google/` subpackage (`auth.py`, `docs_ops.py`, `workspace.py`, `pipeline.py`) with editors remaining thin Streamlit adapters; keep constants with the Drive layer.

- **[Severity: medium]** CLI `import_ledger_to_mongo.py` lives inside the installable package rather than `scripts/`.
  - Why it matters: Mixes library code with a one-off migration tool; `scripts/` already exists for ops helpers.
  - Suggestion: Move the CLI under `scripts/` (thin wrapper importing package APIs) or expose it as a `python -m` entry clearly documented in the README.

- **[Severity: low]** Editor plugin layout (`editors/base.py`, `registry.py`, `dispatch.py`, `latex.py`, `google.py`) is clear and is a strength of the project—keep extending that pattern for new formats instead of more root-level modules.

### Documentation

- **[Severity: medium]** README covers setup, Docker, Mongo, and tests well, but there is no short architecture map (entrypoint → editors → Claude → ledger).
  - Why it matters: New contributors must reverse-engineer `app.py` + `editors/` + dual Google modules to make a small change.
  - Suggestion: Add a brief “Architecture” section (or `docs/architecture.md`) listing: `src/app.py`, `editors/*`, `claude_service` / `parsing`, `tex_workspace`, `google_*`, Mongo ledger.

- **[Severity: medium]** Planning docs (`docs/gdocs_plan.md`, `docs/worddocs_plan.md`) sit beside shipped Google Docs support and an unimplemented Word path without a clear “done / not done” status in the README.
  - Why it matters: Plans can be mistaken for current behavior.
  - Suggestion: Mark plans as historical or “next,” and point README “Notes” at implemented formats only (LaTeX + Google Docs).

- **[Severity: low]** Public module and many function docstrings are consistently good (`claude_service`, `parsing`, `filenames`, `tex_workspace`). A few hot helpers (`signing_secret`, `_google_client_secret`) have none—acceptable if private, but `signing_secret` is imported across modules.
  - Why it matters: Slight inconsistency for cross-module APIs.
  - Suggestion: Add one-liner docstrings on exported helpers in `browser_auth.py`.

- **[Severity: low]** Package `__init__.py` re-exports LaTeX/Claude helpers but not editors or Google APIs—fine if intentional; note that in the architecture doc so people do not assume the package façade is complete.

## Suggested next steps

1. Extract a shared page-budget / condense control flow and a shared editorial prompt fragment used by both LaTeX and Google.
2. Collapse `CustomizationUsage` / `LedgerUsage` (and their converters) into one type; type `_usage_to_ledger` properly.
3. Break `LatexEditor.run` and `run_google_customization` into named helpers; flatten `render_main` with early returns.
4. Align or quarantine the `.docx` path; decide whether Google should honor `RunSettings.system_prompt`.
5. Add a short architecture note to README/`docs/` and clarify status of `gdocs_plan` / `worddocs_plan`.
