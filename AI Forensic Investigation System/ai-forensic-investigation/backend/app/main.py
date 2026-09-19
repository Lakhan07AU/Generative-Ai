import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api import auth, videos, cameras, dashboard, media, rag, policies, investigations, reports, evidence, live, evidence_live, demo, investigation_search, investigator, forensics, health, audit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _DEFAULT_SECRETS = ("change_me", "dev_secret_key_for_local_testing_only_change_in_production")
    if settings.SECRET_KEY in _DEFAULT_SECRETS:
        logger.warning(
            "SECRET_KEY is set to a known development default. Generate a strong "
            "random secret (python -c \"import secrets; print(secrets.token_urlsafe(64))\") "
            "and set SECRET_KEY before any non-demo deployment."
        )
    # Ensure MinIO buckets exist on startup
    try:
        from app.storage.service import storage

        storage.ensure_buckets()
        logger.info("MinIO buckets ensured")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not ensure MinIO buckets at startup: %s", exc)
    yield


app = FastAPI(title="AI Forensic Investigation System", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(videos.router)
app.include_router(cameras.router)
app.include_router(dashboard.router)
app.include_router(media.router)
app.include_router(rag.router)
app.include_router(policies.router)
app.include_router(investigations.router)
app.include_router(reports.router)
app.include_router(evidence.router)
app.include_router(live.router)
app.include_router(evidence_live.router)
app.include_router(demo.router)
app.include_router(investigation_search.router)
app.include_router(investigator.router)
app.include_router(forensics.router)
app.include_router(health.router)
app.include_router(audit.router)


@app.get("/")
def root():
    return {"service": "AI Forensic Investigation System", "version": "1.0.0", "status": "ok"}
