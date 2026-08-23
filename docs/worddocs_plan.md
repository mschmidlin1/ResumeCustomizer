# Word (.docx) editor — implementation plan (not implemented)

> **Status: next / not implemented.** The live app accepts **`.tex` uploads** and **Google Docs** only.
> `.docx` is rejected in dispatch until this plan ships. See [architecture.md](architecture.md).

This spec adds a **Microsoft Word** resume source alongside LaTeX. Visitors sign in with the existing shared app password and use the existing Anthropic key. They upload a `.docx`, and download a **new** customized `.docx`. Google Docs users who already exported to Word can use this path; native Google Docs (Connect + Picker, no Word conversion) is a separate plan: [gdocs_plan.md](gdocs_plan.md).

Implement this at a different time from the Google editor. **Whichever editor ships first** extracts today’s LaTeX pipeline into a `LatexEditor` plugin. The second editor only registers itself.

## Locked decisions

| Topic | Decision |
|-------|----------|
| App auth | Shared Streamlit password (`[auth] password`) |
| Claude | Shared `[anthropic] api_key` |
| Ingest | Shared file uploader: **`.tex` and `.docx`** in the right column (not legacy `.doc`) |
| Output | Download customized `.docx` only (no PDF, no page-budget loop) |
| Original file | Never mutated; work on an in-memory copy |
| UI | Two columns: **Google Drive** controls \| **file upload** (`.tex` and `.docx`). No source radio. |
| Editor selection | Drive Doc → `GoogleEditor`; `.tex` upload → `LatexEditor`; `.docx` upload → `DocxEditor` |
| Layout | In-place text replacement with `python-docx`, not a rebuilt document |

LaTeX keeps pdfLaTeX, page-count matching, and `.tex` / `.pdf` downloads **inside** `LatexEditor`. The Word editor does not compile, count pages, call LibreOffice, or offer a PDF button.

## Current code this plan touches

Today everything is LaTeX-specific:

- [`src/app.py`](../src/app.py) — upload `.tex`, Claude, pdfLaTeX, download buttons
- [`src/resume_customizer/claude_service.py`](../src/resume_customizer/claude_service.py) — JSON with `job_title` + `customized_latex`
- [`src/resume_customizer/parsing.py`](../src/resume_customizer/parsing.py) — LaTeX payload only
- [`src/resume_customizer/filenames.py`](../src/resume_customizer/filenames.py) — reuse for `.docx` download names

After this work, `app.py` should not import `python-docx` or pdfLaTeX.

Google Docs → Word export can shift columns and spacing (see the earlier options discussion). This editor does not try to fix that; it customizes whatever `.docx` the user uploaded. Word-native resumes skip that Google export step entirely.

---

## Shared editor plugin

This contract is the same as in [gdocs_plan.md](gdocs_plan.md). Implement it once (during whichever editor ships first).

### Package layout

```
src/resume_customizer/editors/
    __init__.py
    base.py          # protocol + EditorRunResult
    latex.py         # today’s behavior
    docx.py          # this plan
    registry.py      # get_editor(kind)
```

`editors/google.py` is added by the Google plan, not this one. Until then the left column is empty or a short “Google Docs coming later” caption. `registry.py` should still accept `"google"` and fail clearly if that module is missing.

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

`SourceHandle` is an opaque per-editor object (uploaded bytes + filename for Word/LaTeX). `EditorRunResult` always includes `job_title`, cost/usage for the ledger, and editor-specific artifacts (LaTeX string + PDF bytes, or `.docx` bytes).

### Orchestrator (`app.py`)

Keep: page config, password gate, sidebar (model/prompt/temperature/max tokens, sign out, spend metric), job-description text area, **Run**, cost-ledger writes.

Main source UI is **two columns** (no radio):

| Left column | Right column |
|-------------|--------------|
| Google Drive: Connect / Disconnect / Picker (`GoogleEditor.render_source_controls()` when that plugin exists) | Shared `st.file_uploader` with `type=["tex", "docx"]` |

On Run, pick **exactly one** source:

- Drive Doc selected, no upload → `GoogleEditor`
- `.tex` uploaded, no Drive Doc → `LatexEditor`
- `.docx` uploaded, no Drive Doc → `DocxEditor`
- Both columns have a source → warn and do not Run (“Use a Google Doc or an uploaded file, not both”)
- Neither → warn to pick a source

Then `result = editor.run(...)`, persist ledger entries, `editor.render_outputs(result)`.

Do not put `python-docx`, Google OAuth, Docs `batchUpdate`, or `pdflatex` in `app.py` beyond laying out the columns and dispatching by source (extension for uploads).

### Claude helper

Slim [`claude_service.py`](../src/resume_customizer/claude_service.py) to “JSON completion”: `messages.create`, token usage, cost estimate. Keep [`extract_json_object_text`](../src/resume_customizer/parsing.py) as shared fence-stripping.

Each editor supplies:

- Extra system-prompt rules (LaTeX validity vs “do not add/remove blocks”)
- User-message body (full `.tex` vs numbered text blocks)
- Payload parser (`customized_latex` vs `replacements`)

LaTeX’s condense-to-page-budget second call stays **inside** `LatexEditor.run`. The Word editor makes one Claude call (no page budget).

### First-ship refactor (if this plan is implemented first)

