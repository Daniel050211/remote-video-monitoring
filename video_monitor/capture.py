"""Single-owner video capture service.

One CaptureService is started for the process. Every viewer reads from the
shared FrameBuffer. A new camera (or synthetic source) is never opened
for each HTTP client.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from typing import Any

import cv2

from video_monitor.config import Config
from video_monitor.faces import FaceDetector, overlay_face_detections
from video_monitor.frames import FrameBuffer
from video_monitor.motion import MotionDetector, overlay_motion_indicator
from video_monitor.processing import encode_jpeg, prepare_display_frame, render_message_frame, render_synthetic_frame
from video_monitor.recording import RecordingManager

CameraOpener = Callable[[int, int, int, float], Any]


def open_camera(index: int, width: int, height: int, fps: float) -> Any | None:
    """Try to open a webcam. Returns a VideoCapture or None.

    On Windows, Media Foundation is tried first, then DirectShow, then the
    default backend. The caller must release the object.
    """
    backends: list[int] = []
    if sys.platform == "win32":
        # Media Foundation worked on the demonstration PC when DirectShow
        # could not open any index. Try both, then the default backend.
        backends.extend([cv2.CAP_MSMF, cv2.CAP_DSHOW, cv2.CAP_ANY])
    else:
        backends.append(cv2.CAP_ANY)

    for backend in backends:
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
        cap.set(cv2.CAP_PROP_FPS, float(fps))
        ok, frame = _read_with_retries(cap, attempts=5, delay=0.05)
        if ok and frame is not None:
            return cap
        cap.release()
    return None


def _read_with_retries(cap: Any, attempts: int, delay: float):
    ok, frame = False, None
    for _ in range(attempts):
        ok, frame = cap.read()
        if ok and frame is not None:
            return ok, frame
        time.sleep(delay)
    return ok, frame


class CaptureService:
    """Owns the capture loop, JPEG encoding, and lifecycle of the source."""

    def __init__(
        self,
        config: Config,
        frame_buffer: FrameBuffer,
        camera_opener: CameraOpener | None = None,
        motion_detector: MotionDetector | None = None,
        face_detector: FaceDetector | None = None,
        recorder: RecordingManager | None = None,
    ) -> None:
        self.config = config
        self.frame_buffer = frame_buffer
        self.motion = motion_detector or MotionDetector.from_config(config)
        self.faces = face_detector or FaceDetector.from_config(config)
        self.recorder = recorder or RecordingManager(
            config.recording_dir,
            writer_fps=config.fps,
        )
        self._camera_opener = camera_opener or open_camera
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cap: Any | None = None
        self._status_lock = threading.Lock()
        self._frame_index = 0
        self.requested_source = config.source
        self.active_source: str | None = None
        self.error: str | None = None
        self.notice: str | None = None
        self.running = False
        self.actual_width = config.width
        self.actual_height = config.height
        self.start_count = 0
        self.source_open_count = 0
        self.frames_produced = 0
        self._thread_joined_cleanly = True

    def start(self) -> None:
        with self._status_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self.start_count += 1
            self._stop.clear()
            self._frame_index = 0
        self._prepare_source()
        self._thread = threading.Thread(
            target=self._run,
            name="capture-owner",
            daemon=True,
        )
        self.running = True
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        """Stop the capture thread, release the camera, and join with a timeout."""
        self._stop.set()
        thread = self._thread
        joined = True
        if thread is not None and thread.is_alive():
            thread.join(timeout)
            joined = not thread.is_alive()
        self._release_camera()
        self.running = False
        self._thread_joined_cleanly = joined
        # Finalize or clearly fail an in-progress recording after the
        # capture loop has stopped offering new frames.
        self.recorder.shutdown()
        return joined

    def is_thread_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status_dict(self) -> dict[str, Any]:
        with self._status_lock:
            error = self.error
            active = self.active_source
            notice = self.notice
            running = self.running
            actual_width = self.actual_width
            actual_height = self.actual_height
            start_count = self.start_count
            source_open_count = self.source_open_count
            frames_produced = self.frames_produced
        is_synthetic = active == "synthetic"
        ok = running and error is None and active in {"camera", "synthetic"}
        return {
            "ok": ok,
            "capture_running": running,
            "requested_source": self.requested_source,
            "active_source": active,
            "is_synthetic": is_synthetic,
            "notice": notice,
            "error": error,
            "configured": {
                "width": self.config.width,
                "height": self.config.height,
                "fps": self.config.fps,
                "jpeg_quality": self.config.jpeg_quality,
                "timestamp_overlay": self.config.timestamp_overlay,
            },
            "timestamp_overlay": self.config.timestamp_overlay,
            "timestamp_timezone": "Asia/Hong_Kong",
            "timestamp_zone_label": "HKT",
            "timestamp_utc_offset": "UTC+8",
            "actual_capture": {
                "width": actual_width,
                "height": actual_height,
            },
            "stream_transport": "MJPEG over HTTP (multipart/x-mixed-replace)",
            "image_compression": "JPEG",
            "capture_start_count": start_count,
            "source_open_count": source_open_count,
            "frames_produced": frames_produced,
            "motion": self.motion.status_dict(),
            "faces": self.faces.status_dict(),
            "recording": self.recorder.status_dict(),
        }

    def _prepare_source(self) -> None:
        requested = self.config.source
        if requested in {"auto", "camera"}:
            cap = self._camera_opener(
                self.config.camera_index,
                self.config.width,
                self.config.height,
                self.config.fps,
            )
            if cap is not None:
                width, height = _capture_size(cap, self.config.width, self.config.height)
                with self._status_lock:
                    self._cap = cap
                    self.active_source = "camera"
                    self.error = None
                    self.notice = None
                    self.actual_width = width
                    self.actual_height = height
                    self.source_open_count += 1
                return
            if requested == "camera":
                with self._status_lock:
                    self._cap = None
                    self.active_source = "unavailable"
                    self.error = (
                        f"Camera index {self.config.camera_index} is unavailable. "
                        "Check that a webcam is connected, not used by another "
                        "application, and that the index is correct."
                    )
                    self.notice = None
                    self.actual_width = self.config.width
                    self.actual_height = self.config.height
                return
            # source=auto and no camera: fall back to the test pattern.
            with self._status_lock:
                self.notice = (
                    "No camera was available; using the synthetic test source. "
                    "Synthetic results do not prove that a real webcam works."
                )
                self.error = None

        with self._status_lock:
            self._cap = None
            self.active_source = "synthetic"
            self.actual_width = self.config.width
            self.actual_height = self.config.height
            self.source_open_count += 1
            if requested == "synthetic":
                self.error = None
                if self.notice is None:
                    self.notice = (
                        "Using the synthetic test source. This does not prove "
                        "that a real webcam or a LAN demonstration works."
                    )

    def _run(self) -> None:
        interval = 1.0 / self.config.fps if self.config.fps > 0 else 1.0 / 15.0
        next_time = time.perf_counter()
        try:
            while not self._stop.is_set():
                frame, midstream_error = self._next_frame()
                if frame is not None:
                    try:
                        usable_video = (
                            self.active_source in {"camera", "synthetic"}
                            and midstream_error is None
                        )
                        if usable_video:
                            # Draw order (once, on the shared display frame):
                            # 1) analyse motion and faces on the raw frame
                            #    (so changing overlays are not treated as
                            #    motion, and Haar does not see badges);
                            # 2) face boxes + Faces: N badge (top-left,
                            #    or just below a SYNTHETIC SOURCE banner);
                            # 3) MOTION badge (top-right);
                            # 4) timestamp (bottom-right), so the clock and
                            #    MOTION mark stay readable if a box overlaps.
                            motion_result = self.motion.process(frame)
                            face_result = self.faces.process(frame)
                            if face_result.enabled:
                                overlay_face_detections(
                                    frame, face_result.boxes, face_result.count
                                )
                            if motion_result.motion_detected:
                                overlay_motion_indicator(frame)
                        else:
                            self.motion.note_unusable_frame()
                            self.faces.note_unusable_frame()
                        frame = prepare_display_frame(
                            frame,
                            timestamp_overlay=self.config.timestamp_overlay,
                        )
                        # Offer the same display frame (face boxes, MOTION
                        # badge, and timestamp already burned in) to the
                        # recorder. This does not open a second camera.
                        self.recorder.write_frame(frame)
                        jpeg = encode_jpeg(frame, self.config.jpeg_quality)
                        height, width = frame.shape[:2]
                        self.frame_buffer.update(jpeg, width, height)
                        with self._status_lock:
                            self.frames_produced += 1
                            self.actual_width = int(width)
                            self.actual_height = int(height)
                            if midstream_error:
                                self.error = midstream_error
                    except Exception as exc:  # noqa: BLE001 — keep the loop alive
                        with self._status_lock:
                            self.error = f"JPEG encoding failed: {exc}"
                next_time += interval
                remaining = next_time - time.perf_counter()
                if remaining > 0:
                    if self._stop.wait(remaining):
                        break
                else:
                    next_time = time.perf_counter()
        finally:
            self.running = False
            self._release_camera()
            self.recorder.shutdown()

    def _next_frame(self) -> tuple[Any, str | None]:
        if self.active_source == "synthetic":
            self._frame_index += 1
            return (
                render_synthetic_frame(
                    self.config.width,
                    self.config.height,
                    self._frame_index,
                    self.config.fps,
                ),
                None,
            )

        cap = self._cap
        if cap is not None:
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame, None
            message = "The camera stopped delivering frames."
            self._frame_index += 1
            return (
                render_message_frame(
                    self.config.width,
                    self.config.height,
                    "CAMERA ERROR",
                    message,
                ),
                message,
            )

        self._frame_index += 1
        return (
            render_message_frame(
                self.config.width,
                self.config.height,
                "CAMERA UNAVAILABLE",
                self.error
                or "The requested camera could not be opened.",
            ),
            None,
        )

    def _release_camera(self) -> None:
        cap = self._cap
        self._cap = None
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001 — release must not raise on shutdown
                pass


def _capture_size(cap: Any, fallback_width: int, fallback_height: int) -> tuple[int, int]:
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width <= 0 or height <= 0:
        return fallback_width, fallback_height
    return width, height
