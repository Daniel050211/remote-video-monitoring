"""Timestamp overlay tests: format, drawing, shared encode path, errors."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import numpy as np

from video_monitor.capture import CaptureService
from video_monitor.config import build_config
from video_monitor.frames import FrameBuffer
from video_monitor.processing import (
    TIMESTAMP_TIMEZONE,
    TIMESTAMP_UTC_OFFSET,
    TIMESTAMP_ZONE_LABEL,
    decode_jpeg,
    encode_jpeg,
    format_timestamp,
    overlay_timestamp,
    prepare_display_frame,
    render_message_frame,
    render_synthetic_frame,
)

TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} HKT$")


def _wait_for_frame(buffer: FrameBuffer, service: CaptureService, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    snapshot = None
    while time.monotonic() < deadline:
        snapshot = buffer.latest()
        if snapshot is not None and service.frames_produced >= 1:
            return snapshot
        time.sleep(0.02)
    raise AssertionError("Capture service did not produce a frame in time.")


def test_format_timestamp_uses_asia_hong_kong():
    assert TIMESTAMP_TIMEZONE == "Asia/Hong_Kong"
    assert TIMESTAMP_ZONE_LABEL == "HKT"
    assert TIMESTAMP_UTC_OFFSET == "UTC+8"

    from zoneinfo import ZoneInfo

    local = datetime(2026, 11, 17, 22, 28, 5, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    assert format_timestamp(local) == "2026-11-17 22:28:05 HKT"

    utc = datetime(2026, 11, 17, 14, 28, 5, tzinfo=timezone.utc)
    assert format_timestamp(utc) == "2026-11-17 22:28:05 HKT"

    naive = datetime(2026, 11, 17, 22, 28, 5)
    assert format_timestamp(naive) == "2026-11-17 22:28:05 HKT"

    live = format_timestamp()
    assert TIMESTAMP_PATTERN.match(live), live


def test_overlay_changes_timestamp_region_versus_raw_frame():
    raw = np.full((480, 640, 3), 180, dtype=np.uint8)
    stamped = raw.copy()
    overlay_timestamp(stamped, text="2026-11-17 22:28:05 HKT")
    assert stamped.shape == raw.shape
    assert not np.array_equal(stamped, raw)
    # The overlay sits in the bottom-right; the top-left is unchanged.
    assert np.array_equal(stamped[:80, :80], raw[:80, :80])
    roi_raw = raw[-70:, -320:]
    roi_stamped = stamped[-70:, -320:]
    assert not np.array_equal(roi_raw, roi_stamped)
    # Dark background and white text should both be present.
    assert int(roi_stamped.min()) <= 15
    assert int(roi_stamped.max()) >= 240


def test_overlay_is_applied_before_jpeg_encoding():
    when = datetime(2026, 11, 17, 22, 28, 5)
    raw = render_synthetic_frame(640, 480, 4, 15.0)
    unstamped = raw.copy()
    prepared = prepare_display_frame(raw, timestamp_overlay=True, when=when)
    jpeg = encode_jpeg(prepared, 80)
    decoded = decode_jpeg(jpeg)
    jpeg_raw = encode_jpeg(unstamped, 80)

    assert jpeg.startswith(b"\xff\xd8")
    assert jpeg != jpeg_raw
    assert decoded.shape == unstamped.shape
    assert not np.array_equal(decoded[-70:, -320:], unstamped[-70:, -320:])
    # The synthetic banner at the top must remain after stamping and encoding.
    assert np.array_equal(prepared[0:20, 0:40], unstamped[0:20, 0:40])


def test_synthetic_source_frames_are_stamped_and_shared_by_viewers():
    config = build_config(source="synthetic", width=640, height=480, fps=20)
    assert config.timestamp_overlay is True
    buffer = FrameBuffer()
    service = CaptureService(config, buffer)
    try:
        service.start()
        snapshot = _wait_for_frame(buffer, service)
        viewer_a = buffer.latest()
        viewer_b = buffer.latest()
        assert viewer_a is not None and viewer_b is not None
        assert viewer_a.sequence == viewer_b.sequence
        assert viewer_a.jpeg == viewer_b.jpeg

        decoded = decode_jpeg(viewer_a.jpeg)
        assert decoded.shape == (480, 640, 3)
        roi = decoded[-70:, -320:]
        assert int(roi.min()) <= 20
        assert int(roi.max()) >= 220
        # Top banner is still the synthetic red bar (BGR approximately 0,0,180).
        banner = decoded[0:20, 20:80]
        assert int(banner[:, :, 2].mean()) > 100
        assert int(banner[:, :, 1].mean()) < 80
    finally:
        assert service.stop(timeout=5.0) is True


def test_disabled_overlay_leaves_raw_pixels_in_encode_path():
    when = datetime(2026, 11, 17, 22, 28, 5)
    raw = render_synthetic_frame(320, 240, 1, 15.0)
    expected = raw.copy()
    prepared = prepare_display_frame(raw, timestamp_overlay=False, when=when)
    assert np.array_equal(prepared, expected)


def test_missing_camera_error_frame_is_stamped_and_does_not_crash():
    config = build_config(
        source="camera",
        camera_index=99999,
        width=320,
        height=240,
        fps=10,
        timestamp_overlay=True,
    )

    def fail_open(index, width, height, fps):
        return None

    buffer = FrameBuffer()
    service = CaptureService(config, buffer, camera_opener=fail_open)
    try:
        service.start()
        snapshot = _wait_for_frame(buffer, service)
        status = service.status_dict()
        assert status["ok"] is False
        assert status["error"]
        assert status["active_source"] == "unavailable"
        assert status["timestamp_overlay"] is True
        assert service.is_thread_alive() is True

        decoded = decode_jpeg(snapshot.jpeg)
        assert decoded.shape[0] == 240
        assert decoded.shape[1] == 320
        unstamped = render_message_frame(
            320,
            240,
            "CAMERA UNAVAILABLE",
            status["error"],
        )
        assert not np.array_equal(decoded[-60:, -260:], unstamped[-60:, -260:])
    finally:
        assert service.stop(timeout=5.0) is True
        assert service.is_thread_alive() is False