1. Move the current Run path from `app.py` into `LatexEditor`.
2. Introduce `base.py`, `registry.py`, and the two-column source row (left empty or “Google Docs coming later” until that plan ships; right = uploader for `.tex` and `.docx`).
3. Point existing tests at `LatexEditor` / the LaTeX payload parser so they still pass.
4. Then add `DocxEditor` and dispatch `.docx` uploads to it.

If Google already shipped the plugin, skip 1–3 and only add `docx.py` plus registry/UI wiring.

---

## Word source controls

The **right column** is one shared uploader, not a Word-only page:

- `st.file_uploader(..., type=["tex", "docx"])` — same drag-and-drop pattern as today’s `.tex` uploader
- Accept multiple files like LaTeX does today, but **Run uses the first**; show the same warning if more than one is selected
- Dispatch by extension: `.tex` → `LatexEditor`, `.docx` → `DocxEditor`
- Reject `.doc` (pre-2007). If someone renames `.doc` to `.docx`, `python-docx` will fail; catch that and show a short error asking for a real `.docx`

Google Connect / Picker stay in the **left column** (see [gdocs_plan.md](gdocs_plan.md)). If both a Drive Doc and an upload are set, Run is blocked until one is cleared.

## Run pipeline

```
Uploaded .docx bytes
    → open a copy with python-docx
    → extract numbered text blocks (paragraphs + table cells)
    → Claude JSON { job_title, replacements }
    → apply replacements on the in-memory copy
    → serialize .docx bytes
    → st.download_button
```

### Extract blocks

Walk:

- Body paragraphs (`document.paragraphs`)
- Table cells (`document.tables` → rows → cells → paragraphs), in document order

Assign a stable `block_id` per non-empty paragraph (including those inside cells). Headers and footers are out of scope for v1 (do not send them to Claude; leave them unchanged).

Send Claude something like:

```
BLOCK 0: Jane Doe
BLOCK 1: Software engineer
BLOCK 2: Built an API in Python
...
```

### Claude payload

Same shape as the Google editor so the two non-LaTeX plugins stay parallel:

```json
{
  "job_title": "short filename title",
  "replacements": [
    { "block_id": 2, "text": "Built a payments API in Python" }
  ]
}
```

Rules in the Word editor’s system extras:

- Only reword existing blocks; do not add or delete blocks (no new paragraphs, no dropped bullets)
- Preserve truthfulness (same claim rules as today’s LaTeX prompt)
- Prefer weaving job-description terms into existing bullets
- Omit unchanged blocks from `replacements` (identity replacements are fine)
- Never invent employers, dates, or skills

Parse errors surface in the UI the same way LaTeX parse errors do today.

### Apply replacements (`python-docx`)

Work on a **copy** of the uploaded bytes (parse a fresh `Document` from a `BytesIO` copy). Never write the user’s upload path; there isn’t one.

For each `block_id` in `replacements`, set that paragraph’s text to the new string.

**v1 formatting limit (document this in UI caption if useful):** assigning `paragraph.text` often collapses multiple runs into one and can drop mid-sentence bold/italic. Prefer a helper that:

1. Replaces text in-place when the paragraph is a single run
2. Otherwise keeps the first run’s style, writes the new text into that run, and clears following runs in the paragraph

Do not rebuild the document from scratch (that would lose tables, headers, section layout, and images). Images, shapes, and empty paragraphs stay as they are.

Unknown `block_id`s: fail the run with a parse/apply error rather than silently skipping (the model must refer to extracted ids).

### Success UI

- Message that customization succeeded
- **Download customized resume (.docx)** via `st.download_button`
- Filename: `with_download_disambiguation(safe_filename_base(job_title)) + ".docx"` (same stem rules as `.tex`)
- MIME `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- Estimated API cost (same ledger path as LaTeX)
- No PDF button

If Claude succeeds but serialization fails, show the error; do not offer a bogus download.

## Dependencies (when implementing)

- Add `python-docx` to [`requirements.txt`](../requirements.txt) (pin a current 1.x at implement time)

Do **not** add LibreOffice, unoconv, or extra apt packages to the [Dockerfile](../Dockerfile). There is no Word → PDF path.

No Google client libraries are required for this editor.

## Tests

Use `unittest` and mocks (no live Anthropic). Check in a small fixture `.docx` under `tests/fixtures/` (a few paragraphs + one table cell).

- Payload parser: valid replacements, missing `job_title`, empty `text`
- Extract: body paragraphs and table cells get ids; empty paragraphs skipped; headers ignored
- Apply: replaced paragraph text appears in the saved bytes; unmentioned paragraphs unchanged; table cell text can be replaced
- Apply: unknown `block_id` raises
- Download stem uses `job_title` via existing filename helpers
- Registry: `get_editor("docx")` returns `DocxEditor`; `get_editor("latex")` still works
- Dispatch: `.docx` upload selects Word; `.tex` upload selects LaTeX; Drive + upload together is rejected
- After the plugin extraction, existing LaTeX tests still pass

## Out of scope

- PDF export, LibreOffice, or page-count enforcement
- Legacy `.doc`
- Headers/footers, text boxes, and SmartArt (leave unchanged)
- Perfect preservation of mixed bold/italic inside a single bullet (known v1 limit)
- Google Drive upload of the result (users can open the `.docx` in Word or upload it to Docs themselves)
- Updating Docker/K8s docs for TeX — unchanged
