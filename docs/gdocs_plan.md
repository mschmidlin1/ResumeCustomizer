# Google Docs editor — implementation plan (historical)

> **Status: done.** Google Docs Connect + Picker + customize/condense shipped in the app.
> Keep this file for design history. Current architecture: [architecture.md](architecture.md).

This spec adds a **Google Docs** resume source alongside LaTeX. Visitors sign in with the existing shared app password and use the existing Anthropic key. They **Connect Google** with *their* account, pick a Doc from Drive, and get a **new** customized Doc. The original is never overwritten.

Implement this at a different time from the Word editor ([worddocs_plan.md](worddocs_plan.md)). **Whichever editor ships first** extracts today’s LaTeX pipeline into a `LatexEditor` plugin. The second editor only registers itself.

Do **not** convert the Google Doc to `.docx` (or HTML) at any point. Read and write with the Google Docs API so layout stays native. PDF export via the Drive API is **only** for page counting and the PDF download — it is not an edit format.

## Locked decisions

| Topic | Decision |
|-------|----------|
| App auth | Shared Streamlit password (`[auth] password`) |
| Claude | Shared `[anthropic] api_key` |
| Google identity | Per-visitor OAuth; tokens in `st.session_state` only |
| Ingest | **Connect Google** + Drive file picker (not a `.gdoc` upload) |
| Output | Link to a **new** Google Doc, plus PDF download of Drive’s PDF export (same artifacts idea as `.tex` + `.pdf`) |
| Page budget | Same loop as LaTeX: measure original pages → customize → measure copy → condense Claude pass if over |
| Page measurement | Drive API `files.export` with `application/pdf`, then existing `count_pdf_pages` (Docs API has no page field) |
| New Doc location | Folder named `ResumeCustomizer` in the visitor’s Drive (create if missing) |
| Original Doc | Copy, then edit the copy |
| UI | Two columns: **Google Drive** controls \| **file upload** (`.tex` and `.docx`). No source radio. |
| Editor selection | Drive Doc → `GoogleEditor`; `.tex` upload → `LatexEditor`; `.docx` upload → `DocxEditor` |
| OAuth scopes | `drive.file` plus Docs edit (Picker-granted per file, not full Drive) |

LaTeX keeps pdfLaTeX, page-count matching, and `.tex` / `.pdf` downloads **inside** `LatexEditor`. The Google editor mirrors that page loop with **Drive PDF export** (not pdfLaTeX, not `.docx`) and offers an Open-in-Docs link plus that PDF.

## Current code this plan touches

Today everything is LaTeX-specific:

- [`src/app.py`](../src/app.py) — upload `.tex`, Claude, pdfLaTeX, download buttons
- [`src/resume_customizer/claude_service.py`](../src/resume_customizer/claude_service.py) — JSON with `job_title` + `customized_latex`
- [`src/resume_customizer/parsing.py`](../src/resume_customizer/parsing.py) — LaTeX payload only
- [`src/resume_customizer/tex_workspace.py`](../src/resume_customizer/tex_workspace.py) — pdfLaTeX (stays in the LaTeX plugin)

After this work, `app.py` should not import Docs API clients, OAuth helpers, or pdfLaTeX.

---

## Shared editor plugin

This contract is the same as in [worddocs_plan.md](worddocs_plan.md). Implement it once (during whichever editor ships first).

### Package layout

```
src/resume_customizer/editors/
    __init__.py
    base.py          # protocol + EditorRunResult
    latex.py         # today’s behavior
    google.py        # this plan
    registry.py      # get_editor(kind)
```

`editors/docx.py` is added by the Word plan, not this one. Until then the shared uploader should accept `.tex` only (or accept `.docx` and error with “Word editor not implemented yet”). `registry.py` should still accept `"docx"` and fail clearly if that module is missing.

### Protocol

```python
class ResumeEditor(Protocol):
    id: str       # "latex" | "google" | "docx"
    label: str

    def render_source_controls(self) -> SourceHandle | None:
        """Optional Streamlit widgets for this editor. Google uses this (Connect + Picker).
        LaTeX and Word do not; the orchestrator owns the shared file uploader."""

    def run(
        self,
        source: SourceHandle,
        job_text: str,
        claude: ClaudeClient,
        settings: RunSettings,
    ) -> EditorRunResult:
        """Extract text, call Claude, apply edits, return usage + artifacts."""

    def render_outputs(self, result: EditorRunResult) -> None:
        """Downloads or an Open-in-Docs link."""
```

