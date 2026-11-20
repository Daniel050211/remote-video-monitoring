"""HTTP route and MJPEG streaming tests. Stream reads always use a timeout."""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection

import pytest

from tests.conftest import read_mjpeg_parts
from video_monitor.processing import decode_jpeg


def test_index_page_returns_200(flask_app):
    client = flask_app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Remote Video Monitoring" in html
    assert "/video_feed" in html
    assert "Configured FPS" in html
    assert "Timestamp overlay" in html
    assert "On (HKT, UTC+8)" in html
    assert "Save snapshot" in html
    assert "/api/snapshot" in html or "snapshot-button" in html
    assert "Start recording" in html
    assert "Stop recording" in html
    assert "Face detection" in html
    assert "Enable face detection" in html
    assert "favicon" in html
    assert "Skip to live view" in html


def test_favicon_is_served_at_root(flask_app):
    client = flask_app.test_client()
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    data = response.get_data()
    assert data.startswith(bytes([0, 0, 1, 0]))
    ctype = (response.content_type or "").lower()
    assert "icon" in ctype or "octet-stream" in ctype


def test_status_api_describes_synthetic_source(flask_app):
    client = flask_app.test_client()
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["is_synthetic"] is True
    assert data["active_source"] == "synthetic"
    assert data["configured"]["width"] == 640
    assert data["configured"]["height"] == 480
    assert data["configured"]["fps"] == 15.0
    assert data["stream_transport"].startswith("MJPEG")
    assert data["image_compression"] == "JPEG"
    assert data["timestamp_overlay"] is True
    assert data["timestamp_timezone"] == "Asia/Hong_Kong"
    assert data["timestamp_zone_label"] == "HKT"
    assert data["configured"]["timestamp_overlay"] is True
    assert data["capture_start_count"] == 1
    assert data["source_open_count"] == 1
    assert data["frames_produced"] >= 1
    assert data["faces"]["mode"] == "detection"
    assert data["faces"]["recognition"] is False
    assert data["faces"]["enabled"] is True


def test_video_feed_via_test_client_is_multipart_and_finite(flask_app):
    client = flask_app.test_client()
    response = client.get("/video_feed", buffered=False)
    assert response.status_code == 200
    assert "multipart/x-mixed-replace" in response.content_type
    assert "boundary=frame" in response.content_type
    collected = b""
    for chunk in response.response:
        collected += chunk if isinstance(chunk, (bytes, bytearray)) else bytes(chunk)
        if b"\xff\xd8" in collected and b"\xff\xd9" in collected:
            break
    else:
        pytest.fail("Did not receive a complete JPEG from the test-client stream.")
    start = collected.find(b"\xff\xd8")
    end = collected.find(b"\xff\xd9")
    decode_jpeg(collected[start : end + 2])
    # Closing the context ends iteration; do not wait for the infinite generator.


@pytest.mark.parametrize("running_app", [["--source", "synthetic", "--server", "waitress"]], indirect=True)
def test_waitress_serves_page_status_and_mjpeg(running_app):
    host, port = running_app.host, running_app.port
    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/")
        page = connection.getresponse()
        body = page.read()
        assert page.status == 200
        assert b"Remote Video Monitoring" in body
    finally:
        connection.close()

    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/api/status")
        status = connection.getresponse()
        data = json.loads(status.read().decode("utf-8"))
        assert status.status == 200
        assert data["is_synthetic"] is True
        assert data["source_open_count"] == 1
    finally:
        connection.close()

    response, parts = read_mjpeg_parts(host, port, count=2, timeout=8)
    assert response.status == 200
    content_type = response.getheader("Content-Type") or ""
    assert "multipart/x-mixed-replace" in content_type
    assert "boundary=frame" in content_type
    assert len(parts) >= 2
    for part in parts:
        decode_jpeg(part)


@pytest.mark.parametrize("running_app", [["--source", "synthetic", "--server", "waitress"]], indirect=True)
def test_two_concurrent_clients_share_one_capture(running_app):
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


@pytest.mark.parametrize(
    "running_app",
    [["--source", "camera", "--camera-index", "99999", "--server", "waitress"]],
    indirect=True,
)
def test_missing_camera_via_entry_point_returns_error_and_keeps_serving(running_app):
    host, port = running_app.host, running_app.port
    # The process must stay up even when the camera cannot be opened.
    assert running_app.process.poll() is None

    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/")
        assert connection.getresponse().status == 200
    finally:
        connection.close()

    deadline = time.monotonic() + 6.0
    data = None
    while time.monotonic() < deadline:
        connection = HTTPConnection(host, port, timeout=8)
        try:
            connection.request("GET", "/api/status")
            data = json.loads(connection.getresponse().read().decode("utf-8"))
        finally:
            connection.close()
        if data.get("error"):
            break
        time.sleep(0.1)
    assert data is not None
    assert data["ok"] is False
    assert data["error"]
    assert data["active_source"] == "unavailable"
    assert data["capture_running"] is True

    _response, parts = read_mjpeg_parts(host, port, count=1, timeout=8)
    assert len(parts) >= 1
    decode_jpeg(parts[0])
