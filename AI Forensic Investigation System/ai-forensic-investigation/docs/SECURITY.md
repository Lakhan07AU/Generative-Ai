# SECURITY.md — security model and guardrails

## 1. Design guardrails (non-negotiable)

- **No facial recognition, no name/biometric identification** — ever. Objects
  are tracked as opaque `Person-001` style ids only.
- **No human-intent inference.** The system reports behavior, not motive.
- **Latent anti-hallucination:** no invented timestamps; every timeline/finding
  carries `evidence_ids`; simulation-mode AI output is labeled as simulation.
  An unanswerable run reports `UNANSWERED` rather than fabricating.
- **Evidence immutability:** original uploaded videos are stored with MinIO
  object locking (COMPLIANCE mode) where configured.

## 2. Authentication & authorization

- Passwords are hashed (`hash_password` / PBKDF2-family) — never stored raw.
- JWTs are signed with `SECRET_KEY`; role gates (`ADMIN`, `SECURITY_OFFICER`,
  `INVESTIGATOR`, `REVIEWER`) are enforced in dependency functions.
- **Role checks read the role from the DB row, never from the JWT claim**, so a
  stale token cannot escalate.
- **Login rate limiting** (Phase 9): sliding-window per IP+email,
  5 attempts / 60 s by default; locked identities receive `429` + `Retry-After`.
  In-process — move to a shared store for multi-worker deployments.

## 3. Secrets

- `SECRET_KEY` defaults to a known development value; the backend logs a startup
  warning until you rotate it. Generate:
  `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `.env` files are gitignored; `.env.example` contains placeholders only.

## 4. Input & path security

- The `file` live transport only resolves `video_path` under `DEMO_DATA_DIR`
  (realpath containment check) — directory traversal is rejected 403.
- Login/register emails are lowercased and validated; registration role choices
  are restricted to `VALID_ROLES`.
- Evidence/multi-part uploads are validated before storage.

## 5. Integrity & auditability

- Every forensic conclusion is traceable to evidence ids; findings snapshots are
  stored in `finding_reviews` when a human reviews them.
- Security-relevant events (register, login, logout, live start/stop, VLM
  analysis, investigation runs, report generation) are written to `audit_logs`.
- `scripts/verify_evidence_integrity.py` turns the integrity model into a
  machine check: SHA-256 reconciliation, storage presence, vector-index sync and
  orphaned-reference detection.

## 6. Deployment notes

- Keep backend behind a reverse proxy with:
  - sane body size limits for uploads;
  - TLS termination (all cookies/headers flagged appropriately);
  - equivalent or stricter rate limits if you have multiple workers.
- Run the demo with `LLM_PROVIDER=simulation` for deterministic offline results;
  any real provider requires API keys stored outside the repo.
- Containerize with the provided `docker-compose.yml`; do not publish
  development secrets to shared registries.

## 7. Failure honesty

Backends never pretend: `/health` reports per-component status and which vector/
object backend is in use; missing dependencies surface as
`NOT TESTED - DEPENDENCY UNAVAILABLE` in `run_full_e2e.py`, and unavailable AI
providers degrade to labeled simulation rather than emitting fake confident
answers.