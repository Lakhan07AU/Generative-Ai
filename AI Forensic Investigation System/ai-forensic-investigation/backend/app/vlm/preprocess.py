"""Copy-safe image preprocessing for VLM evidence frames (Phase 4).

Input frames are NEVER mutated. Every evidence frame is a freshly encoded JPEG
of a downscaled COPY, capped to a max side length and max byte budget so the
evidence-selection stage really does send the minimal visual data. Duplicate
content (identical bytes) is skipped to save provider tokens/bandwidth.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PreparedFrame:
    frame_id: int
    sequence: int
    timestamp: float
    data: bytes
    width: int
    height: int
    original_width: int
    original_height: int


def _as_bgr(frame) -> Optional[np.ndarray]:
    """Return a BGR numpy copy of a frame, or None when it is not an image."""
    try:
        if frame is None:
            return None
        img = np.asarray(frame)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Frame not array-convertible: %s", exc)
        return None
    if img.ndim not in (2, 3):
        return None
    if img.size == 0:
        return None
    if img.ndim == 2:
        return img
    channels = img.shape[2]
    if channels == 4:
        img = img[:, :, :3]
    elif channels != 3:
        return None
    # Convert RGB -> BGR when the frame is flagged as RGB. Detection frames are
    # already BGR (cv2 convention), so this is a defensive guard only.
    return img


def _downscale_copy(img: np.ndarray, max_side: int) -> np.ndarray:
    import cv2

    if max_side <= 0:
        return img.copy()
    height, width = img.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return img.copy()
    scale = max_side / longest
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)


def encode_frames(
    entries,
    max_side: int = 1280,
    jpeg_quality: int = 80,
    max_bytes: int = 512 * 1024,
) -> Tuple[List[PreparedFrame], int]:
    """Encode buffered frame entries into small JPEG evidence frames.

    Returns ``(prepared, dropped)``. Never mutates the source frames.
    """
    import cv2

    prepared: List[PreparedFrame] = []
    dropped = 0
    seen = set()
    for entry in entries:
        try:
            img = _as_bgr(entry.frame)
            if img is None:
                dropped += 1
                continue
            original_h, original_w = img.shape[:2]
            small = _downscale_copy(img, max_side)
            ok, buf = cv2.imencode(
                ".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)]
            )
            if not ok or buf is None:
                dropped += 1
                continue
            data = buf.tobytes()
            if len(data) > max_bytes:
                dropped += 1
                continue
            digest = hashlib.sha1(data).digest()
            if digest in seen:
                dropped += 1
                continue
            seen.add(digest)
            h, w = small.shape[:2]
            prepared.append(
                PreparedFrame(
                    frame_id=int(entry.sequence),
                    sequence=int(entry.sequence),
                    timestamp=float(entry.timestamp),
                    data=data,
                    width=int(w),
                    height=int(h),
                    original_width=original_w,
                    original_height=original_h,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one bad frame must not abort
            logger.warning("Frame preprocessing failed (seq=%s): %s", getattr(entry, "sequence", "?"), exc)
            dropped += 1
    return prepared, dropped