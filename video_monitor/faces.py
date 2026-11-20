"""Face detection only (Viola-Jones / Haar), not recognition.

The detector runs once on the capture/processing thread. Viewers never
run their own face check and do not open a camera.

Algorithm (student-explainable classical computer vision):

1. Optionally shrink a copy of the current raw BGR frame
   (configured ``detect_scale``, default 0.5).
2. Convert that copy to grayscale.
3. Run OpenCV's ``CascadeClassifier`` (the classical Viola-Jones Haar
   cascade) using the official ``haarcascade_frontalface_default.xml``.
4. Scale the returned rectangles back to the original frame size.
5. Later in the same processing path, draw green boxes and a
   ``Faces: N`` count on the shared display frame.

This is detection, not recognition: the detector reports bounding
boxes and a count. It does not identify, name, or track people across
frames, and it does not match biometric templates.

Limits: it works best on roughly frontal, well-lit faces. Pose,
occlusion, glasses, scale, and lighting can cause missed detections
or false positives. A count of zero does not prove that no person is
present.

Performance: detection may run on a downscaled copy and/or every Nth
frame. Those values are a configured trade-off so the live stream
stays responsive; they are not a measured camera or browser FPS.
On skipped frames the last boxes are reused until the next detection
runs (or until detection is disabled / the source becomes unusable).

The cascade XML is a project-bundled copy of the official OpenCV
file (Intel Open Source Computer Vision Library license, retained in
the XML header) at ``video_monitor/data/``. If that file is missing,
the loader falls back to ``cv2.data.haarcascades``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from video_monitor.processing import detect_synthetic_source_banner_height

CASCADE_FILENAME = "haarcascade_frontalface_default.xml"
DEFAULT_ENABLED = True
DEFAULT_DETECT_EVERY_N_FRAMES = 2
MIN_DETECT_EVERY_N_FRAMES = 1
MAX_DETECT_EVERY_N_FRAMES = 15
DEFAULT_DETECT_SCALE = 0.5
MIN_DETECT_SCALE = 0.25
MAX_DETECT_SCALE = 1.0
HAAR_SCALE_FACTOR = 1.1
HAAR_MIN_NEIGHBORS = 5
# Minimum window on the image that is actually scanned (the possibly
# downscaled copy). At the default scale of 0.5 this is 60x60 on a
# 640x480 original frame.
HAAR_MIN_SIZE = (30, 30)

# Display overlay (BGR).
BOX_COLOR = (0, 220, 0)
BOX_THICKNESS = 2
COUNT_BADGE_BG = (12, 90, 28)


class FaceConfigError(ValueError):
    """Raised when a face-detection setting is outside the accepted range."""


@dataclass(frozen=True)
class FaceResult:
    enabled: bool
    boxes: tuple[tuple[int, int, int, int], ...]
    count: int
    detection_ran: bool
    reused_previous: bool

    @property
    def boxes_list(self) -> list[tuple[int, int, int, int]]:
        return list(self.boxes)


def validate_detect_every_n_frames(value: object) -> int:
    try:
        if isinstance(value, bool):
            raise TypeError
        every = int(value)
    except (TypeError, ValueError) as exc:
        raise FaceConfigError(
            "face-detect-every must be an integer from "
            f"{MIN_DETECT_EVERY_N_FRAMES} to {MAX_DETECT_EVERY_N_FRAMES}."
        ) from exc
    if not MIN_DETECT_EVERY_N_FRAMES <= every <= MAX_DETECT_EVERY_N_FRAMES:
        raise FaceConfigError(
            "face-detect-every must be an integer from "
            f"{MIN_DETECT_EVERY_N_FRAMES} to {MAX_DETECT_EVERY_N_FRAMES}."
        )
    return every


def validate_detect_scale(value: object) -> float:
    try:
        if isinstance(value, bool):
            raise TypeError
        scale = float(value)
    except (TypeError, ValueError) as exc:
        raise FaceConfigError(
            "face-detect-scale must be a number from "
            f"{MIN_DETECT_SCALE:g} to {MAX_DETECT_SCALE:g}."
        ) from exc
    if not MIN_DETECT_SCALE <= scale <= MAX_DETECT_SCALE:
        raise FaceConfigError(
            "face-detect-scale must be a number from "
            f"{MIN_DETECT_SCALE:g} to {MAX_DETECT_SCALE:g}."
        )
    return scale


def bundled_cascade_path() -> Path:
    return Path(__file__).resolve().parent / "data" / CASCADE_FILENAME


def resolve_cascade_path() -> Path:
    """Prefer the project-bundled official XML, then cv2.data if present."""
    bundled = bundled_cascade_path()
    if bundled.is_file():
        return bundled
    data_dir = getattr(cv2.data, "haarcascades", "") or ""
    fallback = Path(data_dir) / CASCADE_FILENAME
    if fallback.is_file():
        return fallback
    raise FaceConfigError(
        f"Could not find {CASCADE_FILENAME} in the project data folder "
        "or in cv2.data.haarcascades."
    )


def load_cascade(path: Path | None = None) -> tuple[Any, Path]:
    """Load a CascadeClassifier and the path it came from.

    Raises FaceConfigError if the XML cannot be read.
    """
    cascade_path = path or resolve_cascade_path()
    classifier = cv2.CascadeClassifier(str(cascade_path))
    if classifier is None or classifier.empty():
        raise FaceConfigError(
            f"Failed to load Haar cascade from {cascade_path.name}."
        )
    return classifier, Path(cascade_path)


def _scale_boxes_to_original(
    faces: Sequence[Sequence[int]],
    scale: float,
    width: int,
    height: int,
) -> tuple[tuple[int, int, int, int], ...]:
    if scale <= 0:
        scale = 1.0
    boxes: list[tuple[int, int, int, int]] = []
    for item in faces:
        x, y, w, h = (int(v) for v in item[:4])
        x = int(round(x / scale))
        y = int(round(y / scale))
        w = int(round(w / scale))
        h = int(round(h / scale))
        x = max(0, min(width - 1, x))
        y = max(0, min(height - 1, y))
        w = max(1, min(width - x, w))
        h = max(1, min(height - y, h))
        boxes.append((x, y, w, h))
    return tuple(boxes)


def detect_faces_bgr(
    frame: np.ndarray,
    classifier: Any,
    detect_scale: float = DEFAULT_DETECT_SCALE,
) -> tuple[tuple[int, int, int, int], ...]:
    """Run Haar detection on one BGR frame and return original-size boxes."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return ()
    height, width = frame.shape[:2]
    scale = float(detect_scale)
    if scale < 1.0:
        small_w = max(1, int(round(width * scale)))
        small_h = max(1, int(round(height * scale)))
        scanned = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_AREA)
        used_scale = small_w / width if width else scale
    else:
        scanned = frame
        used_scale = 1.0
    if scanned.ndim == 3:
        gray = cv2.cvtColor(scanned, cv2.COLOR_BGR2GRAY)
    else:
        gray = scanned
    faces = classifier.detectMultiScale(
        gray,
        scaleFactor=HAAR_SCALE_FACTOR,
        minNeighbors=HAAR_MIN_NEIGHBORS,
        minSize=HAAR_MIN_SIZE,
    )
    if faces is None or len(faces) == 0:
        return ()
    return _scale_boxes_to_original(faces, used_scale, width, height)


