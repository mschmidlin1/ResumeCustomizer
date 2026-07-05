# Docker Setup Playbook

This document is a step-by-step playbook for setting up a new repository the same way the **Resume Customizer** project is set up: a Python/Streamlit app that builds and runs in Docker (via WSL on Windows), is launched/debugged from VS Code, and connects to a MongoDB instance running on the Windows host.

Each step is tagged either **(AI)** or **(Human)** to indicate who performs it.

- **(AI)** steps are performed by the assistant — file creation, edits, terminal commands.
- **(Human)** steps must be performed by the user. The AI **must pause** and prompt the human with explicit instructions, then wait for confirmation before continuing.

Throughout this doc, replace the placeholders below with values for the new project:

| Placeholder | Meaning | Example (this repo) |
|---|---|---|
| `<PROJECT_NAME>` | Friendly name shown in launch configs/tasks | `ResumeCustomizer` |
| `<APP_ENTRY>` | Path (inside repo) to the Streamlit entry script | `src/app.py` |
| `<APP_PORT>` | Port the app listens on inside the container | `8501` |
| `<SRC_DIR>` | Source directory copied into the image | `src` |
| `<DB_NAME>` | Mongo database name | `resume_customizer` |
| `<DB_ENV_VAR>` | Env var name the app reads for the DB name | `RESUME_CUSTOMIZER_DB` |
| `<HOST_IP>` | Physical LAN IPv4 of the host running Mongo | `192.168.50.116` |
| `<SECRETS_FILE>` | Path to a host-mounted secrets file (optional) | `.streamlit/secrets.toml` |

---

## 0. Prerequisites (Human)

Before any AI steps, the human must have the following installed and working:

1. Windows 10/11 with **WSL2** enabled.
2. A WSL distro (Ubuntu/Debian) with **Docker Engine** installed *inside* WSL (not just Docker Desktop). The Docker daemon should be runnable via `wsl -u root service docker start`.
3. **VS Code** with the Python and Docker extensions.
4. (Optional) **MongoDB Community Server** installed natively on Windows if the app needs a database.

> **AI prompt to human (before continuing):**
> "Please confirm: WSL2 is installed, a Linux distro with Docker Engine is set up inside WSL, and VS Code is installed. Reply when ready."

---

## 1. Fix the WSL Docker credentials store (AI)

If Docker Desktop was ever installed on Windows, WSL's `~/.docker/config.json` may contain `{"credsStore": "desktop.exe"}`. That entry causes `docker compose build` inside WSL to fail because `desktop.exe` is not on the WSL `PATH`.

**What to change**

- **File:** `~/.docker/config.json` *(inside WSL, not Windows)*
- **Before:**

  ```json
  { "credsStore": "desktop.exe" }
  ```

- **After:**

  ```json
  {}
  ```

**Steps for the AI**

