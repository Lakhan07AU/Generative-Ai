from pydantic import BaseModel, Field, field_validator

REPO_URL_PATTERN = r"^https?://(www\.)?github\.com/[\w.\-]+/[\w.\-]+/?(\.git)?(/[^\s]*)?$"


class ExplainRequest(BaseModel):
    repo_url: str = Field(
        ...,
        description="GitHub repository URL, e.g. https://github.com/username/repository",
    )
    model: str | None = Field(None, description="Ollama model name. Defaults to the server-side default.")

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, value: str) -> str:
        import re

        cleaned = value.strip()
        if not re.match(REPO_URL_PATTERN, cleaned):
            raise ValueError("Invalid GitHub repository URL. Example: https://github.com/username/repository")
        return cleaned


class AnalysedFile(BaseModel):
    path: str
    chars: int
    language: str


class ExplainResponse(BaseModel):
    repo_url: str
    project_name: str
    model_used: str
    files_analysed: int
    files: list[AnalysedFile]
    languages: dict[str, int]
    explanation: str
    elapsed_seconds: float


class HealthResponse(BaseModel):
    status: str
    git_available: bool
    git_path: str | None
    ollama_available: bool
    ollama_host: str
    default_model: str
    available_models: list[str]
    llm_backend: str
    openai_configured: bool


class ExplainJobCreated(BaseModel):
    job_id: str
    status: str


class ExplainJobStatus(BaseModel):
    job_id: str
    status: str
    detail: str | None = None
    result: ExplainResponse | None = None
