"""Capture service tests: synthetic source, missing camera, shutdown."""

from __future__ import annotations

import time
from video_monitor.capture import CaptureService
from video_monitor.config import build_config
from video_monitor.frames import FrameBuffer
from video_monitor.processing import decode_jpeg


def test_synthetic_source_produces_shared_frames():
    config = build_config(source="synthetic", width=640, height=480, fps=20)
    buffer = FrameBuffer()
    service = CaptureService(config, buffer)
    try:
        service.start()
        deadline = time.monotonic() + 5.0
        snapshot = None
        while time.monotonic() < deadline:
            snapshot = buffer.latest()
            if snapshot is not None and service.frames_produced >= 2:
                break
            time.sleep(0.02)
        assert snapshot is not None
        frame = decode_jpeg(snapshot.jpeg)
        assert frame.shape[1] == 640
        assert frame.shape[0] == 480
        assert service.source_open_count == 1
        assert service.start_count == 1
        assert service.status_dict()["is_synthetic"] is True
        first_seq = snapshot.sequence
        deadline = time.monotonic() + 3.0
        newer = None
        while time.monotonic() < deadline:
            newer = buffer.wait_for_frame(first_seq, 0.5)
            if newer is not None and newer.sequence != first_seq:
                break
        assert newer is not None and newer.sequence != first_seq
    finally:
        assert service.stop(timeout=5.0) is True
        assert service.is_thread_alive() is False
        assert service._cap is None


def test_missing_camera_does_not_crash_and_reports_error():
    config = build_config(source="camera", camera_index=99999, width=320, height=240, fps=10)

    def fail_open(index, width, height, fps):
        assert index == 99999
        return None

    buffer = FrameBuffer()
    service = CaptureService(config, buffer, camera_opener=fail_open)
    try:
        service.start()
        deadline = time.monotonic() + 5.0
        while service.frames_produced < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        status = service.status_dict()
        assert status["ok"] is False
        assert status["error"]
        assert "unavailable" in status["error"].lower() or "camera" in status["error"].lower()
        assert status["active_source"] == "unavailable"
        assert service.is_thread_alive() is True
        snapshot = buffer.latest()
        assert snapshot is not None
        decode_jpeg(snapshot.jpeg)
    finally:
        assert service.stop(timeout=5.0) is True
        assert service.is_thread_alive() is False


def test_start_is_single_owner_even_if_called_twice():
    config = build_config(source="synthetic", fps=15)
    buffer = FrameBuffer()
    service = CaptureService(config, buffer)
    try:
        service.start()
        service.start()
        deadline = time.monotonic() + 5.0
        while service.frames_produced < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert service.start_count == 1
        assert service.source_open_count == 1
    finally:
        service.stop(timeout=5.0)


def test_camera_object_is_released_on_shutdown():
    released = {"done": False}
    captured_frame = __import__("numpy").zeros((240, 320, 3), dtype="uint8")

    class FakeCam:
        def read(self):
            return True, captured_frame

        def release(self):
            released["done"] = True

        def get(self, _prop):
            return 0

    def opener(_index, _width, _height, _fps):
        return FakeCam()

    config = build_config(source="camera", width=320, height=240, fps=15)
    buffer = FrameBuffer()
    service = CaptureService(config, buffer, camera_opener=opener)
    try:
        service.start()
        deadline = time.monotonic() + 5.0
        while service.frames_produced < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert service.active_source == "camera"
    finally:
        service.stop(timeout=5.0)
    assert released["done"] is True
    assert service._cap is None


def test_slow_client_does_not_grow_a_queue():
    """The buffer stores only the latest snapshot, not a history list."""
    config = build_config(source="synthetic", fps=30)
    buffer = FrameBuffer()
    service = CaptureService(config, buffer)
    try:
        service.start()
        deadline = time.monotonic() + 5.0
        while service.frames_produced < 8 and time.monotonic() < deadline:
            time.sleep(0.02)
        # Inspect the private snapshot only to confirm there is no queue.
        assert buffer._snapshot is not None
        assert not hasattr(buffer, "_queue")
        assert buffer.latest() is buffer._snapshot
    finally:
        service.stop(timeout=5.0)
