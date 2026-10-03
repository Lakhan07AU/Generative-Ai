"""YOLO inference engine (Phase 2).

Wraps Ultralytics YOLO so the rest of the system depends on a small interface
(Frame -> DetectionEngine.infer -> DetectionFrame) instead of Ultralytics
internals. The engine is deliberately decoupled from WebRTC / the live session:
it only knows how to turn a ``numpy`` BGR frame into a detection frame.

Model loading is centralized and cached per configuration so multiple live
sessions can share one loaded model. Ultralytics inference is serialized with a
lock per engine instance so concurrent sessions never interleave on the same
model (this is the concurrency-safe sharing mechanism required by Phase 2).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, List, Optional

import numpy as np

from app.core.config import settings
from app.detection.schemas import BoundingBox, DetectionFrame, DetectionObject

logger = logging.getLogger(__name__)


class DetectionError(RuntimeError):
    """Generic detection-layer failure (model, inference, conversion)."""


class ModelNotFoundError(DetectionError):
    """The configured YOLO weights file does not exist / is not readable."""


class InvalidFrameError(DetectionError):
    """The frame is not a valid image for YOLO inference."""


class InvalidModelError(DetectionError):
    """The model could not be loaded/validated."""


_PATCH_LOCK = threading.Lock()
_PATCHED = False


def _patch_ultralytics_loading() -> None:
    """Make ultralytics 8.2.x work with torch>=2.6 (``weights_only`` default).

    torch 2.6 flipped ``torch.load`` to ``weights_only=True`` which breaks the
    legacy pickle format used by many YOLO checkpoints. We override it once per
    process (idempotent) so the trusted local model loads reliably.
    """
    global _PATCHED
    if _PATCHED:
        return
    with _PATCH_LOCK:
        if _PATCHED:
            return
        try:
            import torch

            original = torch.load
            if getattr(original, "_forensics_weights_patch", False):
                _PATCHED = True
                return
            try:
                _ = torch.load.__defaults__
            except AttributeError:
                pass

            def _load(weights, *args, **kwargs):
                kwargs.setdefault("weights_only", False)
                return original(weights, *args, **kwargs)

            _load.__name__ = getattr(original, "__name__", "torch_load")
            _load._forensics_weights_patch = True  # type: ignore[attr-defined]
            torch.load = _load
        except Exception as exc:  # pragma: no cover - env dependent
            logger.warning("Failed to patch torch.load for ultralytics: %s", exc)
        _PATCHED = True


class DetectionEngine:
    """A loaded, concurrency-serialized YOLO model instance."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: Optional[float] = None,
        iou_threshold: Optional[float] = None,
        device: Optional[str] = None,
        imgsz: Optional[int] = None,
        max_detections: Optional[int] = None,
    ) -> None:
        self.model_path = model_path or settings.YOLO_MODEL
        self.conf_threshold = conf_threshold if conf_threshold is not None else settings.YOLO_CONF_THRESHOLD
        self.iou_threshold = iou_threshold if iou_threshold is not None else settings.YOLO_IOU_THRESHOLD
        self.device = device or settings.YOLO_DEVICE
        self.imgsz = imgsz or settings.YOLO_IMGSZ
        self.max_detections = max_detections if max_detections is not None else settings.YOLO_MAX_DETECTIONS

        self._model = None
        self._class_names: Dict[int, str] = {}
        self._model_tensor_size = 3
        self._lock = threading.RLock()
        self._validate_and_load()

    # ----------------------------------------------------------------- init

    def model_info(self) -> dict:
        """Describe the REAL loaded model (never infer a device that is unused).

        ``device`` reports what the model actually runs on - when the request is
        CUDA but the loaded torch model is on CPU, ``device`` is reported as
        ``cpu`` so no GPU claim is made without evidence.
        """
        actual_device = "unloaded"
        if self._model is not None:
            try:
                actual_device = str(next(iter(self._model.model.parameters())).device)
            except Exception:  # noqa: BLE001 - introspection is best effort
                actual_device = self.device
        return {
            "model": os.path.basename(self.model_path) if self.model_path else None,
            "model_path": self.model_path,
            "requested_device": self.device,
            "device": actual_device,
            "imgsz": self.imgsz,
            "conf_threshold": self.conf_threshold,
            "iou_threshold": self.iou_threshold,
            "classes": len(self._class_names),
        }

    def _validate_and_load(self) -> None:
        if not self.model_path:
            raise ModelNotFoundError("No YOLO model path configured (YOLO_MODEL is empty)")
        if not _file_exists(self.model_path):
            raise ModelNotFoundError(
                f"YOLO model not found at '{self.model_path}'. "
                "Place your .pt weights there or set YOLO_MODEL, and do NOT download arbitrary models."
            )
        _patch_ultralytics_loading()
        try:
            from ultralytics import YOLO
        except Exception as exc:  # pragma: no cover - env dependent
            self._model = None
            raise DetectionError(f"Ultralytics is not importable: {exc}") from exc

        start = time.monotonic()
        try:
            model = YOLO(self.model_path)
        except Exception as exc:
            raise InvalidModelError(f"Failed to load YOLO model '{self.model_path}': {exc}") from exc
        if model is None or getattr(model, "model", None) is None:
            raise InvalidModelError(f"YOLO model '{self.model_path}' produced no usable model")
        self._model = model
        try:
            self._class_names = dict(model.names or {})
        except Exception:  # pragma: no cover
            self._class_names = {}
        load_ms = (time.monotonic() - start) * 1000.0
        logger.info(
            "Loaded YOLO model path=%s device=%s imgsz=%s classes=%d (load %.0f ms)",
            self.model_path,
            self.device,
            self.imgsz,
            len(self._class_names),
            load_ms,
        )

    # -------------------------------------------------------------- public

    @property
    def class_names(self) -> Dict[int, str]:
        return dict(self._class_names)

    def infer(
        self,
        frame: np.ndarray,
        timestamp: float,
        session_id: Optional[int] = None,
        frame_id: Optional[int] = None,
        camera_id: Optional[int] = None,
    ) -> DetectionFrame:
        """Run detection on a single BGR frame.

        Returns a :class:`DetectionFrame` with zero detections when nothing is
        found. Raises :class:`InvalidFrameError` for bad frames and
        :class:`DetectionError` for inference failures.
        """
        self._assert_model()
        frame = as_bgr_uint8(frame)
        h, w = frame.shape[0], frame.shape[1]
        if h <= 0 or w <= 0:
            raise InvalidFrameError("frame has non-positive dimensions")

        with self._lock:  # serialize inference per engine (shared-model safety)
            start = time.monotonic()
            try:
                results = self._model.predict(
                    source=frame,
                    conf=self.conf_threshold,
                    iou=self.iou_threshold,
                    device=self.device,
                    imgsz=self.imgsz,
                    max_det=self.max_detections,
                    verbose=False,
                )
            except Exception as exc:  # noqa: BLE001
                raise DetectionError(f"Inference failed: {exc}") from exc
            finally:
                infer_ms = (time.monotonic() - start) * 1000.0

        detections: List[DetectionObject] = []
        try:
            result = results[0]
            boxes = result.boxes
            if boxes is not None and len(boxes) > 0:
                xyxy = boxes.xyxy.cpu().numpy()
                confs = boxes.conf.cpu().numpy()
                classes = boxes.cls.cpu().numpy().astype(int)
                for i in range(len(boxes)):
                    x1, y1, x2, y2 = (int(round(v)) for v in xyxy[i])
                    conf = float(confs[i])
                    cls_id = int(classes[i])
                    detections.append(
                        DetectionObject(
                            detection_id=f"{camera_id or ''}-{frame_id or 'x'}-{i}",
                            class_id=cls_id,
                            class_name=self._class_names.get(cls_id, str(cls_id)),
                            confidence=conf,
                            bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                            frame_timestamp=timestamp,
                            session_id=session_id,
                            frame_id=frame_id,
                            camera_id=camera_id,
                            frame_width=w,
                            frame_height=h,
                        )
                    )
        except Exception as exc:  # conversion of raw tensors -> schema
            raise DetectionError(f"Failed to convert inference output: {exc}") from exc

        logger.debug(
            "Detection camera=%s frame=%s timestamp=%.3f detections=%d latency=%.1f ms",
            camera_id,
            frame_id,
            timestamp,
            len(detections),
            infer_ms,
        )
        return DetectionFrame(
            session_id=session_id,
            camera_id=camera_id,
            frame_id=frame_id,
            frame_timestamp=timestamp,
            frame_width=w,
            frame_height=h,
            detections=detections,
        )

    def close(self) -> None:
        self._model = None

    # --------------------------------------------------------------- intern

    def _assert_model(self) -> None:
        if self._model is None:
            raise DetectionError(
                f"Detection engine has no loaded model (path={self.model_path})"
            )


