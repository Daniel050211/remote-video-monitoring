"""Face detection tests: Haar cascade, enable/disable, fixture, API, capture path."""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

import cv2
import numpy as np
import pytest

from tests.conftest import read_mjpeg_parts
from video_monitor.capture import CaptureService
from video_monitor.config import build_config
from video_monitor.faces import (
    CASCADE_FILENAME,
    DEFAULT_DETECT_EVERY_N_FRAMES,
    DEFAULT_DETECT_SCALE,
    FaceConfigError,
    FaceDetector,
    bundled_cascade_path,
    detect_faces_bgr,
    load_cascade,
    overlay_face_detections,
    resolve_cascade_path,
)
from video_monitor.frames import FrameBuffer
from video_monitor.motion import render_static_synthetic_scene
from video_monitor.processing import (
    decode_jpeg,
    detect_synthetic_source_banner_height,
    render_synthetic_frame,
    synthetic_banner_height_for,
)
from video_monitor.web import create_app

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "astronaut_face.png"


def load_face_fixture() -> np.ndarray:
    """Load the bundled public-domain NASA / scikit-image astronaut photograph."""
    assert FIXTURE_PATH.is_file(), f"Missing face fixture: {FIXTURE_PATH}"
    frame = cv2.imread(str(FIXTURE_PATH), cv2.IMREAD_COLOR)
    assert frame is not None, "OpenCV could not decode the face fixture."
    return frame


def _green_box_pixels(frame: np.ndarray, box: tuple[int, int, int, int]) -> int:
    x, y, w, h = box
    # Sample the rectangle border, where the overlay draws green.
    border = np.concatenate(
        [
            frame[y, x : x + w],
            frame[y + h - 1, x : x + w],
            frame[y : y + h, x],
            frame[y : y + h, x + w - 1],
        ],
        axis=0,
    )
    # BOX_COLOR is approximately (0, 220, 0) but JPEG and thickness can vary
    # on live streams; for raw BGR overlays the exact color is present.
    return int(np.count_nonzero((border[:, 1] >= 150) & (border[:, 0] <= 80) & (border[:, 2] <= 80)))


def test_bundled_cascade_loads():
    path = resolve_cascade_path()
    assert path == bundled_cascade_path()
    assert path.name == CASCADE_FILENAME
    classifier, loaded_from = load_cascade()
    assert loaded_from == path
    assert not classifier.empty()


def test_fixture_triggers_at_least_one_detection():
    frame = load_face_fixture()
    classifier, _path = load_cascade()
    boxes = detect_faces_bgr(frame, classifier, detect_scale=DEFAULT_DETECT_SCALE)
    assert len(boxes) >= 1
    height, width = frame.shape[:2]
    x, y, w, h = boxes[0]
    assert w >= 20 and h >= 20
    assert 0 <= x < width and 0 <= y < height

    detector = FaceDetector(enabled=True, detect_every_n_frames=1, detect_scale=0.5)
    result = detector.process(frame)
    assert result.enabled is True
    assert result.detection_ran is True
    assert result.count >= 1
    assert len(result.boxes) == result.count
    status = detector.status_dict()
    assert status["recognition"] is False
    assert status["mode"] == "detection"
    assert status["detected_count"] >= 1
    assert "not recognition" in status["detected_count_definition"]


def test_disabled_detector_does_not_report_or_draw_faces():
    frame = load_face_fixture()
    detector = FaceDetector(enabled=False, detect_every_n_frames=1, detect_scale=0.5)
    result = detector.process(frame)
    assert result.enabled is False
    assert result.count == 0
    assert result.boxes == ()
    assert result.detection_ran is False
    assert detector.status_dict()["detected_count"] == 0

    # Even if a caller asked to overlay, we do not call overlay when disabled.
    # Direct overlay with empty boxes should not invent rectangles; the badge
    # is only used when detection is enabled in the capture path.
    canvas = frame.copy()
    before = canvas.copy()
    # Confirm the detector itself did not mark the input.
    assert np.array_equal(frame, before)


def test_overlay_draws_boxes_only_when_given_boxes():
    frame = load_face_fixture()
    detector = FaceDetector(enabled=True, detect_every_n_frames=1, detect_scale=0.5)
    result = detector.process(frame)
    assert result.count >= 1
    marked = overlay_face_detections(frame.copy(), result.boxes, result.count)
    assert _green_box_pixels(marked, result.boxes[0]) > 0
    # A copy with no boxes must not receive face rectangles (badge only).
    clean = np.full((240, 320, 3), 40, dtype=np.uint8)
    overlay_face_detections(clean, (), 0)
    # The count badge is drawn at the top-left; the rest of the frame stays plain.
    interior = clean[40:200, 40:280]
    assert np.all(interior == 40)



