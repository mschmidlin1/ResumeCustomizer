# Code review — 2026-08-23

## Scope

Full application source under `src/` (`app.py`, `resume_customizer/` including `editors/`, HTML component frontends). Tests, Docker/Kubernetes config, and docs were used for context. This review reflects the codebase after recent refactors (`page_budget.py`, `prompts.py`, `secrets_config.py`, helper-split pipelines).

## Summary

ResumeCustomizer is in strong shape: a clear editor-plugin boundary, shared page-budget and prompt modules, typed dataclasses, and thoughtful cookie/OAuth handling. The biggest remaining themes are **parallel result/run-context types** between LaTeX and Google paths, **`GoogleEditor.render_source_controls` as a large UI monolith**, and **hard MongoDB coupling** that can break the sidebar or run path without a friendly error. Security is reasonable for a small password-gated deploy, but the shared-password + cookie-signing model and lack of run rate limits deserve conscious acceptance or hardening.

## Findings

### Code structure and duplication

- **[Severity: medium]** `GooglePipelineResult` (`google_pipeline.py`) and `EditorRunResult` (`editors/base.py`) carry nearly the same fields; `GoogleEditor.run` manually maps between them field-by-field.
  - Why it matters: Adding a field (e.g. a new artifact or metric) requires edits in three places and is easy to miss.
  - Suggestion: Have `run_google_customization` return `EditorRunResult` directly, or add `GooglePipelineResult.to_editor_result(editor_id="google")` (and use it in `GoogleEditor.run`).

- **[Severity: medium]** `_LatexRunContext` (`editors/latex.py`) and `_GoogleRunContext` (`google_pipeline.py`) mirror each other (captions, warnings, errors, usages, pages, condense flag).
  - Why it matters: The customize → measure → condense flow is already shared via `enforce_page_budget`, but run-state accumulation is still duplicated; a third editor (Word) would copy the pattern again.
  - Suggestion: Introduce a small mutable `EditorRunContext` dataclass in `editors/base.py` or `page_budget.py` with shared list fields and a single `_build_editor_result(ctx, editor_id, **extras)` helper.

- **[Severity: low]** User-message header construction is split three ways: `_build_user_message` / `_build_condense_user_message` (`claude_service.py`) and `_blocks_user_message` (`google_pipeline.py`).
  - Why it matters: Page-count keys (`SOURCE_PDF_PAGE_COUNT`, `TARGET_PDF_PAGE_COUNT`, etc.) and delimiter style could drift.
  - Suggestion: One helper that formats optional page-count lines + `JOB_DESCRIPTION` + body label (`RESUME_LATEX`, `RESUME_BLOCKS`, `CUSTOMIZED_LATEX`).

- **[Severity: low]** No significant issues in the editor registry/dispatch layer; `LedgerUsage = CustomizationUsage`, centralized `GOOGLE_DOC_MIME`, and shared `enforce_page_budget` are good consolidations.

### Readability and simpler syntax

- **[Severity: medium]** `GoogleEditor.render_source_controls` (~80 lines) interleaves secrets checks, OAuth callback handling, PKCE handshake setup, token refresh, disconnect, picker wiring, and selected-file caption in one method.
  - Why it matters: OAuth regressions are hard to spot; the happy path for “already connected” is buried below handshake logic.
  - Suggestion: Extract `_ensure_google_oauth(secrets) -> dict | None`, `_handle_oauth_callback`, and `_render_picker(token_dict, secrets)` helpers (same file or `google_oauth_ui.py`).

- **[Severity: low]** `condense_succeeded` on `EditorRunResult` is set from `result.usage is not None` in `page_budget.enforce_page_budget`, meaning “a condense API call ran,” not “pages now fit.”
  - Why it matters: Readers (and `_show_run_cost` in `app.py`) may read the name as “condense fixed the budget.”
  - Suggestion: Rename to `condense_attempted` or document the semantics on `EditorRunResult` and in `PageBudgetOutcome`.

- **[Severity: low]** `_create_message` in `claude_service.py` remains dense but is well-commented; no change required unless you pin a single Anthropic SDK major and drop the shim.

### Variable names

- **[Severity: low]** `drive: object` and `docs: object` in `google_pipeline.py` and `GoogleEditor.run` hide the Google API resource types.
  - Why it matters: IDE assistance and refactors suffer; “object” does not convey Drive vs Docs clients.
  - Suggestion: Use `typing.Any` with a one-line comment, or a minimal `Protocol` with the methods you call (`export`, `files`, `documents`).

- **[Severity: low]** `info` vs `info_messages` on run contexts vs result dataclasses is a minor inconsistency when reading LaTeX vs Google code side by side.
  - Suggestion: Align context field names with `EditorRunResult` (`info_messages` everywhere).

### Language best practices

- **[Severity: medium]** `app.py` reads `os.environ["MONGODB_URI"]` in `_ledger_mongo_service()` with no guard; a missing env var raises `KeyError` on every authenticated page load (sidebar metric) and after each run when persisting usage.
  - Why it matters: Local dev or misconfigured deploy fails loudly with a stack trace instead of a user-facing caption.
  - Suggestion: Wrap ledger access in a small helper that catches connection/config errors and shows `st.warning("Cost ledger unavailable (MONGODB_URI).")` while still allowing customization.

