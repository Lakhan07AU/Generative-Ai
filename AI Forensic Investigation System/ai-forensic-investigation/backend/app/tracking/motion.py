"""Motion features - ALL UNITS ABSOLUTE FRAME PIXELS (documented, no
real-world calibration; visual identifiers only, no biometrics)."""

import math
from typing import List, Optional, Sequence

CENTER_MAX_PX = 8.0
STATIONARY_TOLERANCE_PX = 4.0
MOVING_TOLERANCE_PX = 8.0
STATIONARY_MIN_SECONDS = 20.0
STATIONARY_MIN_FRAMES = 100
REAPPEAR_MIN_HITS = 3
PRESENCE_WINDOW_SECONDS = 60.0


def center_of_bbox(bbox: Sequence[float]) -> List[float]:
    if not bbox or len(bbox) < 4:
        return [0.0, 0.0]
    return [(bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0]


def displacement_px(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) < 2 or len(b) < 2:
        return 0.0
    return round(math.hypot(b[0] - a[0], b[1] - a[1]), 3)


def path_distance_px(centers: Sequence[Sequence[float]]) -> float:
    total = 0.0
    prev = None
    for c in centers:
        if prev is not None:
            total += displacement_px(prev, c)
        prev = c
    return round(total, 3)


def pixel_velocity_px_per_frame(centers: Sequence[Sequence[float]]) -> float:
    if len(centers) < 2:
        return 0.0
    return round(path_distance_px(centers) / (len(centers) - 1), 3)


def stationary_seconds(
    centers: Sequence[Sequence[float]],
    stationary_tolerance_px: float = 4.0,
    fps: float = 5.0,
) -> float:
    if len(centers) < 2 or fps <= 0:
        return 0.0
    frames = sum(
        1
        for i in range(1, len(centers))
        if displacement_px(centers[i - 1], centers[i]) <= stationary_tolerance_px
    )
    return round(frames / fps, 3)


def moving_seconds(
    centers: Sequence[Sequence[float]],
    stationary_tolerance_px: float = 4.0,
    fps: float = 5.0,
) -> float:
    if len(centers) < 2 or fps <= 0:
        return 0.0
    frames = sum(
        1
        for i in range(1, len(centers))
        if displacement_px(centers[i - 1], centers[i]) > stationary_tolerance_px
    )
    return round(frames / fps, 3)


def stationary_ratio(
    centers: Sequence[Sequence[float]],
    stationary_tolerance_px: float = 4.0,
    fps: float = 5.0,
) -> float:
    s = stationary_seconds(centers, stationary_tolerance_px, fps)
    m = moving_seconds(centers, stationary_tolerance_px, fps)
    total = s + m
    if total <= 0:
        return 0.0
    return round(s / total, 3)
