import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import config, llm, repo_processor, schemas

git_ok, git_path_or_reason = config.configure_git()

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.prepare_repos_dir()
    yield


app = FastAPI(
    title="Local GitHub Repository Code Explainer",
    description="Clone a GitHub repository, read its source code and explain it with a local LLM.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["meta"])
def root():
    return {
        "service": "Local GitHub Repository Code Explainer",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/api/health", response_model=schemas.HealthResponse, tags=["meta"])
def health():
    active = llm.backend()
    ollama_ok = llm.is_ollama_available()
    llm_ok = llm.is_available()
    return schemas.HealthResponse(
        status="ok" if git_ok and llm_ok else "degraded",
        git_available=git_ok,
        git_path=git_path_or_reason if git_ok else None,
        ollama_available=ollama_ok,
        ollama_host=config.OLLAMA_HOST,
        default_model=config.DEFAULT_MODEL if active != "openai" else config.OPENAI_MODEL,
        available_models=llm.list_models(),
        llm_backend=active,
        openai_configured=bool(config.OPENAI_API_KEY),
    )


@app.post("/api/explain", response_model=schemas.ExplainResponse, tags=["explain"])
def explain(request: schemas.ExplainRequest):
    return _run_explain(request)


@app.post("/api/jobs", response_model=schemas.ExplainJobCreated, status_code=202, tags=["explain"])
def create_job(request: schemas.ExplainRequest):
    _require_dependencies()
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _prune_jobs_locked()
        _JOBS[job_id] = {
            "status": "queued",
            "detail": None,
            "result": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    threading.Thread(target=_run_job, args=(job_id, request), daemon=True).start()
    return schemas.ExplainJobCreated(job_id=job_id, status="queued")


@app.get("/api/jobs/{job_id}", response_model=schemas.ExplainJobStatus, tags=["explain"])
def get_job(job_id: str):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job id (jobs expire after one hour).")
        return schemas.ExplainJobStatus(
            job_id=job_id,
            status=job["status"],
            detail=job["detail"],
            result=job["result"],
        )


def _require_dependencies() -> None:
    if not git_ok:
        raise HTTPException(
            status_code=503,
            detail=f"Git is required to clone repositories but is not available: {git_path_or_reason}. "
            "Run scripts/setup.ps1 to install the portable Git bundle.",
        )
    if not llm.is_available():
        active = llm.backend()
        if active == "openai":
            detail = "No LLM API key configured. Set OPENAI_API_KEY (free key: https://console.groq.com/keys)."
        elif active == "none":
            detail = (
                f"No LLM is reachable: Ollama is not responding at {config.OLLAMA_HOST} and OPENAI_API_KEY is not set."
            )
        else:
            detail = f"Ollama is not reachable at {config.OLLAMA_HOST}. Start it with 'ollama serve'."
        raise HTTPException(status_code=503, detail=detail)


def _run_explain(request: schemas.ExplainRequest) -> schemas.ExplainResponse:
    _require_dependencies()

    started = time.time()
    workdir = _make_workdir()
    try:
        try:
            repo = repo_processor.extract_repository(request.repo_url, dest_root=workdir)
        except repo_processor.CloneError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except repo_processor.ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        prompt = llm.build_prompt(repo.name, repo.url, repo.files, repo.languages)
        try:
            explanation, model_used = llm.generate(prompt, model=request.model)
        except llm.LLMError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return schemas.ExplainResponse(
            repo_url=request.repo_url,
            project_name=repo.name,
            model_used=model_used,
            files_analysed=len(repo.files),
            files=[
                schemas.AnalysedFile(
                    path=item["path"],
                    chars=len(item["content"]),
                    language=item["language"],
                )
                for item in repo.files
            ],
            languages=repo_processor.languages_summary(repo.files),
            explanation=explanation,
            elapsed_seconds=round(time.time() - started, 2),
        )
    finally:
        config.safe_rmtree(workdir)


def _run_job(job_id: str, request: schemas.ExplainRequest) -> None:
    _job_update(job_id, status="running")
    try:
        result = _run_explain(request)
    except HTTPException as exc:
        _job_update(job_id, status="error", detail=str(exc.detail))
    except Exception as exc:
        _job_update(job_id, status="error", detail=f"Unexpected error: {exc}")
    else:
        _job_update(job_id, status="done", result=result)


def _job_update(job_id: str, *, status: str, detail: str | None = None, result=None) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = status
        job["detail"] = detail
        job["result"] = result
        job["updated_at"] = time.time()


def _prune_jobs_locked() -> None:
    now = time.time()
    expired = [job_id for job_id, job in _JOBS.items() if now - job["updated_at"] > config.JOB_TTL_SECONDS]
    for job_id in expired:
        _JOBS.pop(job_id, None)
    while len(_JOBS) >= config.MAX_JOBS:
        oldest = min(_JOBS, key=lambda job_id: _JOBS[job_id]["created_at"])
        _JOBS.pop(oldest, None)


def _make_workdir() -> str:
    config.REPOS_DIR.mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(prefix="repo_explain_", dir=str(config.REPOS_DIR))
