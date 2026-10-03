"""Phase 9 - Database backup script.

Creates a consistent snapshot of the configured database without requiring the
API or the containers to be stopped.

  * PostgreSQL: streams ``pg_dump`` (logical backup) to a time-stamped SQL file
    (optionally gzip-compressed). ``pg_dump`` is auto-discovered from PATH or
    the ``PG_DUMP`` environment variable.
  * SQLite: copies the database file (SQLite is safe to copy).

Restore (PostgreSQL):
    psql "$DATABASE_URL" -f backups/forensics-<timestamp>.sql

Run from ``backend/``::

    python scripts/backup_database.py
    python scripts/backup_database.py --out ../backups
    python scripts/backup_database.py --no-compress

Exit codes: 0 = backup written, 1 = backup failed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(BACKEND_DIR, "backups")


def _resolve_url() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    from app.core.config import settings
    return str(settings.DATABASE_URL)


def _find_pg_dump() -> str | None:
    explicit = os.environ.get("PG_DUMP")
    if explicit and shutil.which(explicit):
        return explicit
    return shutil.which("pg_dump")


def _backup_postgres(db_url: str, out_dir: str, compress: bool) -> str:
    pg_dump = _find_pg_dump()
    if pg_dump is None:
        raise SystemExit(
            "pg_dump not found in PATH (set PG_DUMP). Install the PostgreSQL client "
            "tools or use the docker image: docker run --rm ... postgres pg_dump"
        )
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, f"forensics-{ts}.sql")
    if compress:
        path += ".gz"

    # Stream pg_dump out into the file (or the gzip compressor) so huge dumps
    # never sit fully in memory.
    print(f"[backup] using pg_dump: {pg_dump}")
    cmd = [pg_dump, db_url]
    if compress:
        with open(path, "wb") as out:
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as dump:
                gzip = subprocess.Popen(["gzip", "-1"], stdin=dump.stdout, stdout=out)
                assert dump.stdout is not None
                dump.stdout.close()
                _, err = dump.communicate()
                rc = gzip.wait()
                if dump.returncode != 0 or rc != 0:
                    raise SystemExit(f"pg_dump/gzip failed: {err.decode(errors='replace')[:400]}")
    else:
        with open(path, "w", encoding="utf-8", newline="") as out:
            with subprocess.Popen(cmd, stdout=out, stderr=subprocess.PIPE) as dump:
                _, err = dump.communicate()
                if dump.returncode != 0:
                    raise SystemExit(f"pg_dump failed: {err.decode(errors='replace')[:400]}")
    if os.path.getsize(path) == 0:
        raise SystemExit("backup produced an empty file; refusing to keep it")
    print(f"[backup] wrote {path} ({os.path.getsize(path):,} bytes)")
    return path


def _backup_sqlite(db_url: str, out_dir: str) -> str:
    raw = db_url.split("sqlite:///", 1)[1]
    path = raw if raw.startswith("/") else os.path.join(BACKEND_DIR, raw)
    if not os.path.isfile(path):
        raise SystemExit(f"SQLite file not found: {path}")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(out_dir, f"forensics-{ts}-{os.path.basename(path)}")
    shutil.copy2(path, dest)
    print(f"[backup] copied {path} -> {dest} ({os.path.getsize(dest):,} bytes)")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup the demo database")
    parser.add_argument("--url", default=None, help="database URL (overrides DATABASE_URL)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="backup output directory")
    parser.add_argument("--no-compress", action="store_true", help="do not gzip the dump")
    args = parser.parse_args()

    db_url = args.url or _resolve_url()
    os.makedirs(args.out, exist_ok=True)
    print(f"[backup] database: {db_url.split('@')[-1]}")

    if db_url.startswith("sqlite"):
        _backup_sqlite(db_url, args.out)
    elif "postgresql" in db_url:
        _backup_postgres(db_url, args.out, compress=not args.no_compress)
    else:
        raise SystemExit(f"Unsupported database URL scheme: {db_url}")


if __name__ == "__main__":
    main()