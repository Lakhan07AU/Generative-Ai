import os
import sys

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

# ---- Test DB file (SQLite so relationships + SQL work) ----
# Point both the app's SessionLocal and the test session at the SAME file so
# background logic that opens its own SessionLocal (e.g. RAG ingestion) stays
# consistent with the test session.
TEST_DB_FILE = os.path.join(os.path.dirname(__file__), "test_forensics.db")

# Prevent any attempt to read a real .env during tests
os.environ.setdefault("SECRET_KEY", "test_secret_key")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB_FILE}")

# Make backend importable
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.database.session import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


test_engine = sa.create_engine(f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False})
TestingSession = sa.orm.sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)
    # Release the file-backed engine so the temp DB can be removed on Windows
    test_engine.dispose()
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except OSError:
            pass


@pytest.fixture
def db():
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def _reset_qdrant():
    """Reset the (offline in-memory) Qdrant singleton before every test so tests
    are independent of one another."""
    try:
        from app.ai.qdrant_service import qdrant

        qdrant._client = None
        qdrant._backend = None
        qdrant._mem = {}
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    # TestClient without context manager: avoid running lifespan (MinIO startup)
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client):
    """Register + login an investigator, return Authorization headers."""
    email = "investigator@test.com"
    client.post(
        "/auth/register",
        json={"email": email, "name": "Test Investigator", "password": "password123", "role": "INVESTIGATOR"},
    )
    res = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(client):
    email = "admin@test.com"
    client.post(
        "/auth/register",
        json={"email": email, "name": "Admin", "password": "password123", "role": "ADMIN"},
    )
    res = client.post("/auth/login", json={"email": email, "password": "password123"})
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