1. Open a WSL terminal (`wsl` from PowerShell, or your distro's launcher).
2. Back up the original file:

   ```bash
   cp ~/.docker/config.json ~/.docker/config.json.bak
   ```

3. Overwrite it with an empty JSON object:

   ```bash
   echo '{}' > ~/.docker/config.json
   ```

4. Verify:

   ```bash
   cat ~/.docker/config.json
   ```

   It should print exactly `{}`.

---

## 2. Create the `Dockerfile` (AI)

Place this file at the repo root as `Dockerfile`. Adjust the `apt-get` packages, `WORKDIR`, source copy, and `CMD` to match the new project.

```dockerfile
FROM python:3.11-bookworm

# OS-level dependencies. Trim or extend this list per project.
# (This repo needs TeX Live to render LaTeX résumés to PDF.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-fonts-recommended \
        texlive-latex-extra \
        texlive-fonts-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Streamlit looks here for secrets.toml when mounted.
RUN mkdir -p /app/.streamlit

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY <SRC_DIR> ./<SRC_DIR>

ENV PYTHONPATH=/app/<SRC_DIR>

EXPOSE <APP_PORT>

CMD ["streamlit", "run", "<APP_ENTRY>", "--server.address=0.0.0.0", "--server.port=<APP_PORT>"]
```

Notes:

- `--server.address=0.0.0.0` is required so the container is reachable from the Windows host browser.
- `PYTHONPATH=/app/<SRC_DIR>` lets imports inside the source tree resolve as if `<SRC_DIR>` were a top-level package root.

---

## 3. Create the `.dockerignore` (AI)

Place at the repo root as `.dockerignore`. Keeps the build context small and prevents secrets/caches from leaking into the image.

```gitignore
.git
.venv
__pycache__
**/__pycache__
*.py[cod]
*$py.class
.pytest_cache
.mypy_cache
.ruff_cache
.streamlit/secrets.toml
cost_data
tests
.cursor
*.egg-info
.eggs
build
dist
.env
.env.*
```

Add any other large or sensitive directories specific to the new project (e.g., model weights, datasets, scratch folders).

---

## 4. Create the `docker-compose.yml` (AI)

Place at the repo root. The MongoDB env vars are only needed if the app talks to Mongo on the host (see Section 7 for how to fill in `<HOST_IP>`).

```yaml
services:
  app:
    build: .
    ports:
      - "<APP_PORT>:<APP_PORT>"
    volumes:
      - ./<SECRETS_FILE>:/app/<SECRETS_FILE>:ro
    environment:
      MONGODB_URI: "mongodb://<HOST_IP>:27017"
      <DB_ENV_VAR>: "<DB_NAME>"
```

Notes:

- The secrets volume mount is read-only (`:ro`) and points to a file that is **excluded from the image** by `.dockerignore`. Remove this `volumes:` block if the project has no secrets file.
- Drop the `MONGODB_URI` / `<DB_ENV_VAR>` lines if Mongo is not used.

---

## 5. Create `.vscode/launch.json` (AI)

This file gives the developer three F5 configurations:

1. **Docker: Run Streamlit App** — builds and runs the container via `docker compose` inside WSL.
2. **<PROJECT_NAME>: Streamlit (Debug)** — runs Streamlit directly under `debugpy` against a local `.venv` so breakpoints work.
3. **<PROJECT_NAME>: Streamlit (Run)** — same as above without the debugger attached.

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Docker: Run Streamlit App",
      "type": "node",
      "request": "launch",
      "noDebug": true,
      "runtimeExecutable": "wsl",
      "runtimeArgs": [
        "--cd",
        "${workspaceFolder}",
        "docker",
        "compose",
        "up",
        "--build"
      ],
      "console": "integratedTerminal",
      "preLaunchTask": "Start Docker Service",
      "postDebugTask": "Docker: Compose Down"
    },
    {
      "name": "<PROJECT_NAME>: Streamlit (Debug)",
      "type": "debugpy",
      "request": "launch",
      "module": "streamlit",
      "args": [
        "run",
        "${workspaceFolder}/<APP_ENTRY>",
        "--server.headless",
        "true"
      ],
      "cwd": "${workspaceFolder}",
      "python": "${workspaceFolder}/.venv/Scripts/python.exe",
      "justMyCode": true,
      "env": {
        "PYTHONPATH": "${workspaceFolder}/<SRC_DIR>",
        "MONGODB_URI": "mongodb://127.0.0.1:27017",
        "<DB_ENV_VAR>": "<DB_NAME>"
      }
    },
    {
      "name": "<PROJECT_NAME>: Streamlit (Run)",
      "type": "debugpy",
      "request": "launch",
      "module": "streamlit",
      "args": [
        "run",
        "${workspaceFolder}/<APP_ENTRY>",
        "--server.headless",
        "true"
      ],
      "cwd": "${workspaceFolder}",
      "python": "${workspaceFolder}/.venv/Scripts/python.exe",
      "justMyCode": true,
      "noDebug": true,
      "env": {
        "PYTHONPATH": "${workspaceFolder}/<SRC_DIR>",
        "MONGODB_URI": "mongodb://127.0.0.1:27017",
        "<DB_ENV_VAR>": "<DB_NAME>"
      }
    }
  ]
}
```

Important details:

- The Docker config uses `type: "node"` with `runtimeExecutable: "wsl"`. This is a deliberate trick to invoke any arbitrary command from VS Code's launcher; it does **not** mean the project is Node.js.
- The two `debugpy` configs use `mongodb://127.0.0.1:27017` because they run on the Windows host directly. The Docker config uses `<HOST_IP>` (set in `docker-compose.yml`) because the container can't reach the host via `127.0.0.1` or `localhost`.
- `python` points at `.venv/Scripts/python.exe` (Windows path). On a non-Windows dev machine, change to `.venv/bin/python`.

