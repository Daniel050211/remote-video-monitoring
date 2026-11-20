"""Motion detection tests: algorithm, cooldown, log bound, API, and capture path."""

from __future__ import annotations

import json
import time
from http.client import HTTPConnection

import numpy as np
import pytest

from tests.conftest import read_mjpeg_parts
from video_monitor.capture import CaptureService
from video_monitor.config import build_config
from video_monitor.frames import FrameBuffer
from video_monitor.motion import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_LOG_SIZE,
    DEFAULT_SENSITIVITY,
    MotionConfigError,
    MotionDetector,
    overlay_motion_indicator,
    render_motion_synthetic_scene,
    render_static_synthetic_scene,
    thresholds_for_sensitivity,
)
from video_monitor.processing import decode_jpeg
from video_monitor.snapshots import SnapshotStore
from video_monitor.web import create_app


def test_thresholds_match_documented_defaults():
    low_px, low_area = thresholds_for_sensitivity(1)
    mid_px, mid_area = thresholds_for_sensitivity(DEFAULT_SENSITIVITY)
    high_px, high_area = thresholds_for_sensitivity(100)
    assert low_px == 30
    assert low_area == pytest.approx(4.0)
    assert mid_px == 25
    assert mid_area == pytest.approx(2.12, abs=0.02)
    assert high_px == 20
    assert high_area == pytest.approx(0.20)
    # Higher sensitivity must accept smaller changes.
    assert high_area < mid_area < low_area
    assert high_px <= mid_px <= low_px


def test_static_scene_does_not_flood_the_log():
    detector = MotionDetector(
        enabled=True,
        sensitivity=DEFAULT_SENSITIVITY,
        cooldown_seconds=0.0,
        max_events=DEFAULT_LOG_SIZE,
    )
    # Ten identical frames: first is baseline, the rest should stay quiet.
    for index in range(10):
        frame = render_static_synthetic_scene(640, 480, index)
        result = detector.process(frame)
        assert result.motion_detected is False
        assert result.event_recorded is False
    status = detector.status_dict()
    assert status["log_count"] == 0
    assert status["events_recorded_total"] == 0
    assert status["currently_detected"] is False
    assert status["frames_checked"] == 10


def test_deliberate_motion_produces_at_least_one_event():
    detector = MotionDetector(
        enabled=True,
        sensitivity=DEFAULT_SENSITIVITY,
        cooldown_seconds=0.0,
        max_events=DEFAULT_LOG_SIZE,
    )
    baseline = render_motion_synthetic_scene(640, 480, 0)
    moving = render_motion_synthetic_scene(640, 480, 1)
    assert not np.array_equal(baseline, moving)
    first = detector.process(baseline)
    assert first.motion_detected is False
    second = detector.process(moving)
    assert second.motion_detected is True
    assert second.event_recorded is True
    assert second.changed_percent is not None
    assert second.changed_percent > second.min_changed_percent
    events = detector.events()
    assert len(events) == 1
    assert "Motion detected" in events[0].message
    assert events[0].time_label.endswith("HKT")


def test_disabling_motion_stops_new_events_while_frames_keep_moving():
    detector = MotionDetector(enabled=True, sensitivity=50, cooldown_seconds=0.0)
    detector.process(render_motion_synthetic_scene(640, 480, 0))
    moving_result = detector.process(render_motion_synthetic_scene(640, 480, 1))
    assert moving_result.event_recorded is True
    count_after_enable = detector.status_dict()["events_recorded_total"]

    detector.set_enabled(False)
    for index in range(2, 8):
        result = detector.process(render_motion_synthetic_scene(640, 480, index))
        assert result.enabled is False
        assert result.motion_detected is False
        assert result.event_recorded is False
    status = detector.status_dict()
    assert status["enabled"] is False
    assert status["currently_detected"] is False
    assert status["events_recorded_total"] == count_after_enable
    assert status["log_count"] == count_after_enable

    # Enabling again starts from a fresh baseline, then records new motion.
    detector.set_enabled(True)
    baseline = detector.process(render_motion_synthetic_scene(640, 480, 8))
    assert baseline.motion_detected is False
    assert baseline.event_recorded is False
    resumed = detector.process(render_motion_synthetic_scene(640, 480, 9))
    assert resumed.motion_detected is True
    assert resumed.event_recorded is True
    assert detector.status_dict()["events_recorded_total"] == count_after_enable + 1


