# ResumeCustomizer

This repo is a small **Streamlit** app that tailors a resume to a job description using the **Anthropic (Claude) API**. **LaTeX** (`.tex`) is compiled with **pdfLaTeX** and returned as `.tex` + `.pdf`. **Google Docs** (optional) uses Connect Google + a Drive picker, copies the Doc into a `ResumeCustomizer` folder, edits via the Docs API, and checks page count by exporting PDF through Drive.

## Setup

1. Copy [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) to `.streamlit/secrets.toml`.
2. Set `[auth]` `password` for the app sign-in page.
3. Set `[anthropic]` `api_key` to your [Anthropic API key](https://console.anthropic.com/).
4. Optional: set `[google]` keys (see the example file) to enable **Connect Google** and the Drive picker. Add OAuth redirect URIs for `http://localhost:8501` and the deployed host.
5. Install a LaTeX distribution (**MiKTeX** or **TeX Live**) so `pdflatex` is on your `PATH` (required for LaTeX PDF validation and the PDF download).
6. Create a virtual environment (`python -m venv .venv`), activate it, then install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

7. Set **`MONGODB_URI`** (and optionally **`RESUME_CUSTOMIZER_DB`**) in the environment; see [`.vscode/launch.json`](.vscode/launch.json) for example values used when debugging.
8. Run the app from the repo root (so `src` can be resolved):

   ```bash
   streamlit run src/app.py
   ```

   On Windows PowerShell, if imports fail, run from the repo root with `PYTHONPATH` set to `src`:

   ```powershell
   $env:PYTHONPATH = "src"
   $env:MONGODB_URI = "mongodb://127.0.0.1:27017"
   streamlit run src/app.py
   ```

   Or use the **ResumeCustomizer: Streamlit (Debug)** / **(Run)** configurations in [`.vscode/launch.json`](.vscode/launch.json), which set `PYTHONPATH`, `MONGODB_URI`, and `RESUME_CUSTOMIZER_DB`.

## Docker

The image uses **Python 3.11** on **Debian Bookworm**, installs **pdfLaTeX** via TeX Live packages, and sets `PYTHONPATH` so `resume_customizer` imports resolve. Do not bake real credentials into the image; mount `.streamlit/secrets.toml` at run time.

**Build** (from the repo root):

```bash
docker build -t resume-customizer:latest .
```

**Run** (mount your secrets file; **MongoDB is required** for the spend ledger—set `MONGODB_URI`, e.g. MongoDB on the host via Docker Desktop):

```bash
docker run --rm -p 8501:8501 \
  -v "$(pwd)/.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro" \
  -e MONGODB_URI="mongodb://host.docker.internal:27017" \
  resume-customizer:latest
```

On Windows PowerShell:

```powershell
docker run --rm -p 8501:8501 `
  -v "${PWD}\.streamlit\secrets.toml:/app/.streamlit/secrets.toml:ro" `
  -e MONGODB_URI="mongodb://host.docker.internal:27017" `
  resume-customizer:latest
```

Set `RESUME_CUSTOMIZER_DB` if you want a database name other than the default (`resume_customizer`).

Then open [http://localhost:8501](http://localhost:8501).

**Compose** (Streamlit plus MongoDB; ensure `.streamlit/secrets.toml` exists first):

```bash
docker compose up --build
```

The app service sets `MONGODB_URI` in [`docker-compose.yml`](docker-compose.yml) (often `host.docker.internal` to reach **MongoDB on the Windows host**). It mounts `./.streamlit/secrets.toml` read-only.

### MongoDB on Windows: `bindIp: 0.0.0.0` and “nothing can connect”

If you widened Mongo to `bindIp: 0.0.0.0` and **Streamlit from WSL** or **Docker** can no longer connect while **Windows-native** Python still can:

1. **Windows Firewall** often blocks inbound TCP **27017** from **WSL** and **Docker** even though loopback (`127.0.0.1`) still works from the same PC. Run the repo script **as Administrator**:

   ```powershell
   Set-Location <repo>\scripts
   .\Enable-MongoInboundFirewall.ps1
   ```

   Adjust the `mongod.exe` path inside the script if your install is not `Server\8.3`.

2. **WSL is not Windows loopback:** inside WSL, `127.0.0.1` is the **Linux** machine. To hit Mongo on Windows, use the **Windows host** address (often the default route gateway from WSL: `ip route show default | awk '{print $3}'`) or `172.30.240.1`-style **vEthernet (WSL)** addresses—after the firewall rule above, `MONGODB_URI=mongodb://<that-ip>:27017` from WSL is typical.

3. **Docker → Windows Mongo:** if `host.docker.internal` still fails after the firewall script, set `MONGODB_URI` to your PC’s **LAN IPv4** (e.g. `192.168.x.x`) in a Compose `.env` file (see [Compose env file](https://docs.docker.com/compose/environment-variables/set-environment-variables/)) and ensure the firewall allows that path.

## Tests

From the repo root with `PYTHONPATH=src` (or equivalent):

```bash
python -m unittest discover -s tests -v
```

Tests use `unittest` and mocks; they do not call the live Anthropic API.

## Notes

- **Single self-contained `.tex`:** The compiler runs one file in a temp directory. Projects that rely on `\\input` of other local files or assets are not fully supported in this version.
- **Model list** in the app sidebar uses Anthropic model ids (see `MODEL_OPTIONS` in `src/app.py`).