---

## 6. Create `.vscode/tasks.json` (AI)

Defines the `preLaunchTask` (start Docker daemon in WSL) and `postDebugTask` (tear the compose stack down) referenced by `launch.json`.

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Start Docker Service",
      "type": "shell",
      "command": "wsl -u root service docker start",
      "presentation": {
        "reveal": "always",
        "panel": "shared"
      }
    },
    {
      "label": "Docker: Compose Down",
      "type": "process",
      "command": "wsl",
      "args": [
        "--cd",
        "${workspaceFolder}",
        "docker",
        "compose",
        "down"
      ],
      "presentation": {
        "reveal": "always",
        "panel": "shared"
      },
      "problemMatcher": []
    }
  ]
}
```

`Start Docker Service` requires `wsl -u root service docker start` to be runnable without a password prompt. If your distro's root account requires a password, configure passwordless `service docker start` via `sudoers`, or start the daemon manually before pressing F5.

---

## 7. MongoDB on the Windows host *(only when applicable)*

Skip this entire section if the project does not use a database, or if Mongo runs as its own container in `docker-compose.yml`. These steps are specifically for **MongoDB Community installed on the Windows host** with the containerized app connecting to it across the WSL network boundary.

### 7.1 Bind Mongo to all interfaces (Human)

By default Mongo only listens on `127.0.0.1`, which the container cannot reach. Bind it to `0.0.0.0` so it accepts connections from the WSL bridge.

- **File:** `C:\Program Files\MongoDB\Server\<version>\bin\mongod.cfg`
  *(The version folder name depends on what you installed — e.g., `7.0`, `8.0`. If unsure, browse `C:\Program Files\MongoDB\Server\` and pick the only folder there.)*
- **Find:**

  ```yaml
  net:
    port: 27017
    bindIp: 127.0.0.1
  ```

- **Change to:**

  ```yaml
  net:
    port: 27017
    bindIp: 0.0.0.0
  ```

> **Security note:** `0.0.0.0` means Mongo will accept connections from anywhere the OS firewall permits. Step 7.2 limits that exposure to your private LAN by leaving the **Public** profile box unchecked on the firewall rule.

**Steps for the human**

1. Press the **Windows key**, type `Notepad`, right-click **Notepad** → **Run as administrator**. (Admin rights are required because the file lives under `Program Files`.)
2. In Notepad: **File → Open**, paste `C:\Program Files\MongoDB\Server\` into the path bar, open the version folder, then `bin\mongod.cfg`. (Set the file-type filter to **All Files** so `.cfg` is visible.)
3. Edit the `bindIp` line as shown above and save.
4. Restart the service so the change takes effect. In an **admin PowerShell**:

   ```powershell
   Restart-Service MongoDB
   ```

5. Verify it's listening on all interfaces:

   ```powershell
   Get-NetTCPConnection -LocalPort 27017 -State Listen | Select-Object LocalAddress, LocalPort
   ```

   You should see `0.0.0.0` in the `LocalAddress` column.

> **AI prompt to human:**
> "Open Notepad as Administrator, edit `C:\Program Files\MongoDB\Server\<version>\bin\mongod.cfg`, change `bindIp: 127.0.0.1` to `bindIp: 0.0.0.0`, save, then run `Restart-Service MongoDB` in an admin PowerShell. Reply 'done' when finished."

### 7.2 Open port 27017 in Windows Firewall (Human, Windows-only)

> **AI prompt to human (must run *first*):**
> "Are you on a Windows PC? If yes, follow the steps below. If you're on macOS or Linux, tell me your OS so we can use the right firewall tool (`pfctl` / `ufw` / etc.)."
>
> If unsure, the AI may run `[System.Environment]::OSVersion.Platform` (PowerShell) or `uname -s` (bash) in a terminal to detect the OS itself before asking.

Assuming Windows:

1. Press **Windows key**, type `Windows Defender Firewall with Advanced Security`, press **Enter**. (Make sure to pick the "with Advanced Security" entry, not the basic Control Panel one.)
2. In the left pane, click **Inbound Rules**.
3. In the right pane, click **New Rule…**.
4. **Rule Type:** select **Port**, click **Next**.
5. **Protocol and Ports:** select **TCP**, choose **Specific local ports**, enter `27017`, click **Next**.
6. **Action:** select **Allow the connection**, click **Next**.
7. **Profile:** check **Domain** and **Private**. **Uncheck Public.** Click **Next**.
8. **Name:** `MongoDB 27017 (LAN only)`. Description optional. Click **Finish**.

To verify, from the WSL distro run:

```bash
nc -zv <HOST_IP> 27017
```

You should see `succeeded`/`open`. If `nc` isn't available, `curl -v telnet://<HOST_IP>:27017` works too (look for "Connected").