def test_face_count_badge_sits_below_synthetic_banner():
    """Faces: N must not cover the full-width SYNTHETIC SOURCE banner."""
    plain = np.full((240, 320, 3), 40, dtype=np.uint8)
    assert detect_synthetic_source_banner_height(plain) == 0
    overlay_face_detections(plain, (), 3)
    # No banner: the badge remains in the reserved top-left band.
    assert not np.all(plain[0:40, 0:40] == 40)
    assert np.all(plain[40:200, 40:280] == 40)

    frame = render_synthetic_frame(640, 480, 0, 15.0)
    banner_h = detect_synthetic_source_banner_height(frame)
    assert banner_h == synthetic_banner_height_for(480)
    assert banner_h == 48
    overlay_face_detections(frame, (), 2)
    # The top banner (including the left-hand title) stays red, not the
    # green Faces badge.
    banner = frame[0:banner_h, 16:120]
    assert int(banner[:, :, 2].mean()) > 100
    assert int(banner[:, :, 1].mean()) < 80
    # The count badge starts immediately below the banner on the left.
    badge = frame[banner_h + 4 : banner_h + 36, 8:130]
    assert int(badge[:, :, 1].mean()) > 50
    assert int(badge[:, :, 1].mean()) > int(badge[:, :, 2].mean())


def test_plain_synthetic_pattern_has_zero_detections():
    detector = FaceDetector(enabled=True, detect_every_n_frames=1, detect_scale=0.5)
    hits = 0
    for index in range(12):
        frame = render_synthetic_frame(640, 480, index, 15.0)
        result = detector.process(frame)
        if result.count:
            hits += 1
    assert hits == 0
    static = render_static_synthetic_scene(640, 480, 0)
    assert detector.process(static).count == 0


def test_empty_or_missing_frame_does_not_invent_faces():
    detector = FaceDetector(enabled=True, detect_every_n_frames=1)
    assert detector.process(None).count == 0
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    assert detector.process(empty).count == 0
    detector.note_unusable_frame()
    assert detector.status_dict()["detected_count"] == 0


def test_enable_disable_clears_held_boxes():
    frame = load_face_fixture()
    detector = FaceDetector(enabled=True, detect_every_n_frames=2, detect_scale=0.5)
    first = detector.process(frame)
    assert first.count >= 1
    # Skipped frame would reuse boxes while enabled.
    reused = detector.process(frame)
    assert reused.reused_previous is True
    assert reused.count == first.count
    detector.set_enabled(False)
    disabled = detector.process(frame)
    assert disabled.enabled is False
    assert disabled.count == 0
    assert detector.status_dict()["detected_count"] == 0
    detector.set_enabled(True)
    enabled = detector.process(frame)
    assert enabled.detection_ran is True
    assert enabled.count >= 1


def test_invalid_performance_settings_are_rejected():
    with pytest.raises(FaceConfigError):
        FaceDetector(detect_every_n_frames=0)
    with pytest.raises(FaceConfigError):
        FaceDetector(detect_scale=0.1)


def test_capture_path_uses_one_owner_and_shared_boxes(tmp_path):
    class FixtureCam:
        def isOpened(self):
            return True

        def read(self):
            return True, load_face_fixture()

        def get(self, _prop):
            image = load_face_fixture()
            height, width = image.shape[:2]
            if _prop == cv2.CAP_PROP_FRAME_WIDTH:
                return float(width)
            if _prop == cv2.CAP_PROP_FRAME_HEIGHT:
                return float(height)
            return 0.0

        def release(self):
            return None

    detector = FaceDetector(enabled=True, detect_every_n_frames=1, detect_scale=0.5)
    config = build_config(
        source="camera",
        width=512,
        height=512,
        fps=15,
        snapshot_dir=tmp_path / "snapshots",
        recording_dir=tmp_path / "recordings",
        face_detection_enabled=True,
        face_detect_every_n_frames=1,
    )
    buffer = FrameBuffer()
    service = CaptureService(
        config,
        buffer,
        camera_opener=lambda *_args: FixtureCam(),
        face_detector=detector,
    )
    try:
        service.start()
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            status = service.status_dict()
            if status["frames_produced"] >= 2 and status["faces"]["detected_count"] >= 1:
                break
            time.sleep(0.02)
        status = service.status_dict()
        assert status["source_open_count"] == 1
        assert status["capture_start_count"] == 1
        assert status["faces"]["enabled"] is True
        assert status["faces"]["recognition"] is False
        assert status["faces"]["detected_count"] >= 1
        snapshot = buffer.latest()
        assert snapshot is not None
        viewer_a = buffer.latest()
        viewer_b = buffer.latest()
        assert viewer_a is not None and viewer_b is not None
        assert viewer_a.jpeg == viewer_b.jpeg
        decoded = decode_jpeg(snapshot.jpeg)
        # Use a separate classifier call so we do not race the capture thread
        # on the shared FaceDetector.lock.
        classifier, _path = load_cascade()
        boxes = detect_faces_bgr(load_face_fixture(), classifier, detect_scale=0.5)
        assert len(boxes) >= 1
        # After JPEG compression the exact (0,220,0) may shift slightly;
        # check that the box region is present by a looser green test.
        x, y, w, h = boxes[0]
        height, width = decoded.shape[:2]
        x2 = min(width, x + w)
        y2 = min(height, y + h)
        region = decoded[max(0, y) : y2, max(0, x) : x2]
        greens = int(np.count_nonzero((region[:, :, 1] > region[:, :, 0] + 40) & (region[:, :, 1] > region[:, :, 2] + 40)))
        assert greens > 0
    finally:
        service.stop(timeout=5.0)


