# Mini Project: Local GitHub Repository Code Explainer

A fully local GenAI application that takes a GitHub repository URL and explains the
codebase in simple language using a locally running LLM.

```
GitHub URL  →  Clone (GitPython)  →  Read source files  →  Prompt  →  Local LLM (Ollama)
                                                                        ↓
Streamlit UI  ←  JSON response  ←  FastAPI  ←  explanation (Markdown)
```

## Features

- Accepts any public GitHub repository URL (`https://github.com/username/repository`)
- Shallow-clones the repository with GitPython (portable MinGit, no admin rights needed)
- Selects the relevant source-code files (skips `node_modules`, binaries, lock files, images...)
- Sends the extracted code to a local LLM through Ollama
- Returns a structured Markdown explanation: overview, features, technologies, flow, structure
- Streamlit frontend renders the explanation, the analysed file list and the detected languages

## Project structure

```
.
├── app/
│   ├── main.py            # FastAPI backend (endpoints)
│   ├── schemas.py         # Pydantic request/response models
│   ├── repo_processor.py  # clone + file selection + code extraction
│   ├── llm.py             # Ollama client + prompt builder
│   └── config.py          # paths, limits, environment settings
├── frontend/
│   └── app.py             # Streamlit UI
├── scripts/
│   ├── setup.ps1          # installs portable Git + Ollama and pulls the model
│   ├── run.ps1            # starts backend + frontend
│   └── smoke_test.py      # end-to-end check of backend and frontend
├── pyproject.toml         # ruff lint/format settings
├── requirements.txt
└── README.md
```

## Prerequisites

- Python 3.11+
- Windows PowerShell (setup scripts are written for Windows; on Linux/macOS install
  `git` and `ollama` with your package manager instead)
- Internet access the first time (to clone repos and download the model)

## Setup

```powershell
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

`scripts/setup.ps1` will:

1. Download the portable MinGit bundle into `%LOCALAPPDATA%\miniproject-tools\MinGit` (no admin rights required)
2. Download the portable Ollama build into `%LOCALAPPDATA%\miniproject-tools\ollama`
3. Start `ollama serve` on `http://127.0.0.1:11434`
4. Pull the default model `qwen2.5:1.5b` (about 1 GB, only once)

## Run

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run.ps1
```

- Backend (FastAPI + Uvicorn): http://127.0.0.1:8001 — interactive docs at `/docs`
- Frontend (Streamlit): http://127.0.0.1:8501

`run.ps1` opens one console window per server. Close those windows to stop the app.

Or start them manually in two terminals:

```powershell
$env:PYTHONPATH = "."
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
python -m streamlit run frontend/app.py --server.headless true
```

> The backend uses port **8001** on purpose: Docker Desktop already occupies 8000 on some machines.

## Run with VS Code

1. Open this folder in VS Code (`File > Open Folder...`).
2. Install the **Python** extension (ms-python.python) if it is not installed yet, and pick the
   interpreter you used for `pip install -r requirements.txt`.
3. First time only: `Terminal > Run Task... > setup: install portable Git + Ollama`
   (downloads portable Git + Ollama and pulls `qwen2.5:1.5b`).
4. Make sure Ollama is running: `Terminal > Run Task... > ollama: serve`
   (check `http://127.0.0.1:11434/api/tags`).
5. Press **F5** and choose:
   - **Backend + Frontend** — starts both in the debug console
   - **Backend (FastAPI :8001)** or **Frontend (Streamlit :8501)** — start one at a time
6. Open http://127.0.0.1:8501 , paste a repo URL and click *Explain this repository*.
7. Set breakpoints directly in `app/main.py`, `app/repo_processor.py` or `app/llm.py` —
   `justMyCode` is on, so stepping only stops in project code.
8. Stop with the red square in the Debug toolbar (`stopAll` stops both processes).

Optional: run `Smoke test (end-to-end)` from the F5 dropdown to verify the whole pipeline.

## API

| Method | Endpoint       | Body                                      | Result                                  |
|--------|----------------|-------------------------------------------|-----------------------------------------|
| GET    | `/api/health`  | –                                         | git / ollama status, available models   |
| POST   | `/api/explain` | `{"repo_url": "https://github.com/u/r"}`  | explanation + analysed files + metadata |

Example:

```powershell
curl -X POST http://127.0.0.1:8001/api/explain `
  -H "Content-Type: application/json" `
  -d '{"repo_url": "https://github.com/example/expense-tracker"}'
```

## Smoke test

With the stack running:

```powershell
python scripts\smoke_test.py                      # default repo: pallets/click
python scripts\smoke_test.py https://github.com/you/your-repo
```

It checks `/api/health`, calls `/api/explain` and then drives the Streamlit page itself,
printing the rendered Markdown. Exit message: `ALL SMOKE TESTS PASSED`.

## Configuration (environment variables)

| Variable                | Default                                    | Purpose                                  |
|-------------------------|--------------------------------------------|------------------------------------------|
| `OLLAMA_HOST`           | `http://127.0.0.1:11434`                   | Ollama server address                    |
| `OLLAMA_MODEL`          | `qwen2.5:1.5b`                             | Preferred model                          |
| `MAX_FILES`             | `50`                                       | Max source files sent to the LLM         |
| `MAX_FILE_CHARS`        | `4000`                                     | Truncation limit per file                |
| `MAX_TOTAL_CHARS`       | `26000`                                    | Total code budget for one prompt         |
| `LLM_CONTEXT_TOKENS`    | `8192`                                     | Ollama context window                    |
| `BACKEND_URL`           | `http://127.0.0.1:8001`                    | Backend address used by the frontend     |

Other suggested models: `qwen2.5:0.5b` (fastest), `phi3:mini`, `llama3.2:1b`, `gemma2:2b`.
Pull one with `ollama pull <model>` and pick it in the frontend dropdown.

## Notes

- The explanation is produced by the local LLM at request time; nothing is hard-coded.
- Repositories are cloned into a temporary folder and deleted after each request.
- On CPU, generating an explanation takes roughly 30–120 seconds depending on the model.
- Lint/format: `ruff check .` and `ruff format .`
- Portable tooling lives in `%LOCALAPPDATA%\miniproject-tools` (`MinGit`, `ollama`), so no
  admin rights are required.