def test_cooldown_prevents_event_flood_on_continuous_motion():
    clock = {"now": 100.0}

    def time_fn() -> float:
        return clock["now"]

    detector = MotionDetector(
        enabled=True,
        sensitivity=50,
        cooldown_seconds=DEFAULT_COOLDOWN_SECONDS,
        time_fn=time_fn,
    )
    detector.process(render_motion_synthetic_scene(320, 240, 0))
    first = detector.process(render_motion_synthetic_scene(320, 240, 1))
    assert first.event_recorded is True

    # Many moving frames still inside the 2.0 s cooldown.
    for index in range(2, 12):
        clock["now"] += 0.1  # 1.0 s total, still below 2.0 s
        result = detector.process(render_motion_synthetic_scene(320, 240, index))
        assert result.motion_detected is True
        assert result.event_recorded is False
    assert detector.status_dict()["events_recorded_total"] == 1
    assert detector.status_dict()["currently_detected"] is True

    clock["now"] += 1.1  # now 2.1 s after the first event
    after = detector.process(render_motion_synthetic_scene(320, 240, 12))
    assert after.motion_detected is True
    assert after.event_recorded is True
    assert detector.status_dict()["events_recorded_total"] == 2


def test_event_log_is_bounded_and_keeps_the_latest_entries():
    detector = MotionDetector(
        enabled=True,
        sensitivity=50,
        cooldown_seconds=0.0,
        max_events=5,
    )
    # Baseline plus 8 moving frames => 8 events, log keeps the latest 5.
    detector.process(render_motion_synthetic_scene(320, 240, 0))
    for index in range(1, 9):
        result = detector.process(render_motion_synthetic_scene(320, 240, index))
        assert result.event_recorded is True
    status = detector.status_dict()
    assert status["events_recorded_total"] == 8
    assert status["log_count"] == 5
    assert status["log_capacity"] == 5
    messages_changed = [item.changed_percent for item in detector.events()]
    assert len(messages_changed) == 5


def test_empty_or_missing_frames_do_not_crash_or_spam():
    detector = MotionDetector(enabled=True, cooldown_seconds=0.0)
    empty = detector.process(None)
    assert empty.motion_detected is False
    assert empty.event_recorded is False
    blank = detector.process(np.zeros((0, 0, 3), dtype=np.uint8))
    assert blank.event_recorded is False
    assert detector.status_dict()["log_count"] == 0


def test_invalid_sensitivity_is_rejected():
    with pytest.raises(MotionConfigError):
        MotionDetector(sensitivity=0)
    detector = MotionDetector()
    with pytest.raises(MotionConfigError):
        detector.set_sensitivity(101)


def test_motion_badge_is_drawn_on_the_top_right():
    frame = render_static_synthetic_scene(640, 480, 0)
    original = frame.copy()
    overlay_motion_indicator(frame)
    assert not np.array_equal(frame, original)
    # Top-left region used by the synthetic banner check stays untouched.
    assert np.array_equal(frame[0:20, 20:80], original[0:20, 20:80])
    # Bottom-right timestamp region stays untouched.
    assert np.array_equal(frame[-70:, -80:], original[-70:, -80:])
    badge = frame[4:40, 500:636]
    assert int(badge[:, :, 2].mean()) > 80


def test_missing_camera_does_not_invent_motion_events():
    config = build_config(source="camera", camera_index=99999, width=320, height=240, fps=15)

    def fail_open(index, width, height, fps):
        return None

    buffer = FrameBuffer()
    service = CaptureService(config, buffer, camera_opener=fail_open)
    try:
        service.start()
        deadline = time.monotonic() + 5.0
        while service.frames_produced < 8 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert service.frames_produced >= 1
        status = service.status_dict()
        assert status["error"]
        assert status["active_source"] == "unavailable"
        assert status["motion"]["log_count"] == 0
        assert status["motion"]["events_recorded_total"] == 0
        assert status["motion"]["currently_detected"] is False
        snapshot = buffer.latest()
        assert snapshot is not None
        decode_jpeg(snapshot.jpeg)
    finally:
        assert service.stop(timeout=5.0) is True