- **[Severity: low]** Broad `except Exception` remains in OAuth/token paths (`editors/google.py`, `browser_auth.restore_from_cookies`). Cookie restore now surfaces a caption on failure, which is an improvement; Google token refresh still silently clears session via `clear_google_session()` without user feedback.
  - Suggestion: Add a one-line `st.caption` when refresh fails, mirroring `browser_auth`.

- **[Severity: low]** `find_or_create_folder` builds a Drive query with an f-string (`google_workspace.py`). `name` defaults to a constant today; if it ever becomes user input, quote/escape Drive query syntax.
  - Suggestion: Keep folder name as a module constant only, or add escaping if parameterized.

### File and folder organization

- **[Severity: medium]** `app.py` (~370 lines) owns landing page, privacy policy, sidebar settings, main run UI, cost display, and ledger persistence.
  - Why it matters: Streamlit apps often grow here; further features (Word editor, admin views) will inflate a single file.
  - Suggestion: Move `render_public_home`, `render_privacy_policy`, `render_sidebar`, and `_show_run_cost` into `resume_customizer/ui/` (or `streamlit_pages/`) modules; keep `app.py` as routing + session init.

- **[Severity: low]** Google modules remain flat at package root (`google_auth`, `google_docs_ops`, `google_workspace`, `google_pipeline`) while `editors/google.py` is the Streamlit adapter. The split is workable; a `resume_customizer/google/` subpackage would reduce root clutter when Word lands.
  - Suggestion: Optional namespace move when adding `docx.py`; not urgent.

- **[Severity: low]** `import_ledger_to_mongo` correctly documents the `scripts/` wrapper; keeping the module in-package is acceptable for `python -m` use.

### UI components

- **[Severity: medium]** Google OAuth + Picker UI logic lives entirely inside `GoogleEditor.render_source_controls` rather than reusable Streamlit helpers or components (contrast with extracted `google_doc_picker` and `rc_cookie_bridge` HTML components).
  - Why it matters: Connect/disconnect/caption patterns are not reusable; testing OAuth edge cases requires mocking all of Streamlit inside the editor class.
  - Suggestion: Extract `render_google_drive_column(secrets) -> SourceHandle | None` (or split connect vs picker) under `editors/google_ui.py`; keep `GoogleEditor` as a thin `ResumeEditor` wrapper.

- **[Severity: low]** LaTeX upload UI correctly stays in `app.py` with `LatexEditor.render_source_controls` returning `None`; the two-column layout is clear. Download buttons in `LatexEditor.render_outputs` and `GoogleEditor.render_outputs` are appropriately editor-specific.

- **[Severity: low]** Static HTML frontends (`cookie_bridge_frontend`, `google_picker_frontend`) are small and focused; `postMessage(..., "*")` matches Streamlit component conventions.

### Documentation

- **[Severity: low]** `docs/architecture.md` and README cross-links clearly describe implemented vs planned formats (LaTeX + Google Docs; Word not shipped). Good improvement over earlier state.
  - Suggestion: Add one sentence in `architecture.md` that MongoDB is required at runtime for the spend sidebar (not optional).

- **[Severity: low]** `prompts.py` module docstring explains sidebar vs format prefixes well; `compose_*_system_prompt` behavior is clear for contributors editing editorial policy.

- **[Severity: low]** `resume_customizer/__init__.py` re-exports LaTeX/Claude helpers only; `architecture.md` already notes editors are imported separately — no gap.

### Security

- **[Severity: medium]** Authentication is a single shared app password (`[auth].password`); the same secret signs login and Google OAuth cookies (`auth_cookies.sign_payload` / `signing_secret()`).
  - Why it matters: Appropriate for a small private tool, but anyone who knows the password can forge valid `rc_auth` and `rc_google` cookies for that deployment. Cookie payloads include Google refresh tokens.
  - Suggestion: Document this threat model in deployment docs; consider a dedicated `cookie_signing_key` in secrets separate from the login password if the app password is ever shared broadly.

- **[Severity: medium]** No rate limiting or per-session cap on **Run** (Anthropic API calls). A signed-in user can trigger unbounded spend.
  - Why it matters: Deployed on Kubernetes with a real API key; one compromised password enables cost abuse.
  - Suggestion: Optional daily run limit in MongoDB, Streamlit session counter, or reverse-proxy rate limit for `/`.

- **[Severity: low]** Google OAuth uses PKCE, signed state, and excludes `client_secret` from browser cookies — solid choices. `verify_google_cookie` rejects payloads that still contain `client_secret`.

- **[Severity: low]** Resume and job text are sent to Anthropic; privacy policy covers this. No obvious injection sinks (no shell/SQL from user text).

- **[Severity: low]** Secrets stay in mounted `secrets.toml` / K8s secrets; example file uses placeholders. Ensure production `secrets.toml` is never committed (already gitignored).

## Suggested next steps

1. Unify `GooglePipelineResult` with `EditorRunResult` (or add a single converter) to remove manual field mapping.
2. Decompose `GoogleEditor.render_source_controls` into testable OAuth/picker helpers.
3. Gracefully handle missing or unreachable MongoDB in `app.py` so customization still works when the ledger is down.
4. Split `app.py` UI sections into a `ui/` package before adding the Word editor.
5. Document (or separate) cookie-signing secret from the shared login password; consider a simple run-rate limit for deployed instances.
