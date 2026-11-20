"""Motion detection: grayscale frame differencing, cooldown, and event log.

The detector runs once on the capture/processing thread. Viewers never
run their own motion check and do not open a camera.

Algorithm (student-explainable):

1. Convert the current and previous frames to grayscale.
2. Apply a 5x5 Gaussian blur to reduce small noise.
3. Take the absolute difference between the two blurred images.
4. A pixel is "changed" if that difference is greater than a pixel
   threshold derived from the sensitivity setting.
5. If the percentage of changed pixels is at least ``min_changed_percent``
   (also derived from sensitivity), the frame is treated as motion.
6. The first usable frame after enable, or after a size change, is only
   a baseline: it is stored and no motion is reported.
7. Event logging is rate-limited by a cooldown (default 2.0 seconds).
   The on-screen MOTION mark follows the current frame comparison and
   is not delayed by the cooldown.

This is not promised false-positive-free. Lighting changes, camera
noise, and auto-exposure can look like motion. Synthetic test lighting
is not real lighting.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

import cv2
import numpy as np

from video_monitor.processing import format_timestamp

MIN_SENSITIVITY = 1
MAX_SENSITIVITY = 100
DEFAULT_SENSITIVITY = 50
DEFAULT_COOLDOWN_SECONDS = 2.0
MIN_COOLDOWN_SECONDS = 0.0
MAX_COOLDOWN_SECONDS = 30.0
DEFAULT_LOG_SIZE = 50
MIN_LOG_SIZE = 5
MAX_LOG_SIZE = 200
GAUSSIAN_KERNEL = (5, 5)

# Sensitivity mapping (higher sensitivity = smaller changes count as motion).
# These endpoints are documented and used by thresholds_for_sensitivity().
PIXEL_THRESHOLD_AT_MIN_SENSITIVITY = 30
PIXEL_THRESHOLD_AT_MAX_SENSITIVITY = 20
MIN_CHANGED_PERCENT_AT_MIN_SENSITIVITY = 4.0
MIN_CHANGED_PERCENT_AT_MAX_SENSITIVITY = 0.20


class MotionConfigError(ValueError):
    """Raised when a motion setting is outside the accepted range."""


@dataclass(frozen=True)
class MotionEvent:
    time_label: str
    message: str
    changed_percent: float
    sensitivity: int
    monotonic_ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "time": self.time_label,
            "message": self.message,
            "changed_percent": self.changed_percent,
            "sensitivity": self.sensitivity,
        }


@dataclass(frozen=True)
class MotionResult:
    enabled: bool
    motion_detected: bool
    event_recorded: bool
    changed_percent: float | None
    pixel_threshold: int
    min_changed_percent: float
    event: MotionEvent | None = None


def thresholds_for_sensitivity(sensitivity: int) -> tuple[int, float]:
    """Return ``(pixel_threshold, min_changed_percent)`` for a sensitivity value.

    Sensitivity is an integer from 1 (least sensitive) to 100 (most
    sensitive). It is a configuration knob, not a measured accuracy.

    At sensitivity 1: pixel difference must be at least 30 gray levels,
    and at least 4.0% of pixels must change.
    At sensitivity 50 (default): pixel threshold 25, min changed area
    about 2.12%.
    At sensitivity 100: pixel threshold 20, min changed area 0.20%.
    """
    sensitivity = validate_sensitivity(sensitivity)
    span = MAX_SENSITIVITY - MIN_SENSITIVITY
    t = (sensitivity - MIN_SENSITIVITY) / span
    pixel_threshold = int(
        round(
            PIXEL_THRESHOLD_AT_MIN_SENSITIVITY
            + t
            * (
                PIXEL_THRESHOLD_AT_MAX_SENSITIVITY
                - PIXEL_THRESHOLD_AT_MIN_SENSITIVITY
            )
        )
    )
    min_changed_percent = (
        MIN_CHANGED_PERCENT_AT_MIN_SENSITIVITY
        + t
        * (
            MIN_CHANGED_PERCENT_AT_MAX_SENSITIVITY
            - MIN_CHANGED_PERCENT_AT_MIN_SENSITIVITY
        )
    )
    return pixel_threshold, min_changed_percent


def validate_sensitivity(value: object) -> int:
    try:
        if isinstance(value, bool):
            raise TypeError
        sensitivity = int(value)
    except (TypeError, ValueError) as exc:
        raise MotionConfigError(
            f"sensitivity must be an integer from {MIN_SENSITIVITY} to {MAX_SENSITIVITY}."
        ) from exc
    if not MIN_SENSITIVITY <= sensitivity <= MAX_SENSITIVITY:
        raise MotionConfigError(
            f"sensitivity must be an integer from {MIN_SENSITIVITY} to {MAX_SENSITIVITY}."
        )
    return sensitivity


def validate_cooldown(value: object) -> float:
    try:
        if isinstance(value, bool):
            raise TypeError
        cooldown = float(value)
    except (TypeError, ValueError) as exc:
        raise MotionConfigError(
            f"motion cooldown must be between {MIN_COOLDOWN_SECONDS:g} and "
            f"{MAX_COOLDOWN_SECONDS:g} seconds."
        ) from exc
    if not MIN_COOLDOWN_SECONDS <= cooldown <= MAX_COOLDOWN_SECONDS:
        raise MotionConfigError(
            f"motion cooldown must be between {MIN_COOLDOWN_SECONDS:g} and "
            f"{MAX_COOLDOWN_SECONDS:g} seconds."
        )
    return cooldown


def validate_log_size(value: object) -> int:
    try:
        if isinstance(value, bool):
            raise TypeError
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise MotionConfigError(
            f"motion log size must be between {MIN_LOG_SIZE} and {MAX_LOG_SIZE}."
        ) from exc
    if not MIN_LOG_SIZE <= size <= MAX_LOG_SIZE:
        raise MotionConfigError(
            f"motion log size must be between {MIN_LOG_SIZE} and {MAX_LOG_SIZE}."
        )
    return size


def _to_blurred_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    return cv2.GaussianBlur(gray, GAUSSIAN_KERNEL, 0)


def overlay_motion_indicator(frame: np.ndarray) -> np.ndarray:
    """Draw a MOTION badge once on the display frame (top-right).

    Applied in the capture/processing path, not per viewer. Placed on
    the top-right so it does not cover the synthetic-source banner
    check region (top-left) or the timestamp (bottom-right).
    """
    if frame is None or frame.size == 0:
        raise ValueError("Cannot overlay a motion mark on an empty frame.")
    height, width = frame.shape[:2]
    label = "MOTION"
    scale = 0.7 if width >= 480 else 0.5
    thickness = 2
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_w, text_h), baseline = cv2.getTextSize(label, font, scale, thickness)
    pad_x, pad_y = 10, 6
    margin = 8
    box_w = text_w + pad_x * 2
    box_h = text_h + baseline + pad_y * 2
    x2 = width - margin
    y1 = margin
    x1 = max(0, x2 - box_w)
    y2 = min(height, y1 + box_h)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 220), -1)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 1)
    origin = (x1 + pad_x, y2 - pad_y - baseline)
    cv2.putText(
        frame, label, origin, font, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA
    )
    cv2.putText(
        frame, label, origin, font, scale, (255, 255, 255), thickness, cv2.LINE_AA
    )
    return frame


def render_static_synthetic_scene(width: int, height: int, frame_index: int = 0) -> np.ndarray:
    """A reasonably static test scene. Pixels do not depend on frame_index.

    Used in automated tests. Synthetic lighting is not real lighting, so
    a quiet result here does not prove zero false positives on a webcam.
    """
    del frame_index  # reserved so the signature matches a moving scene
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = (42, 48, 40)
    cv2.rectangle(frame, (20, 20), (110, 90), (200, 200, 200), -1)
    cv2.putText(
        frame,
        "STATIC SCENE",
        (16, height - 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6 if width >= 480 else 0.45,
        (220, 220, 220),
        1,
        cv2.LINE_AA,
    )
    return frame


def render_motion_synthetic_scene(width: int, height: int, frame_index: int) -> np.ndarray:
    """A deliberate-motion test scene: a large bright box jumps each frame.

    The moving box is about one-quarter of the width and one-third of the
    height, and it steps far enough that the changed-pixel percentage is
    well above the default sensitivity threshold.
    """
    frame = render_static_synthetic_scene(width, height, frame_index)
    box_w = max(40, width // 4)
    box_h = max(40, height // 3)
    margin = 10
    travel = max(1, width - box_w - 2 * margin)
    step = max(box_w // 2, width // 8)
    x = margin + (int(frame_index) * step) % travel
    y = max(margin, height // 3)
    if y + box_h >= height - margin:
        y = max(margin, height - box_h - margin)
    cv2.rectangle(frame, (x, y), (x + box_w, y + box_h), (0, 255, 255), -1)
    cv2.putText(
        frame,
        "MOTION SCENE",
        (16, height - 40 if height >= 80 else height - 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6 if width >= 480 else 0.45,
        (0, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return frame


class MotionDetector:
    """Thread-safe motion detector with a bounded event log."""

    def __init__(
        self,
        enabled: bool = True,
        sensitivity: int = DEFAULT_SENSITIVITY,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        max_events: int = DEFAULT_LOG_SIZE,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._enabled = bool(enabled)
        self._sensitivity = validate_sensitivity(sensitivity)
        self._cooldown_seconds = validate_cooldown(cooldown_seconds)
        self._max_events = validate_log_size(max_events)
        self._events: deque[MotionEvent] = deque(maxlen=self._max_events)
        self._previous_gray: np.ndarray | None = None
        self._currently_detected = False
        self._frames_checked = 0
        self._events_recorded_total = 0
        self._last_event_monotonic: float | None = None
        self._cooldown_cleared = True
        self._time_fn = time_fn or time.monotonic

    @classmethod
    def from_config(cls, config: Any) -> MotionDetector:
        return cls(
            enabled=config.motion_enabled,
            sensitivity=config.motion_sensitivity,
            cooldown_seconds=config.motion_cooldown_seconds,
            max_events=config.motion_log_size,
        )

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable detection.

        When disabled, no new events are recorded, the current-detection
        flag is cleared (the MOTION badge stops on the next processed
        frame), the previous-frame baseline is discarded, and the
        cooldown is cleared. Existing log entries are kept. After
        enabling again, the next usable frame becomes a fresh baseline
        (no event), and a later moving frame can be logged immediately
        because the cooldown was cleared.
        """
        with self._lock:
            self._enabled = bool(enabled)
            if not self._enabled:
                self._currently_detected = False
                self._previous_gray = None
                self._last_event_monotonic = None
                self._cooldown_cleared = True

    def set_sensitivity(self, sensitivity: int) -> None:
        with self._lock:
            self._sensitivity = validate_sensitivity(sensitivity)

    def note_unusable_frame(self) -> None:
        """Call when the capture path has no usable video frame.

        Clears the current-detection flag and the baseline so a later
        recovery does not compare a live frame against a stale image.
        Does not invent motion events.
        """
        with self._lock:
            self._currently_detected = False
            self._previous_gray = None

    def process(self, frame: np.ndarray | None) -> MotionResult:
        """Compare one frame against the previous baseline.

        Safe to call with None or an empty array: no crash, no event.
        """
        with self._lock:
            pixel_threshold, min_changed_percent = thresholds_for_sensitivity(
                self._sensitivity
            )
            if not self._enabled:
                return MotionResult(
                    enabled=False,
                    motion_detected=False,
                    event_recorded=False,
                    changed_percent=None,
                    pixel_threshold=pixel_threshold,
                    min_changed_percent=min_changed_percent,
                )
            if frame is None or getattr(frame, "size", 0) == 0:
                self._currently_detected = False
                self._previous_gray = None
                return MotionResult(
                    enabled=True,
                    motion_detected=False,
                    event_recorded=False,
                    changed_percent=None,
                    pixel_threshold=pixel_threshold,
                    min_changed_percent=min_changed_percent,
                )

            gray = _to_blurred_gray(frame)
            self._frames_checked += 1
            if (
                self._previous_gray is None
                or self._previous_gray.shape != gray.shape
            ):
                self._previous_gray = gray
                self._currently_detected = False
                return MotionResult(
                    enabled=True,
                    motion_detected=False,
                    event_recorded=False,
                    changed_percent=None,
                    pixel_threshold=pixel_threshold,
                    min_changed_percent=min_changed_percent,
                )

            delta = cv2.absdiff(self._previous_gray, gray)
            self._previous_gray = gray
            changed = int(np.count_nonzero(delta > pixel_threshold))
            total = int(delta.size)
            changed_percent = (100.0 * changed / total) if total else 0.0
            motion = changed_percent >= min_changed_percent
            self._currently_detected = motion
            event = None
            recorded = False
            if motion and self._cooldown_allows_event():
                event = self._record_event(changed_percent)
                recorded = True
            return MotionResult(
                enabled=True,
                motion_detected=motion,
                event_recorded=recorded,
                changed_percent=round(changed_percent, 2),
                pixel_threshold=pixel_threshold,
                min_changed_percent=round(min_changed_percent, 2),
                event=event,
            )

    def events(self) -> list[MotionEvent]:
        with self._lock:
            return list(self._events)

    def status_dict(self) -> dict[str, Any]:
        with self._lock:
            pixel_threshold, min_changed_percent = thresholds_for_sensitivity(
                self._sensitivity
            )
            last_event = self._events[-1] if self._events else None
            return {
                "enabled": self._enabled,
                "sensitivity": self._sensitivity,
                "sensitivity_scale": (
                    f"{MIN_SENSITIVITY} (least sensitive) to "
                    f"{MAX_SENSITIVITY} (most sensitive); "
                    "higher values treat smaller changes as motion"
                ),
                "pixel_threshold": pixel_threshold,
                "min_changed_percent": round(min_changed_percent, 2),
                "cooldown_seconds": self._cooldown_seconds,
                "currently_detected": self._currently_detected,
                "last_event_at": last_event.time_label if last_event else None,
                "log_count": len(self._events),
                "log_capacity": self._max_events,
                "frames_checked": self._frames_checked,
                "events_recorded_total": self._events_recorded_total,
                "events": [item.as_dict() for item in self._events],
                "frames_checked_definition": (
                    "Count of valid frames submitted to the detector while "
                    "it was enabled (including the baseline frame). Not a "
                    "frame rate and not a browser FPS."
                ),
                "events_recorded_total_definition": (
                    "Count of events accepted this session, including those "
                    "later dropped from the bounded log."
                ),
                "currently_detected_definition": (
                    "Result of the most recent frame-to-frame comparison, "
                    "not a measured duration."
                ),
            }

    def _cooldown_allows_event(self) -> bool:
        if self._last_event_monotonic is None or self._cooldown_cleared:
            return True
        elapsed = self._time_fn() - self._last_event_monotonic
        return elapsed >= self._cooldown_seconds

    def _record_event(self, changed_percent: float) -> MotionEvent:
        rounded = round(changed_percent, 2)
        event = MotionEvent(
            time_label=format_timestamp(),
            message=f"Motion detected ({rounded:.1f}% of pixels changed)",
            changed_percent=rounded,
            sensitivity=self._sensitivity,
            monotonic_ts=self._time_fn(),
        )
        self._events.append(event)
        self._events_recorded_total += 1
        self._last_event_monotonic = event.monotonic_ts
        self._cooldown_cleared = False
        return event
