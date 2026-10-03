"""QR camera pairing: single-use, camera+creator-bound device tokens.

A desktop investigator creates a pairing for a camera. Its ``pairing_id`` is
rendered into a QR code (pure-Python ``qrcode`` + Pillow) pointing at the
frontend mobile page. The mobile/camera UI presents the id over the signaling
WebSocket; the signaling path (app/api/live.py) calls :func:`consume_pairing`
which binds the connection to the creator's identity for THIS camera, exactly
once, before ``expires_at``.
"""

import io
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import Camera, CameraPairing, User

# Soft cap on outstanding un-consumed pairings per camera. The oldest valid
# row is rotated out when a new one is created above the cap. This is purely a
# housekeeping bound and never weakens single-use enforcement.
MAX_OUTSTANDING_PAIRINGS = 5


def _new_pairing_id() -> str:
    return uuid.uuid4().hex


def create_pairing(db: Session, camera: Camera, user: User) -> CameraPairing:
    """Create a single-use pairing for ``camera`` owned by ``user``."""
    now = datetime.utcnow()
    pairing = CameraPairing(
        pairing_id=_new_pairing_id(),
        camera_id=camera.id,
        created_by_user_id=user.id,
        expires_at=now + timedelta(seconds=max(1, settings.LIVE_PAIRING_EXPIRE_SECONDS)),
    )
    # Rotate any outstanding pairings beyond the cap (FIFO by id).
    stale = (
        db.query(CameraPairing)
        .filter(CameraPairing.camera_id == camera.id, CameraPairing.consumed_at.is_(None))
        .order_by(CameraPairing.id.asc())
        .all()
    )
    if len(stale) >= MAX_OUTSTANDING_PAIRINGS:
        for old in stale[: len(stale) - (MAX_OUTSTANDING_PAIRINGS - 1)]:
            db.delete(old)
    db.add(pairing)
    db.commit()
    db.refresh(pairing)
    return pairing


def consume_pairing(
    db: Session, pairing_id: str, camera_id: int
) -> Optional[User]:
    """Validate + consume a pairing for ``camera_id``; return the creator.

    Returns ``None`` when the pairing is unknown, expired, already consumed, or
    targets a different camera. Consumption is atomic within the transaction:
    two racing signaling sockets cannot both consume the same pairing.
    """
    pairing = (
        db.query(CameraPairing)
        .filter(CameraPairing.pairing_id == pairing_id)
        .first()
    )
    if pairing is None:
        return None
    if pairing.camera_id != camera_id:
        return None
    if pairing.consumed_at is not None:
        return None
    if pairing.expires_at < datetime.utcnow():
        return None
    pairing.consumed_at = datetime.utcnow()
    db.commit()
    creator = db.query(User).filter(User.id == pairing.created_by_user_id).first()
    return creator


def pairing_url(pairing_id: str, camera_id: int) -> str:
    base = (settings.LIVE_QR_PAIRING_URL_BASE or "http://localhost:3000").rstrip("/")
    return f"{base}/live/mobile?camera_id={camera_id}&pair={pairing_id}"


def render_pairing_qr(content: str) -> bytes:
    """Render ``content`` into a PNG QR code.

    Uses the pure-Python ``qrcode`` encoder for the matrix and Pillow for the
    PNG bytes (both already available in the backend image). Returns bytes;
    raises ``QRError`` if ``qrcode`` is not installed.
    """
    try:
        import qrcode
    except ImportError as exc:  # pragma: no cover - depends on installed image
        raise QRError("qrcode package is not installed") from exc

    qr = qrcode.QRCode(
        version=None, box_size=8, border=4, error_correction=qrcode.constants.ERROR_CORRECT_M
    )
    qr.add_data(content)
    qr.make(fit=True)
    matrix = qr.get_matrix()

    n = len(matrix)
    scale = qr.box_size
    size = n * scale
    from PIL import Image

    img = Image.new("RGB", (size, size), "white")
    pixels = img.load()
    for y, row in enumerate(matrix):
        for x, cell in enumerate(row):
            if cell:
                for dy in range(scale):
                    for dx in range(scale):
                        pixels[x * scale + dx, y * scale + dy] = (0, 0, 0)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class QRError(RuntimeError):
    """Raised when the QR encoder is unavailable."""