import tempfile
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import config, llm, repo_processor, schemas

git_ok, git_path_or_reason = config.configure_git()


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
    ollama_ok = llm.is_available()
    models = llm.list_models() if ollama_ok else []
    return schemas.HealthResponse(
        status="ok" if git_ok and ollama_ok else "degraded",
        git_available=git_ok,
        git_path=git_path_or_reason if git_ok else None,
        ollama_available=ollama_ok,
        ollama_host=config.OLLAMA_HOST,
        default_model=config.DEFAULT_MODEL,
        available_models=models,
    )


@app.post("/api/explain", response_model=schemas.ExplainResponse, tags=["explain"])
def explain(request: schemas.ExplainRequest):
    if not git_ok:
        raise HTTPException(
            status_code=503,
            detail=f"Git is required to clone repositories but is not available: {git_path_or_reason}. "
            "Run scripts/setup.ps1 to install the portable Git bundle.",
        )
    if not llm.is_available():
        raise HTTPException(
            status_code=503,
            detail=f"Ollama is not reachable at {config.OLLAMA_HOST}. Start it with 'ollama serve'.",
        )

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


def _make_workdir() -> str:
    config.REPOS_DIR.mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(prefix="repo_explain_", dir=str(config.REPOS_DIR))