`SourceHandle` is an opaque per-editor object (uploaded bytes + filename, or Drive file id + name + token). `EditorRunResult` always includes `job_title`, cost/usage for the ledger, and editor-specific artifacts (LaTeX string + PDF bytes, or a Google Doc URL plus exported PDF bytes).

### Orchestrator (`app.py`)

Keep: page config, password gate, sidebar (model/prompt/temperature/max tokens, sign out, spend metric), job-description text area, **Run**, cost-ledger writes.

Main source UI is **two columns** (no radio):

| Left column | Right column |
|-------------|--------------|
| Google Drive: Connect / Disconnect / Picker (`GoogleEditor.render_source_controls()`) | Shared `st.file_uploader` with `type=["tex", "docx"]` |

On Run, pick **exactly one** source:

- Drive Doc selected, no upload → `GoogleEditor`
- `.tex` uploaded, no Drive Doc → `LatexEditor`
- `.docx` uploaded, no Drive Doc → `DocxEditor`
- Both columns have a source → warn and do not Run (“Use a Google Doc or an uploaded file, not both”)
- Neither → warn to pick a source

Then `result = editor.run(...)`, persist ledger entries, `editor.render_outputs(result)`.

Do not put Google OAuth, Picker, Docs `batchUpdate`, `python-docx`, or `pdflatex` in `app.py` beyond laying out the columns and dispatching by source. The left column may call into `GoogleEditor` for widgets; token plumbing stays in the Google module.

### Claude helper

Slim [`claude_service.py`](../src/resume_customizer/claude_service.py) to “JSON completion”: `messages.create`, token usage, cost estimate. Keep [`extract_json_object_text`](../src/resume_customizer/parsing.py) as shared fence-stripping.

Each editor supplies:

- Extra system-prompt rules (LaTeX validity vs “do not add/remove blocks”)
- User-message body (full `.tex` vs numbered text blocks)
- Payload parser (`customized_latex` vs `replacements`)

LaTeX’s condense-to-page-budget second call stays **inside** `LatexEditor.run`. The Google editor owns the same two-call pattern **inside** `GoogleEditor.run`, measuring pages via Drive PDF export instead of pdfLaTeX.

### First-ship refactor (if this plan is implemented first)

1. Move the current Run path from `app.py` into `LatexEditor`.
2. Introduce `base.py`, `registry.py`, and the two-column source row (left empty or “Google Docs coming later” until this editor ships; right = current `.tex` uploader, later `.tex`+`.docx`).
3. Point existing tests at `LatexEditor` / the LaTeX payload parser so they still pass.
4. Then add `GoogleEditor` in the left column.

If Word already shipped the plugin, skip 1–3 and only add `google.py` plus registry/UI wiring.

---

## Google Cloud project

Enable:

- Google Drive API
- Google Docs API
- Google Picker API

Create:

1. **OAuth 2.0 Client ID** — type **Web application**
2. **Authorized redirect URIs** — at least:
   - `http://localhost:8501` (local Streamlit)
   - `https://customizer.schmidlin.casa` (production; see [deployment.md](deployment.md))
3. **API key** for the Picker (HTTP referrer restrictions: localhost and the production host)
4. **OAuth consent screen** — external or testing. `drive.file` is non-sensitive; Docs edit may require adding the scope on the consent screen. While the app is in testing, add each visitor as a test user.

`app_id` for the Picker is the numeric prefix of the OAuth client id (the segment before `-`).

When implementing (not in this writing pass), add the production redirect URI notes to [deployment.md](deployment.md). Streamlit reruns make OAuth redirects awkward; use a documented library (`streamlit-oauth` or Authlib) and keep the callback on the same origin as the app.

## Secrets

Extend `.streamlit/secrets.toml.example` (never commit real secrets):

```toml
[google]
client_id = ".....apps.googleusercontent.com"
client_secret = "..."
api_key = "..."          # Picker developer key
app_id = "..."           # numeric prefix of client_id
```

Scopes (exact strings at implement time):

- `https://www.googleapis.com/auth/drive.file` — files the user opens with Picker, plus files **this app creates** (the `ResumeCustomizer` folder and copies)
- Docs scope needed to `documents.get` / `documents.batchUpdate` on those files (use the least-privilege Docs scope that allows edit)

Do **not** request `drive` (full Drive) or `drive.readonly` over the whole corpus.