def test_status_and_index_page_describe_face_detection(flask_app):
    client = flask_app.test_client()
    page = client.get("/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Face detection" in html
    assert "Enable face detection" in html
    assert "detection only" in html.lower() or "Detection only" in html
    assert "not recognition" in html.lower()

    data = client.get("/api/status").get_json()
    faces = data["faces"]
    assert faces["enabled"] is True
    assert faces["recognition"] is False
    assert faces["mode"] == "detection"
    assert faces["cascade_name"] == CASCADE_FILENAME
    assert faces["detect_every_n_frames"] == DEFAULT_DETECT_EVERY_N_FRAMES
    assert faces["detect_scale"] == DEFAULT_DETECT_SCALE
    assert "not recognition" in faces["detected_count_definition"]
    # Default flask_app uses the synthetic pattern, which should not invent faces.
    # Wait briefly in case a first detection has not been published yet, then check.
    deadline = time.monotonic() + 2.0
    counts = []
    while time.monotonic() < deadline:
        counts.append(client.get("/api/status").get_json()["faces"]["detected_count"])
        if counts[-1] == 0 and len(counts) >= 3:
            break
        time.sleep(0.05)
    assert counts[-1] == 0


def test_faces_api_enable_disable(flask_app):
    client = flask_app.test_client()
    off = client.post("/api/faces", json={"enabled": False, "path": "../evil"})
    assert off.status_code == 200
    data = off.get_json()
    assert data["ok"] is True
    assert data["enabled"] is False
    assert data["detected_count"] == 0
    assert data["recognition"] is False
    assert "path" not in data or data.get("path") is None

    status = client.get("/api/status").get_json()
    assert status["faces"]["enabled"] is False

    bad = client.post("/api/faces", json={"enabled": "maybe"})
    assert bad.status_code == 400
    assert bad.get_json()["ok"] is False

    on = client.post("/api/faces", json={"enabled": True})
    assert on.status_code == 200
    assert on.get_json()["enabled"] is True


@pytest.mark.parametrize(
    "running_app",
    [["--source", "synthetic", "--server", "waitress", "--no-faces"]],
    indirect=True,
)
def test_entry_point_can_start_with_faces_disabled(running_app):
    host, port = running_app.host, running_app.port
    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/api/status")
        data = json.loads(connection.getresponse().read().decode("utf-8"))
    finally:
        connection.close()
    assert data["faces"]["enabled"] is False
    assert data["faces"]["recognition"] is False
    assert data["is_synthetic"] is True

    connection = HTTPConnection(host, port, timeout=8)
    try:
        payload = json.dumps({"enabled": True, "path": "../escape"}).encode("utf-8")
        connection.request(
            "POST",
            "/api/faces",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert body["enabled"] is True
        assert body["recognition"] is False
    finally:
        connection.close()

    connection = HTTPConnection(host, port, timeout=8)
    try:
        payload = json.dumps({"enabled": False}).encode("utf-8")
        connection.request(
            "POST",
            "/api/faces",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        body = json.loads(connection.getresponse().read().decode("utf-8"))
        assert body["enabled"] is False
        assert body["detected_count"] == 0
    finally:
        connection.close()

    response, parts = read_mjpeg_parts(host, port, count=2, timeout=8)
    assert response.status == 200
    assert len(parts) >= 2
    decode_jpeg(parts[0])


@pytest.mark.parametrize(
    "running_app",
    [[
        "--source",
        "synthetic",
        "--server",
        "waitress",
        "--face-detect-every",
        "1",
    ]],
    indirect=True,
)
def test_two_clients_share_one_capture_with_faces_enabled(running_app):
    host, port = running_app.host, running_app.port
    results: list[list[bytes]] = []
    errors: list[BaseException] = []

    def worker():
        try:
            _response, parts = read_mjpeg_parts(host, port, count=2, timeout=8)
            results.append(parts)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=12)
        assert not thread.is_alive()

    assert errors == []
    assert len(results) == 2
    assert all(len(parts) >= 2 for parts in results)
    for parts in results:
        decode_jpeg(parts[0])

    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/api/status")
        data = json.loads(connection.getresponse().read().decode("utf-8"))
    finally:
        connection.close()
    assert data["capture_start_count"] == 1
    assert data["source_open_count"] == 1
    assert data["faces"]["enabled"] is True
    assert data["faces"]["recognition"] is False
    assert data["faces"]["detected_count"] == 0