> **AI prompt to human:**
> "Please walk through the eight Windows Firewall steps above to add the inbound TCP rule on port 27017 for Domain + Private profiles only. Reply 'done' when the new rule appears in the Inbound Rules list."

### 7.3 Discover the host IP and update configs (AI)

The container reaches the Windows host through its **LAN IPv4 address**, not `localhost` or `127.0.0.1`. The AI determines this address and writes it into both `docker-compose.yml` and the Docker config inside `launch.json`.

**Find the IP**

From PowerShell on the Windows host:

```powershell
Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp |
  Where-Object { $_.InterfaceAlias -notmatch 'WSL|vEthernet|Loopback' } |
  Select-Object IPAddress, InterfaceAlias
```

Pick the IP on the active LAN/Wi-Fi adapter (typically `Ethernet` or `Wi-Fi`). In this repo it is `192.168.50.116`.

> If the host uses DHCP, this address can change. When connections start failing after a reboot or network change, re-run the command above and update both files.

**Update `docker-compose.yml`**

Replace the `MONGODB_URI` value:

```yaml
    environment:
      MONGODB_URI: "mongodb://<HOST_IP>:27017"
      <DB_ENV_VAR>: "<DB_NAME>"
```

**Leave the `debugpy` configs in `launch.json` alone**

The two `debugpy` launch configs run directly on the Windows host, so they should keep `mongodb://127.0.0.1:27017`. Only the **Docker** path (which lives entirely in `docker-compose.yml`) needs `<HOST_IP>`.

If you ever decide to also override `MONGODB_URI` from the Docker launch config in `launch.json` (instead of compose), it would look like this — but this is **not** done in the Resume Customizer repo:

```json
"env": {
  "MONGODB_URI": "mongodb://<HOST_IP>:27017"
}
```

---

## 8. First run (Human)

1. Open the new repo in VS Code.
2. Open the **Run and Debug** panel.
3. Pick **Docker: Run Streamlit App** and press F5.
4. Wait for `docker compose up --build` to finish, then open `http://localhost:<APP_PORT>` in a browser.
5. To stop, end the debug session — `Docker: Compose Down` runs automatically as the post-debug task.

> **AI prompt to human:**
> "Try launching **Docker: Run Streamlit App** in VS Code. Tell me whether the app loads at `http://localhost:<APP_PORT>`, and if Mongo-backed features work. Paste any errors here so I can help debug."

---

## Quick checklist

- [ ] (Human) WSL + Docker Engine + VS Code installed.
- [ ] (Human) `~/.docker/config.json` cleared of `credsStore: desktop.exe`.
- [ ] (AI) `Dockerfile` at repo root.
- [ ] (AI) `.dockerignore` at repo root.
- [ ] (AI) `docker-compose.yml` at repo root.
- [ ] (AI) `.vscode/launch.json` written.
- [ ] (AI) `.vscode/tasks.json` written.
- [ ] (Human, if Mongo) `mongod.cfg` `bindIp` set to `0.0.0.0`, service restarted.
- [ ] (Human, if Mongo & Windows) Inbound firewall rule for TCP 27017 (Domain + Private only).
- [ ] (AI, if Mongo) `<HOST_IP>` filled into `docker-compose.yml`.
- [ ] (Human) F5 → **Docker: Run Streamlit App** succeeds and the app loads in the browser.
