"""Manual video recording from the shared display-frame path.

Recording does not open a second camera. When a session is active, the
capture thread offers the same BGR display frames that are about to be
JPEG-encoded for the live MJPEG stream. Timestamp text and the MOTION
badge that are already drawn on those frames may therefore appear in the
saved file.

Live viewing and file recording are documented separately:

- Live view: MJPEG over HTTP (multipart/x-mixed-replace carrying JPEG
  images). That is not H.264, H.265, or WebRTC.
- Recording (this module, verified on the Linux development box):
  Motion JPEG (OpenCV fourcc MJPG) inside an AVI container. The writer
  FPS is the configured container timestamp rate, not a measured
  capture rate. Windows codec availability has not been verified.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import cv2
import numpy as np

_FILENAME_TZ = ZoneInfo("Asia/Hong_Kong")

# recording_YYYYMMDD_HHMMSS_<8 lowercase hex chars>.avi
SAFE_FILENAME_PATTERN = re.compile(r"^recording_\d{8}_\d{6}_[0-9a-f]{8}\.avi$")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDING_DIR = PROJECT_ROOT / "data" / "recordings"

# Preferred first: MJPG in AVI was verified on this Linux box (OpenCV
# 5.0.0 + ffprobe: codec_name=mjpeg, 640x480, 15 FPS, all written
# frames readable). It is also a common OpenCV writer choice on Windows,
# but that runtime has not been tested yet. XVID/AVI was also playable
# here and is a same-container fallback if MJPG fails to open.
PREFERRED_CODEC = "MJPG"
PREFERRED_CODEC_NAME = "Motion JPEG"
PREFERRED_CONTAINER = "AVI"
PREFERRED_EXTENSION = ".avi"


@dataclass(frozen=True)
class WriterCandidate:
    fourcc: str
    extension: str
    codec_name: str
    container: str


WRITER_CANDIDATES: tuple[WriterCandidate, ...] = (
    WriterCandidate("MJPG", ".avi", "Motion JPEG", "AVI"),
    WriterCandidate("XVID", ".avi", "MPEG-4 Part 2 (XVID)", "AVI"),
)

WriterFactory = Callable[[str, str, float, tuple[int, int]], Any]


class RecordingError(Exception):
    """A recording could not be started, stopped, or finalised."""

    status_code = 500


class RecordingConflict(RecordingError):
    """Start or stop was requested in a state that does not allow it."""

    status_code = 409


class RecordingUnavailable(RecordingError):
    """No display frame is available yet, so the writer size is unknown."""

    status_code = 503


def is_safe_recording_filename(name: str) -> bool:
    """Return True only for a server-generated recording basename."""
    if not isinstance(name, str) or not name or name != name.strip():
        return False
    if any(sep in name for sep in ("/", "\\", ":", "\x00")):
        return False
    if name.startswith(".") or ".." in name:
        return False
    return SAFE_FILENAME_PATTERN.fullmatch(name) is not None


def resolve_under_directory(directory: Path, filename: str) -> Path:
    """Resolve an allowlisted recording name under directory, or raise."""
    if not is_safe_recording_filename(filename):
        raise RecordingError("Invalid recording filename.")
    root = Path(directory).resolve()
    candidate = (root / filename).resolve()
    if not candidate.is_relative_to(root) or candidate.parent != root:
        raise RecordingError("Recording path is outside the recording directory.")
    return candidate


def default_writer_factory(
    path: str, fourcc: str, fps: float, size: tuple[int, int]
) -> Any:
    """Open an OpenCV VideoWriter. The caller must check isOpened()."""
    if not isinstance(fourcc, str) or len(fourcc) != 4:
        raise RecordingError("Internal error: FOURCC must be four characters.")
    code = cv2.VideoWriter_fourcc(*fourcc)
    return cv2.VideoWriter(str(path), code, float(fps), (int(size[0]), int(size[1])))


def _unlink_quietly(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _format_hkt(when: datetime | None = None) -> str:
    moment = when or datetime.now(_FILENAME_TZ)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_FILENAME_TZ)
    else:
        moment = moment.astimezone(_FILENAME_TZ)
    return moment.strftime("%Y-%m-%d %H:%M:%S HKT")


def validate_recorded_file(
    path: Path,
    *,
    expected_width: int,
    expected_height: int,
    expected_min_frames: int = 1,
    expected_max_frames: int | None = None,
) -> dict[str, Any]:
    """Open a finished file and confirm it contains frames.

    Returns a dict of observed properties. Raises RecordingError if the
    file is missing, unreadable, empty, or has the wrong frame size.
    """
    if not path.is_file() or path.stat().st_size <= 0:
        raise RecordingError(
            "The recording file is missing or empty after stop. "
            "It was not saved as a successful recording."
        )

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise RecordingError(
                "The recording file could not be opened after stop. "
                "It was not saved as a successful recording."
            )
        reported_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        reported_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        reported_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = 0
        first_shape: tuple[int, int] | None = None
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frames += 1
            if first_shape is None:
                first_shape = (int(frame.shape[1]), int(frame.shape[0]))
    finally:
        cap.release()

    if frames < expected_min_frames:
        raise RecordingError(
            "The recording file could not be validated after stop "
            f"(readable frames: {frames}). It was not saved as a successful recording."
        )
    if expected_max_frames is not None and frames > expected_max_frames:
        raise RecordingError(
            "The recording file frame count is unexpectedly large "
            f"({frames} frames). It was not saved as a successful recording."
        )

    observed_width, observed_height = first_shape or (reported_width, reported_height)
    if observed_width != expected_width or observed_height != expected_height:
        raise RecordingError(
            "The recording file resolution does not match the frames that "
            f"were written ({observed_width}x{observed_height}, expected "
            f"{expected_width}x{expected_height})."
        )

    return {
        "path": path,
        "filename": path.name,
        "frames": frames,
        "width": observed_width,
        "height": observed_height,
        "reported_width": reported_width,
        "reported_height": reported_height,
        "reported_fps": reported_fps,
        "size_bytes": path.stat().st_size,
    }


class RecordingManager:
    """Thread-safe manual recorder that consumes already-processed display frames."""

    def __init__(
        self,
        directory: Path | str,
        *,
        writer_fps: float,
        writer_factory: WriterFactory | None = None,
        candidates: Sequence[WriterCandidate] | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.writer_fps = float(writer_fps)
        self._writer_factory = writer_factory or default_writer_factory
        self._candidates = tuple(candidates or WRITER_CANDIDATES)
        self._lock = threading.Lock()
        self._writer: Any | None = None
        self._state = "idle"
        self._error: str | None = None
        self._filename: str | None = None
        self._last_filename: str | None = None
        self._started_at_label: str | None = None
        self._started_monotonic: float | None = None
        self._frames_written = 0
        self._width = 0
        self._height = 0
        self._codec: str | None = None
        self._codec_name: str | None = None
        self._container: str | None = None
        self._writer_released = True
        # The directory is created on start(), not at construction, so
        # merely launching the app or a test capture does not write files.

    def ensure_directory(self) -> Path:
        path = Path(self.directory)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RecordingError("Could not create the recording directory.") from exc
        resolved = path.resolve()
        if not resolved.is_dir():
            raise RecordingError("The recording path exists and is not a directory.")
        self.directory = resolved
        return resolved

    def start(self, *, width: int, height: int) -> dict[str, Any]:
        """Open a writer under the controlled directory. No client path is used."""
        width = int(width)
        height = int(height)
        if width <= 0 or height <= 0:
            raise RecordingUnavailable(
                "No video frame is available yet. Wait for the stream to start, then try again."
            )

        with self._lock:
            if self._state == "recording" and self._writer is not None:
                raise RecordingConflict(
                    "A recording is already in progress. Stop it before starting another."
                )
            self.ensure_directory()
            filename, path = self._allocate_filename()
            writer, candidate, opened_path, attempts = self._open_writer(
                path, width, height
            )
            if writer is None:
                self._set_error_locked(
                    "Could not start a video writer on this computer. "
                    + " ".join(attempts)
                    + " No recording file was kept as a success. "
                    "The live MJPEG stream is separate from file recording."
                )
                raise RecordingError(self._error or "Could not start a video writer.")

            self._writer = writer
            self._writer_released = False
            self._state = "recording"
            self._error = None
            self._filename = opened_path.name
            self._last_filename = None
            self._started_at_label = _format_hkt()
            self._started_monotonic = time.monotonic()
            self._frames_written = 0
            self._width = width
            self._height = height
            self._codec = candidate.fourcc
            self._codec_name = candidate.codec_name
            self._container = candidate.container
            return self._status_unlocked()

    def stop(self) -> dict[str, Any]:
        """Release the writer and validate that a playable file was produced."""
        with self._lock:
            if self._state != "recording" or self._writer is None:
                raise RecordingConflict("No recording is in progress.")
            writer = self._writer
            path = self.directory / (self._filename or "")
            expected_width = self._width
            expected_height = self._height
            frames_written = self._frames_written
            self._writer = None

        released = self._release_writer(writer)

        min_frames = 1
        try:
            if frames_written < 1:
                raise RecordingError(
                    "Recording stopped before any frame was written. "
                    "No playable file was saved as a success."
                )
            if not released:
                raise RecordingError(
                    "The video writer could not be released cleanly. "
                    "The file was not saved as a successful recording."
                )
            info = validate_recorded_file(
                path,
                expected_width=expected_width,
                expected_height=expected_height,
                expected_min_frames=min_frames,
            )
        except RecordingError as exc:
            _unlink_if_empty_or_unreadable(path)
            with self._lock:
                self._writer_released = True
                self._set_error_locked(str(exc))
                self._filename = None
            raise

        with self._lock:
            self._writer_released = True
            self._state = "idle"
            self._error = None
            self._last_filename = info["filename"]
            self._filename = None
            self._started_monotonic = None
            status = self._status_unlocked()
            status["validated_frames"] = info["frames"]
            status["size_bytes"] = info["size_bytes"]
            return status

    def shutdown(self) -> dict[str, Any] | None:
        """Stop an active recording on process shutdown, or no-op if idle.

        If a session is running, this finalises the file or records a
        clear error. The writer is always released.
        """
        with self._lock:
            active = self._state == "recording" and self._writer is not None
        if not active:
            self._force_release()
            return None
        try:
            return self.stop()
        except RecordingError:
            self._force_release()
            return None

    def write_frame(self, frame: np.ndarray) -> None:
        """Write one display frame if a session is active. Never opens a camera.

        Failures set the error state and release the writer. Exceptions are
        swallowed so the live capture loop is not interrupted.
        """
        with self._lock:
            if self._state != "recording" or self._writer is None:
                return
            writer = self._writer
            width = self._width
            height = self._height

        try:
            prepared = _prepare_writer_frame(frame, width, height)
            writer.write(prepared)
        except Exception as exc:  # noqa: BLE001 — keep the capture loop alive
            self._fail_active_writer(
                f"Recording stopped because a frame could not be written: {exc}"
            )
            return

        with self._lock:
            if self._writer is writer and self._state == "recording":
                self._frames_written += 1

    def status_dict(self) -> dict[str, Any]:
        with self._lock:
            return self._status_unlocked()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def writer_released(self) -> bool:
        with self._lock:
            return self._writer_released and self._writer is None

    def _status_unlocked(self) -> dict[str, Any]:
        elapsed = None
        if self._state == "recording" and self._started_monotonic is not None:
            elapsed = round(time.monotonic() - self._started_monotonic, 3)
        current_name = self._filename if self._state == "recording" else None
        display_name = current_name or self._last_filename
        return {
            "state": self._state,
            "recording": self._state == "recording",
            "filename": display_name,
            "current_filename": current_name,
            "last_filename": self._last_filename,
            "started_at": self._started_at_label if self._state == "recording" else (
                self._started_at_label if self._last_filename else None
            ),
            "elapsed_seconds": elapsed,
            "frames_written": self._frames_written,
            "width": self._width or None,
            "height": self._height or None,
            "writer_fps": self.writer_fps,
            "writer_fps_meaning": (
                "Configured writer/container timestamp rate, not a measured capture rate."
            ),
            "codec": self._codec,
            "codec_name": self._codec_name,
            "container": self._container,
            "preferred_codec": PREFERRED_CODEC,
            "preferred_codec_name": PREFERRED_CODEC_NAME,
            "preferred_container": PREFERRED_CONTAINER,
            "error": self._error,
        }

    def _allocate_filename(self) -> tuple[str, Path]:
        moment = datetime.now(_FILENAME_TZ)
        stamp = moment.strftime("%Y%m%d_%H%M%S")
        for _ in range(32):
            name = f"recording_{stamp}_{secrets.token_hex(4)}.avi"
            path = self.directory / name
            if not path.exists():
                return name, path
        raise RecordingError("Could not allocate a unique recording filename.")

    def _open_writer(
        self, preferred_path: Path, width: int, height: int
    ) -> tuple[Any | None, WriterCandidate | None, Path, list[str]]:
        attempts: list[str] = []
        size = (width, height)
        fps = self.writer_fps
        # Keep the allocated basename; only the extension may change with
        # a fallback candidate (both current candidates use .avi).
        stem = preferred_path.stem
        for candidate in self._candidates:
            path = self.directory / f"{stem}{candidate.extension}"
            writer = None
            try:
                writer = self._writer_factory(str(path), candidate.fourcc, fps, size)
            except Exception as exc:  # noqa: BLE001 — try the next candidate
                _unlink_quietly(path)
                attempts.append(
                    f"{candidate.fourcc}/{candidate.container} failed to open ({exc})."
                )
                continue
            if writer is not None and bool(writer.isOpened()):
                return writer, candidate, path, attempts
            self._release_writer(writer)
            _unlink_quietly(path)
            attempts.append(
                f"{candidate.fourcc} in a {candidate.container} container "
                f"({path.suffix}) was not available (VideoWriter.isOpened() was false)."
            )
        return None, None, preferred_path, attempts

    def _set_error_locked(self, message: str) -> None:
        self._state = "error"
        self._error = message
        self._filename = None
        self._started_monotonic = None

    def _fail_active_writer(self, message: str) -> None:
        with self._lock:
            writer = self._writer
            self._writer = None
            self._writer_released = False
            self._set_error_locked(message)
        self._release_writer(writer)
        with self._lock:
            self._writer_released = True

    def _force_release(self) -> None:
        with self._lock:
            writer = self._writer
            self._writer = None
            was_recording = self._state == "recording"
            if was_recording and self._error is None:
                self._set_error_locked(
                    "Recording was interrupted and could not be finalised cleanly."
                )
        if writer is not None:
            self._release_writer(writer)
        with self._lock:
            self._writer_released = True

    def _release_writer(self, writer: Any | None) -> bool:
        if writer is None:
            return True
        try:
            writer.release()
            return True
        except Exception:  # noqa: BLE001 — release must not raise
            return False


def _unlink_if_empty_or_unreadable(path: Path) -> None:
    try:
        if not path.exists():
            return
        if path.stat().st_size <= 0:
            path.unlink()
            return
        cap = cv2.VideoCapture(str(path))
        try:
            opened = cap.isOpened()
            ok, frame = cap.read() if opened else (False, None)
        finally:
            cap.release()
        if not opened or not ok or frame is None:
            # Leave a non-empty but unreadable file only if unlink fails.
            # A truncated leftover must not be presented as success; we
            # still try to remove obviously unplayable results.
            path.unlink()
    except OSError:
        pass


def _prepare_writer_frame(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    if frame is None or getattr(frame, "size", 0) == 0:
        raise RecordingError("Cannot write an empty frame.")
    image = frame
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    elif image.ndim != 3 or image.shape[2] != 3:
        raise RecordingError("Recording requires a BGR or grayscale frame.")
    if int(image.shape[1]) != width or int(image.shape[0]) != height:
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)
    if not image.flags["C_CONTIGUOUS"] or image.dtype != np.uint8:
        image = np.ascontiguousarray(image, dtype=np.uint8)
    return image
