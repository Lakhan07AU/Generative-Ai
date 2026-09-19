"""Phase 9 - Demo database reset.

Reproducibly rebuilds the AI Forensic Investigation System demo backend in one
step and reseeds the deterministic DEMO dataset:

  1. Resolve the target database URL (-‑url > DATABASE_URL env > app settings).
  2. For PostgreSQL: DROP SCHEMA public CASCADE; for SQLite: delete the file.
  3. Re-run ``alembic upgrade head`` (canonical migration chain, head = 0008).
  4. Clear Qdrant vector collections and stored objects (MinIO/local storage).
  5. Re-seed the DEMO-PHASE6 forensic evidence set in-process (users, camera,
     video, investigation, forensic evidence + Qdrant points) plus the demo
     admin/investigator accounts and DEMO cameras emitted by the seeder.

The script is safe to run while other components are stopped; start the API
afterwards. DEMO-only resources are used - nothing real is ever created.

Run from ``backend/``::

    python scripts/reset_demo_database.py
    python scripts/reset_demo_database.py --url postgresql+psycopg2://user:pw@host:5432/forensics
    python scripts/reset_demo_database.py --no-seed           # schema + clearing only
    python scripts/reset_demo_database.py --no-clear-storage  # keep stored objects
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)


def _resolve_url(arg_url: str | None) -> str:
    if arg_url:
        return arg_url
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    from app.core.config import settings

    return str(settings.DATABASE_URL)


def _drop_and_recreate(db_url: str) -> None:
    if db_url.startswith("sqlite"):
        # sqlite:///relative.db or sqlite:////abs/path.db
        raw = db_url.split("sqlite:///", 1)[1]
        path = raw if raw.startswith("/") else os.path.join(BACKEND_DIR, raw)
        if os.path.exists(path):
            os.remove(path)
            print(f"[reset] removed SQLite database: {path}")
        else:
            print(f"[reset] no existing SQLite database at {path}")
        return
    if "postgresql" not in db_url:
        raise SystemExit(f"Unsupported database URL scheme for reset: {db_url}")

    import psycopg2

    print("[reset] dropping and recreating schema on PostgreSQL")
    # psycopg2 accepts libpq DSNs / postgresql:// URIs but not the SQLAlchemy
    # "+psycopg2" dialect specifier.
    conn = psycopg2.connect(db_url.replace("postgresql+psycopg2://", "postgresql://"))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
            cur.execute("CREATE SCHEMA public")
            cur.execute("GRANT ALL ON SCHEMA public TO public")
    finally:
        conn.close()


def _alembic_upgrade(db_url: str) -> None:
    cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    print(f"[reset] running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BACKEND_DIR, env=env)
    if result.returncode != 0:
        raise SystemExit("alembic upgrade head failed")


def _clear_vectors_and_storage() -> None:
    from app.ai.qdrant_service import qdrant
    from app.core.config import settings
    from app.storage.service import storage

    for collection in (
        settings.QDRANT_COLLECTION_EVIDENCE,
        settings.QDRANT_COLLECTION_POLICY,
    ):
        qdrant.clear(collection)
        print(f"[reset] cleared Qdrant collection: {collection}  (backend={qdrant.backend_name()})")

    storage.clear_buckets()
    print(f"[reset] cleared stored objects  (backend={storage.backend_name()})")


def _seed() -> None:
    from scripts.seed_demo_evidence import seed_demo_evidence

    manifest = seed_demo_evidence()
    print("[reset] seeded DEMO-PHASE6 forensic evidence:")
    for key, value in manifest.items():
        print(f"  {key}: {value}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset + reseed the demo database")
    parser.add_argument("--url", default=None, help="database URL (overrides DATABASE_URL)")
    parser.add_argument("--no-seed", action="store_true", help="do not reseed demo evidence")
    parser.add_argument("--no-clear-storage", action="store_true", help="keep stored objects")
    args = parser.parse_args()

    db_url = _resolve_url(args.url)
    print(f"[reset] database: {db_url.split('@')[-1]}")

    # Set the env override BEFORE importing any app module so the engine binds to
    # the resolved target even when a different backend/.env DATABASE_URL exists.
    os.environ["DATABASE_URL"] = db_url

    _drop_and_recreate(db_url)
    _alembic_upgrade(db_url)

    if not args.no_clear_storage:
        _clear_vectors_and_storage()

    if not args.no_seed:
        _seed()

    print("[reset] done. Start the backend and verify: python scripts/verify_demo_dataset.py")


if __name__ == "__main__":
    main()