def as_bgr_uint8(frame) -> np.ndarray:
    """Coerce a frame blob into a uint8 3-channel BGR array."""
    if isinstance(frame, np.ndarray):
        arr = frame
    else:
        try:
            arr = np.asarray(frame)
        except Exception as exc:
            raise InvalidFrameError(f"unsupported frame type {type(frame).__name__}") from exc
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    if arr.ndim != 3 or arr.shape[2] not in (3, 4):
        raise InvalidFrameError(f"frame has unsupported shape {arr.shape}")
    if arr.dtype != np.uint8:
        try:
            arr = arr.astype(np.uint8)
        except Exception as exc:
            raise InvalidFrameError(f"frame dtype {arr.dtype} cannot convert to uint8") from exc
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    return arr


def _file_exists(path: str) -> bool:
    return os.path.isfile(path)


# ------------------------------------------------------------------- registry


_ENGINE_REGISTRY: Dict[tuple, DetectionEngine] = {}
_ENGINE_LOCK = threading.Lock()


def get_engine(
    model_path: Optional[str] = None,
    conf_threshold: Optional[float] = None,
    iou_threshold: Optional[float] = None,
    device: Optional[str] = None,
    imgsz: Optional[int] = None,
    max_detections: Optional[int] = None,
) -> DetectionEngine:
    """Return a shared, cached engine for a given configuration.

    Sessions share the same model object (load once) while each session keeps
    its own independent queue/worker/metrics - session isolation is preserved
    by the per-session worker layer.
    """
    key = (
        model_path or settings.YOLO_MODEL,
        conf_threshold if conf_threshold is not None else settings.YOLO_CONF_THRESHOLD,
        iou_threshold if iou_threshold is not None else settings.YOLO_IOU_THRESHOLD,
        device or settings.YOLO_DEVICE,
        imgsz or settings.YOLO_IMGSZ,
        max_detections if max_detections is not None else settings.YOLO_MAX_DETECTIONS,
    )
    with _ENGINE_LOCK:
        engine = _ENGINE_REGISTRY.get(key)
        if engine is not None and engine._model is not None:
            return engine
        engine = DetectionEngine(*key[:1], conf_threshold=key[1], iou_threshold=key[2],
                                 device=key[3], imgsz=key[4], max_detections=key[5])
        _ENGINE_REGISTRY[key] = engine
        return engine


def clear_engines() -> None:
    """Close and drop cached engines (mainly for tests)."""
    with _ENGINE_LOCK:
        for engine in _ENGINE_REGISTRY.values():
            try:
                engine.close()
            except Exception:  # noqa: BLE001
                pass
        _ENGINE_REGISTRY.clear()