def overlay_face_detections(
    frame: np.ndarray,
    boxes: Sequence[tuple[int, int, int, int]],
    count: int | None = None,
    top_offset: int | None = None,
) -> np.ndarray:
    """Draw face boxes and a Faces: N badge once on the display frame.

    Applied in the capture/processing path, not per viewer. The badge
    sits at the top-left. When a SYNTHETIC SOURCE banner occupies the
    top of the frame, the badge is drawn immediately below that banner
    so the two labels do not overlap. The MOTION badge stays
    top-right and the timestamp stays bottom-right, drawn later so
    they stay readable. Detection behaviour is unchanged.
    """
    if frame is None or frame.size == 0:
        raise ValueError("Cannot overlay face marks on an empty frame.")
    for x, y, w, h in boxes:
        cv2.rectangle(frame, (x, y), (x + w, y + h), BOX_COLOR, BOX_THICKNESS)
    label_count = len(boxes) if count is None else int(count)
    label = f"Faces: {label_count}"
    height, width = frame.shape[:2]
    scale = 0.6 if width >= 480 else 0.45
    thickness = 2
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_w, text_h), baseline = cv2.getTextSize(label, font, scale, thickness)
    pad_x, pad_y = 10, 6
    margin = 8
    if top_offset is None:
        top_offset = detect_synthetic_source_banner_height(frame)
    banner_gap = 4 if top_offset else 0
    x1 = margin
    y1 = margin if not top_offset else int(top_offset) + banner_gap
    y1 = min(max(0, y1), max(0, height - 1))
    x2 = min(width, x1 + text_w + pad_x * 2)
    y2 = min(height, y1 + text_h + baseline + pad_y * 2)
    cv2.rectangle(frame, (x1, y1), (x2, y2), COUNT_BADGE_BG, -1)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 1)
    origin = (x1 + pad_x, y2 - pad_y - baseline)
    cv2.putText(frame, label, origin, font, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(frame, label, origin, font, scale, (255, 255, 255), thickness, cv2.LINE_AA)
    return frame


class FaceDetector:
    """Thread-safe Haar face detector (detection only)."""

    def __init__(
        self,
        enabled: bool = DEFAULT_ENABLED,
        detect_every_n_frames: int = DEFAULT_DETECT_EVERY_N_FRAMES,
        detect_scale: float = DEFAULT_DETECT_SCALE,
        classifier: Any | None = None,
        cascade_path: Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._enabled = bool(enabled)
        self._detect_every_n_frames = validate_detect_every_n_frames(
            detect_every_n_frames
        )
        self._detect_scale = validate_detect_scale(detect_scale)
        self._boxes: tuple[tuple[int, int, int, int], ...] = ()
        self._count = 0
        self._frames_submitted = 0
        self._detections_run = 0
        self._need_detect = True
        self._last_detection_ran = False
        self._reused_previous = False
        self._error: str | None = None
        self._cascade_source = "bundled"
        self._cascade_name = CASCADE_FILENAME
        self._classifier = classifier
        if self._classifier is None:
            try:
                loaded, path = load_cascade(cascade_path)
                self._classifier = loaded
                self._cascade_name = path.name
                bundled = bundled_cascade_path().resolve()
                try:
                    same = path.resolve() == bundled
                except OSError:
                    same = False
                self._cascade_source = "bundled" if same else "cv2.data"
            except FaceConfigError as exc:
                self._classifier = None
                self._error = str(exc)
        else:
            if cascade_path is not None:
                self._cascade_name = Path(cascade_path).name
                self._cascade_source = "provided"

    @classmethod
    def from_config(cls, config: Any) -> FaceDetector:
        return cls(
            enabled=config.face_detection_enabled,
            detect_every_n_frames=config.face_detect_every_n_frames,
            detect_scale=config.face_detect_scale,
        )

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable detection.

        When disabled, no new detections run, held boxes are cleared,
        and the next processed display frame will not show boxes or a
        count badge. Existing configuration is kept. After enabling
        again, the next usable frame is detected immediately.
        """
        with self._lock:
            self._enabled = bool(enabled)
            if not self._enabled:
                self._clear_result_locked()
            else:
                self._need_detect = True

    def note_unusable_frame(self) -> None:
        """Call when the capture path has no usable video frame.

        Clears held boxes so a later recovery does not draw stale
        rectangles, and does not invent detections.
        """
        with self._lock:
            self._clear_result_locked()
            self._need_detect = True

    def process(self, frame: np.ndarray | None) -> FaceResult:
        """Detect (or reuse boxes) on one raw frame.

        Safe to call with None or an empty array: no crash, no boxes.
        """
        with self._lock:
            if not self._enabled:
                return FaceResult(
                    enabled=False,
                    boxes=(),
                    count=0,
                    detection_ran=False,
                    reused_previous=False,
                )
            if frame is None or getattr(frame, "size", 0) == 0:
                self._clear_result_locked()
                self._need_detect = True
                return FaceResult(
                    enabled=True,
                    boxes=(),
                    count=0,
                    detection_ran=False,
                    reused_previous=False,
                )
            if self._classifier is None:
                self._clear_result_locked()
                return FaceResult(
                    enabled=True,
                    boxes=(),
                    count=0,
                    detection_ran=False,
                    reused_previous=False,
                )

            self._frames_submitted += 1
            should_run = self._need_detect or (
                (self._frames_submitted - 1) % self._detect_every_n_frames == 0
            )
            if should_run:
                try:
                    boxes = detect_faces_bgr(
                        frame, self._classifier, self._detect_scale
                    )
                except Exception as exc:  # noqa: BLE001 — keep the capture loop alive
                    self._error = f"Face detection failed: {exc}"
                    self._clear_result_locked()
                    self._need_detect = True
                    return FaceResult(
                        enabled=True,
                        boxes=(),
                        count=0,
                        detection_ran=False,
                        reused_previous=False,
                    )
                self._boxes = boxes
                self._count = len(boxes)
                self._detections_run += 1
                self._need_detect = False
                self._last_detection_ran = True
                self._reused_previous = False
                self._error = None
                return FaceResult(
                    enabled=True,
                    boxes=self._boxes,
                    count=self._count,
                    detection_ran=True,
                    reused_previous=False,
                )

            self._last_detection_ran = False
            self._reused_previous = True
            return FaceResult(
                enabled=True,
                boxes=self._boxes,
                count=self._count,
                detection_ran=False,
                reused_previous=True,
            )

    def status_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "mode": "detection",
                "recognition": False,
                "algorithm": "Viola-Jones Haar cascade",
                "cascade_name": self._cascade_name,
                "cascade_source": self._cascade_source,
                "cascade_loaded": self._classifier is not None,
                "detected_count": self._count if self._enabled else 0,
                "detected_count_definition": (
                    "Number of Haar bounding boxes on the current processed "
                    "display frame. When detection runs every Nth frame, this "
                    "is the most recent detection result (boxes may be reused "
                    "until the next detection). It is not an identity, not a "
                    "track ID, and not recognition."
                ),
                "reused_previous_detection": self._reused_previous if self._enabled else False,
                "detect_every_n_frames": self._detect_every_n_frames,
                "detect_scale": self._detect_scale,
                "performance_strategy": (
                    "Detection runs on a downscaled grayscale copy and only "
                    "every Nth frame (configured trade-off, not a measured "
                    "camera or browser FPS). Held boxes are reused on skipped "
                    "frames so the live stream stays responsive."
                ),
                "haar_scale_factor": HAAR_SCALE_FACTOR,
                "haar_min_neighbors": HAAR_MIN_NEIGHBORS,
                "haar_min_size": list(HAAR_MIN_SIZE),
                "frames_submitted": self._frames_submitted,
                "detections_run": self._detections_run,
                "frames_submitted_definition": (
                    "Count of valid frames submitted to the detector while "
                    "it was enabled. Not a frame rate and not a browser FPS."
                ),
                "error": self._error,
            }

    def _clear_result_locked(self) -> None:
        self._boxes = ()
        self._count = 0
        self._last_detection_ran = False
        self._reused_previous = False