## Connect Google + Picker

### Connect / Disconnect

In the **left column**:

- If no token: **Connect Google** starts the OAuth flow.
- If connected: show the account email, **Disconnect** (clear token, picked file, and Google run outputs from session), and the picker.

Tokens live only in `st.session_state`. Do not write them to MongoDB, disk, or `secrets.toml`. Shared app password means two people on the same browser profile could see one session; Disconnect and session expiry are the mitigation. Do not persist refresh tokens across processes.

App **Sign out** should also clear Google session state.

### Picker

After Connect, show the official Google Picker in the **left column** (Streamlit custom component or equivalent HTML component).

Requirements:

- Filter to Google Docs only: MIME `application/vnd.google-apps.document`
- Single file
- Return **Drive file id**, name, and MIME type into session state

**Do not download or export file bytes in the Picker.** Libraries that turn a Picker result into an `UploadedFile` of `.docx`/PDF bytes are the conversion trap. If a third-party component only yields bytes, do not use it; wrap Picker JS so Python receives the file id.

PDF bytes are fetched later, on Run, with Drive `files.export` on that file id (original, then the copy). That is measurement, not ingest.

Reject Sheets, Slides, and uploaded Word files sitting in Drive. If the user picks a non-Doc, show an error and do not Run.

## Run pipeline

Same control flow as today’s LaTeX Run in [`src/app.py`](../src/app.py): measure source pages → customize → measure result → if over budget, condense → measure again. Swap pdfLaTeX for Drive PDF export.

```
Picker file id
    → Drive files.export original as application/pdf
    → count_pdf_pages (stop if export or count fails, like a source .tex that will not compile)
    → documents.get (native JSON)
    → extract numbered text blocks
    → Claude JSON { job_title, replacements }  (include SOURCE_PDF_PAGE_COUNT)
    → find or create Drive folder "ResumeCustomizer"
    → files.copy original into that folder
    → rename copy from sanitized job_title
    → documents.batchUpdate replacements on the COPY only
    → Drive files.export COPY as application/pdf → count_pdf_pages
    → if copy pages > source pages:
          Claude condense pass (replacements JSON, same rules as LaTeX condense)
          batchUpdate those replacements on the COPY
          export COPY PDF and count again
          if still over: keep this version, warn (same as LaTeX)
    → store webViewLink + last PDF bytes for the UI
```

If the first Claude call succeeds but copy/`batchUpdate` fails, do not touch the original; show the error.

If export of the **copy** fails after a successful edit, still show the Doc link (editable artifact) and explain that page count could not be verified — same idea as LaTeX still offering `.tex` when PDF compile fails.

### Page measurement (Drive PDF export)

The Docs API has **no page-count field**. Use Google Drive:

`GET files.export?fileId={id}&mimeType=application/pdf`

Then reuse [`count_pdf_pages`](../src/resume_customizer/pdf_pages.py) on the bytes.

- Export the **picked original** for the source budget (before any copy edits).
- Export the **copy** after each apply (customize and, if needed, condense).
- Drive export of Google Docs is capped at 10 MB; if that fails, stop the run with a clear error (cannot know the budget).
- Pageless Docs still get a paged PDF (Google’s print layout). That PDF is the page truth for this loop, matching “what File → Download → PDF would produce.”
- Never export as `.docx` for this loop.

Show a caption like LaTeX: `Source resume: N PDF page(s) (measured via Google PDF export).`

### Extract blocks

Walk the Docs document body (and table contents). Assign a stable `block_id` per text-bearing paragraph or table cell (index in document order is enough for one run). Skip empty blocks. Send Claude something like:

```
BLOCK 0: Jane Doe
BLOCK 1: Software engineer
BLOCK 2: • Built an API in Python
...
```

Do not send image/drawing objects as text. Do not flatten the Doc to markdown for rewriting into a new blank document.

### Claude payload

```json
{
  "job_title": "short filename title",
  "replacements": [
    { "block_id": 2, "text": "• Built a payments API in Python" }
  ]
}
```

Rules in the Google editor’s system extras:

- Only reword existing blocks; do not add or delete blocks
- Preserve truthfulness (same rules as today’s LaTeX prompt for claims)
- Prefer weaving job-description terms into existing bullets
- Omit unchanged blocks from `replacements` (or allow identity replacements; applying a no-op is fine)
- Never invent employers, dates, or skills
- Customized result should fit in `SOURCE_PDF_PAGE_COUNT` pages when exported to PDF (same instruction as LaTeX)