def test_capture_applies_motion_once_before_shared_jpeg():
    frames = [
        render_static_synthetic_scene(320, 240, 0),
        render_static_synthetic_scene(320, 240, 1),
        render_motion_synthetic_scene(320, 240, 0),
        render_motion_synthetic_scene(320, 240, 1),
        render_motion_synthetic_scene(320, 240, 2),
    ]
    cursor = {"i": 0}

    class ScriptedCam:
        def read(self):
            frame = frames[min(cursor["i"], len(frames) - 1)]
            cursor["i"] += 1
            return True, frame.copy()

        def release(self):
            return None

        def get(self, _prop):
            return 0

    detector = MotionDetector(enabled=True, sensitivity=50, cooldown_seconds=0.0)
    config = build_config(source="camera", width=320, height=240, fps=30)
    buffer = FrameBuffer()
    service = CaptureService(
        config,
        buffer,
        camera_opener=lambda *_args: ScriptedCam(),
        motion_detector=detector,
    )
    try:
        service.start()
        deadline = time.monotonic() + 5.0
        while detector.status_dict()["events_recorded_total"] < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        status = service.status_dict()
        assert status["source_open_count"] == 1
        assert status["motion"]["events_recorded_total"] >= 1
        snapshot = buffer.latest()
        assert snapshot is not None
        decoded = decode_jpeg(snapshot.jpeg)
        viewer_a = buffer.latest()
        viewer_b = buffer.latest()
        assert viewer_a is not None and viewer_b is not None
        assert viewer_a.jpeg == viewer_b.jpeg
        assert decoded.shape == (240, 320, 3)
    finally:
        service.stop(timeout=5.0)


def test_status_and_index_page_describe_motion(flask_app):
    client = flask_app.test_client()
    page = client.get("/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Motion detection" in html
    assert "Enable motion detection" in html
    assert "Event log" in html
    assert "Sensitivity" in html

    response = client.get("/api/status")
    data = response.get_json()
    motion = data["motion"]
    assert motion["enabled"] is True
    assert motion["sensitivity"] == 50
    assert motion["cooldown_seconds"] == 2.0
    assert motion["log_capacity"] == 50
    assert "frames_checked_definition" in motion
    assert "browser FPS" in motion["frames_checked_definition"]
    events = client.get("/api/motion/events")
    assert events.status_code == 200
    body = events.get_json()
    assert body["ok"] is True
    assert "events" in body
    assert body["log_capacity"] == 50


def test_motion_api_enable_disable_and_sensitivity(flask_app):
    client = flask_app.test_client()
    off = client.post("/api/motion", json={"enabled": False, "path": "../evil"})
    assert off.status_code == 200
    data = off.get_json()
    assert data["ok"] is True
    assert data["enabled"] is False
    assert "path" not in data or data.get("path") is None

    status = client.get("/api/status").get_json()
    assert status["motion"]["enabled"] is False

    bad = client.post("/api/motion", json={"sensitivity": 500})
    assert bad.status_code == 400
    assert bad.get_json()["ok"] is False

    on = client.post("/api/motion", json={"enabled": True, "sensitivity": 70})
    assert on.status_code == 200
    body = on.get_json()
    assert body["enabled"] is True
    assert body["sensitivity"] == 70


@pytest.mark.parametrize(
    "running_app",
    [["--source", "synthetic", "--server", "waitress", "--no-motion"]],
    indirect=True,
)
def test_entry_point_can_start_with_motion_disabled(running_app):
    host, port = running_app.host, running_app.port
    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/api/status")
        data = json.loads(connection.getresponse().read().decode("utf-8"))
    finally:
        connection.close()
    assert data["motion"]["enabled"] is False
    assert data["is_synthetic"] is True

    # Enable, then disable again over HTTP, and confirm the MJPEG stream still works.
    connection = HTTPConnection(host, port, timeout=8)
    try:
        payload = json.dumps({"enabled": True, "sensitivity": 60}).encode("utf-8")
        connection.request(
            "POST",
            "/api/motion",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert body["enabled"] is True
        assert body["sensitivity"] == 60
    finally:
        connection.close()

    connection = HTTPConnection(host, port, timeout=8)
    try:
        payload = json.dumps({"enabled": False}).encode("utf-8")
        connection.request(
            "POST",
            "/api/motion",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        body = json.loads(connection.getresponse().read().decode("utf-8"))
        assert body["enabled"] is False
    finally:
        connection.close()

    response, parts = read_mjpeg_parts(host, port, count=2, timeout=8)
    assert response.status == 200
    assert len(parts) >= 2
    decode_jpeg(parts[0])


def test_snapshot_still_works_with_motion_marks(tmp_path):
    config = build_config(source="synthetic", width=320, height=240, fps=20)
    buffer = FrameBuffer()
    detector = MotionDetector(enabled=True, sensitivity=50, cooldown_seconds=0.0)
    service = CaptureService(config, buffer, motion_detector=detector)
    store = SnapshotStore(tmp_path / "snapshots")
    app = create_app(config, service, buffer, snapshot_store=store)
    try:
        service.start()
        deadline = time.monotonic() + 5.0
        while buffer.latest() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        client = app.test_client()
        response = client.post("/api/snapshot")
        data = response.get_json()
        assert data["ok"] is True
        saved = store.directory / data["filename"]
        assert saved.is_file()
        decode_jpeg(saved.read_bytes())
    finally:
        service.stop(timeout=5.0)
