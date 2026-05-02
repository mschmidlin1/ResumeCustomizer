# ResumeCustomizer

This repo is a small **Streamlit** app that tailors a **LaTeX** resume to a job description using the **Anthropic (Claude) API**, validates the result by compiling to **PDF** with **pdfLaTeX**, and offers separate downloads for the customized `.tex` and `.pdf`.

## Setup

1. Copy [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) to `.streamlit/secrets.toml`.
2. Set `[auth]` `password` for the app sign-in page.
3. Set `[anthropic]` `api_key` to your [Anthropic API key](https://console.anthropic.com/).
4. Install a LaTeX distribution (**MiKTeX** or **TeX Live**) so `pdflatex` is on your `PATH` (required for PDF validation and the PDF download).
5. Create a virtual environment (`python -m venv .venv`), activate it, then install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

6. Run the app from the repo root (so `src` can be resolved):

   ```bash
   streamlit run src/app.py
   ```

   On Windows PowerShell, if imports fail, run from the repo root with `PYTHONPATH` set to `src`:

   ```powershell
   $env:PYTHONPATH = "src"
   streamlit run src/app.py
   ```

   Or use the **ResumeCustomizer: Streamlit (Debug)** / **(Run)** configurations in [`.vscode/launch.json`](.vscode/launch.json) if configured with the same `PYTHONPATH`.

## Tests

From the repo root with `PYTHONPATH=src` (or equivalent):

```bash
python -m unittest discover -s tests -v
```

Tests use `unittest` and mocks; they do not call the live Anthropic API.

## Notes

- **Single self-contained `.tex`:** The compiler runs one file in a temp directory. Projects that rely on `\\input` of other local files or assets are not fully supported in this version.
- **Model list** in the app sidebar uses Anthropic model ids (see `MODEL_OPTIONS` in `src/app.py`).