Parse errors surface in the UI the same way LaTeX parse errors do today.

### Condense pass

If the copy’s PDF has **more pages** than the original, call Claude again inside `GoogleEditor.run` (do not add a third pass). Mirror [`condense_resume_to_page_budget`](../src/resume_customizer/claude_service.py):

- User message includes `TARGET_PDF_PAGE_COUNT`, `MEASURED_CUSTOMIZED_PDF_PAGE_COUNT`, job description, and the current numbered blocks (after the first apply)
- System extras: shorten by tightening phrasing and merging bullets; do not remove factual claims, employers, dates, degrees, or tools; do not add/delete blocks; do not invent content
- Response shape is still `{ job_title, replacements }`
- Apply replacements to the **same copy** (not a second copy)
- Log the second call on the cost ledger like LaTeX
- If parse or Anthropic fails: keep the first customized copy, warn with measured vs target pages
- If still over after condense: keep that copy, warn to tighten in Google Docs (analog of tightening the `.tex`)

### Copy into `ResumeCustomizer`

1. Search Drive for a folder this app can see named exactly `ResumeCustomizer` that is not trashed (`drive.file` will only see folders the app created or the user picked).
2. If none, `files.create` a folder with that name (Drive root is acceptable as parent).
3. `files.copy` the picked Doc with `parents: [folderId]`.
4. Patch the copy’s name using `safe_filename_base(job_title)` and `with_download_disambiguation` (same helpers as `.tex` downloads).
5. Run all `batchUpdate` calls against the **copy’s** document id.

If copy or folder creation fails, do not `batchUpdate` the original. Show the error and stop.

### Apply replacements

On the copy, for each replacement (process from end of document to start if using index ranges, so earlier indices stay valid):

- Delete the block’s current text and insert the new text, **or** use an equivalent Docs API text replace that stays inside that paragraph/cell
- Keep paragraph/table-cell styles; do not rebuild the document
- Prefer `replaceAllText` only when the original string is unique; otherwise use ranged delete+insert from `documents.get` on the **copy**

Do not use `replaceAllText` for short strings that might appear twice (company names, “Python”, dates).

### Success UI

- Message that customization succeeded (or succeeded with a page-budget warning)
- Caption with source vs customized PDF page counts
- **Open customized resume** — `webViewLink` (editable analog of the `.tex` download)
- **Download customized resume (.pdf)** — last Drive-exported PDF bytes (analog of the LaTeX PDF download)
- Estimated API cost (same ledger path as LaTeX, including the condense call when it ran)
- No `.docx` download

If Claude succeeds but Drive copy/update fails, show the error; do not pretend a Doc was created.

## Dependencies (when implementing)

Typical libraries (pin in `requirements.txt` at implement time):

- Google API client + auth (`google-api-python-client`, `google-auth`, `google-auth-oauthlib`, `google-auth-httplib2`)
- Streamlit OAuth helper and/or Picker component that exposes **file id**

Do not add LibreOffice, `python-docx`, or extra TeX packages for this editor. Page counts use Drive PDF export + existing `pypdf`.

## Tests

Use `unittest` and mocks (no live Google or Anthropic).

- Payload parser: valid replacements, missing `job_title`, empty `text`, unknown `block_id` handling
- Folder: create when missing; reuse existing `ResumeCustomizer` folder
- Copy: `batchUpdate` and rename target the copy id, never the source id
- Page loop: original export counted; copy export counted; condense Claude called only when copy pages > source pages; second export after condense
- Page loop: source export failure aborts before Claude (like a `.tex` that will not compile)
- Page loop: condense parse failure keeps first copy and warns
- Extract: paragraphs and table cells become numbered blocks; empty paragraphs skipped
- Registry: `get_editor("google")` returns `GoogleEditor`; `get_editor("latex")` still works
- Dispatch: Drive-only source selects Google; `.tex` upload selects LaTeX; both sources together is rejected
- After the plugin extraction, existing LaTeX tests still pass

## Out of scope

- Converting to or from `.docx` at any step (PDF export is not Word)
- More than one condense pass
- Editing the original Doc in place
- `.docx` / `.doc` / Sheets
- Storing Google tokens in MongoDB
- Google sign-in as a replacement for the app password
- Updating [deployment.md](deployment.md) in the same change as this markdown spec; do that when the feature is implemented
