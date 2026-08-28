import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api import auth, videos, cameras, dashboard, media, rag, policies, investigations, reports, evidence

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.get("/")
def root():
    return {"service": "AI Forensic Investigation System", "version": "1.0.0", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}
