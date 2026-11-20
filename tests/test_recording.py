"""Manual recording tests. Files are written only under temporary directories."""

from __future__ import annotations

import json
import signal
import time
from http.client import HTTPConnection
from pathlib import Path

import cv2
import pytest

from tests.conftest import read_mjpeg_parts
from video_monitor.capture import CaptureService
from video_monitor.config import build_config
from video_monitor.frames import FrameBuffer
from video_monitor.processing import decode_jpeg
from video_monitor.recording import (
    SAFE_FILENAME_PATTERN,
    WRITER_CANDIDATES,
    RecordingConflict,
    RecordingError,
    RecordingManager,
    WriterCandidate,
    is_safe_recording_filename,
    resolve_under_directory,
    validate_recorded_file,
)
from video_monitor.web import create_app


def _wait_for_frame(buffer: FrameBuffer, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    snapshot = buffer.latest()
    while snapshot is None and time.monotonic() < deadline:
        time.sleep(0.02)
        snapshot = buffer.latest()
    assert snapshot is not None, "Capture did not publish a frame in time."
    return snapshot


def _start_and_stop(recorder: RecordingManager, buffer: FrameBuffer, duration: float):
    snapshot = _wait_for_frame(buffer)
    recorder.start(width=snapshot.width, height=snapshot.height)
    time.sleep(duration)
    return recorder.stop()


@pytest.mark.parametrize(
    "name",
    [
        "../secret.avi",
        r"..\secret.avi",
        "/tmp/evil.avi",
        r"C:\Windows\x.avi",
        "recording/../../etc/passwd",
        "data/recordings/../README.md",
        "",
        ".",
        "..",
        "recording_20260101_000000_abcdabcd.mp4",
        "RECORDING_20260101_000000_abcdabcd.avi",
        "recording_20260101_000000_abcdabcd.avi.exe",
        "foo.avi",
        "recording_20260101_000000_zzzzzzzz.avi",
        "recording_20260101_000000_abcdabcd.avi/../../x",
        "recording_20260101_000000_abcdabcd",
        ".recording_20260101_000000_abcdabcd.avi",
    ],
)
def test_unsafe_recording_names_are_rejected(name, tmp_path):
    recorder = RecordingManager(tmp_path / "recordings", writer_fps=15.0)
    assert not is_safe_recording_filename(name)
    with pytest.raises(RecordingError):
        resolve_under_directory(recorder.directory, name)


def test_safe_generated_recording_name_resolves_inside_directory(tmp_path):
    recorder = RecordingManager(tmp_path / "recordings", writer_fps=15.0)
    name = "recording_20261117_224800_deadbeef.avi"
    assert is_safe_recording_filename(name)
    resolved = resolve_under_directory(recorder.directory, name)
    assert resolved.parent == recorder.directory
    assert resolved.name == name
    assert resolved.is_relative_to(recorder.directory)


def test_start_then_stop_creates_playable_file(capture_bundle, tmp_path):
    config, service, buffer = capture_bundle
    recorder = service.recorder
    assert recorder.directory.is_relative_to(tmp_path)

    started = time.monotonic()
    status = _start_and_stop(recorder, buffer, 1.6)
    elapsed = time.monotonic() - started

    assert status["ok"] if "ok" in status else status["state"] == "idle"
    assert status["state"] == "idle"
    filename = status["last_filename"]
    assert is_safe_recording_filename(filename)
    assert SAFE_FILENAME_PATTERN.fullmatch(filename)
    assert "/" not in filename and "\\" not in filename
    path = recorder.directory / filename
    assert path.is_file()
    assert path.parent == recorder.directory.resolve()

    info = validate_recorded_file(
        path,
        expected_width=640,
        expected_height=480,
        expected_min_frames=3,
    )
    assert info["frames"] >= 3
    # Writer FPS is the configured container rate, not a measured capture rate.
    assert status["writer_fps"] == 15.0
    assert status["codec"] == "MJPG"
    assert status["container"] == "AVI"
    # Tolerant frame-count bounds for ~1.6 s at a 15 FPS writer rate.
    assert info["frames"] <= int(elapsed * 15.0 * 3) + 15
    if elapsed >= 1.0:
        assert info["frames"] >= max(3, int(elapsed * 15.0 * 0.25))


def test_starting_twice_is_rejected_and_does_not_open_second_writer(capture_bundle):
    _config, service, buffer = capture_bundle
    recorder = service.recorder
    snapshot = _wait_for_frame(buffer)
    first = recorder.start(width=snapshot.width, height=snapshot.height)
    first_name = first["current_filename"]
    source_opens_before = service.source_open_count

    with pytest.raises(RecordingConflict, match="already in progress"):
        recorder.start(width=snapshot.width, height=snapshot.height)

    assert recorder.state == "recording"
    assert recorder.status_dict()["current_filename"] == first_name
    assert service.source_open_count == source_opens_before
    files = list(recorder.directory.glob("recording_*.avi"))
    assert len(files) == 1

    time.sleep(0.6)
    recorder.stop()


def test_stop_when_not_recording_is_a_useful_error(tmp_path):
    recorder = RecordingManager(tmp_path / "recordings", writer_fps=15.0)
    with pytest.raises(RecordingConflict, match="No recording is in progress"):
        recorder.stop()
    assert recorder.state == "idle"
    assert list((tmp_path / "recordings").glob("recording_*.avi")) == []


def test_failed_writer_is_reported_and_not_success(tmp_path):
    class ClosedWriter:
        def __init__(self) -> None:
            self.released = False

        def isOpened(self) -> bool:
            return False

        def write(self, _frame) -> bool:
            return False

        def release(self) -> None:
            self.released = True

    def factory(_path, _fourcc, _fps, _size):
        return ClosedWriter()

    recorder = RecordingManager(
        tmp_path / "recordings",
        writer_fps=15.0,
        writer_factory=factory,
        candidates=(WriterCandidate("XXXX", ".avi", "Unavailable test codec", "AVI"),),
    )
    with pytest.raises(RecordingError, match="Could not start a video writer"):
        recorder.start(width=640, height=480)
    status = recorder.status_dict()
    assert status["state"] == "error"
    assert status["recording"] is False
    assert status["error"]
    assert "XXXX" in status["error"]
    leftover = [p for p in recorder.directory.iterdir() if p.is_file()]
    assert leftover == []


def test_client_supplied_paths_are_ignored_by_http(flask_app, tmp_path):
    client = flask_app.test_client()
    deadline = time.monotonic() + 5.0
    response = None
    while time.monotonic() < deadline:
        response = client.post(
            "/api/recording/start",
            json={"filename": "../escape.avi", "path": "/tmp/evil.avi"},
        )
        if response.status_code != 503:
            break
        time.sleep(0.05)
    assert response is not None
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["state"] == "recording"
    filename = data["current_filename"]
    assert is_safe_recording_filename(filename)
    assert ".." not in filename
    assert filename != "../escape.avi"

    time.sleep(0.8)
    stop = client.post(
        "/api/recording/stop",
        json={"filename": "other.avi", "path": "/tmp/other.avi"},
    )
    assert stop.status_code == 200
    stopped = stop.get_json()
    assert stopped["ok"] is True
    saved_name = stopped["last_filename"]
    assert saved_name == filename
    saved = tmp_path / "recordings" / saved_name
    assert saved.is_file()
    info = validate_recorded_file(
        saved, expected_width=640, expected_height=480, expected_min_frames=1
    )
    assert info["frames"] >= 1
    # The client-supplied names must not appear as files.
    assert not (tmp_path / "escape.avi").exists()


def test_http_start_twice_and_stop_when_idle(flask_app):
    client = flask_app.test_client()
    deadline = time.monotonic() + 5.0
    start = None
    while time.monotonic() < deadline:
        start = client.post("/api/recording/start")
        if start.status_code != 503:
            break
        time.sleep(0.05)
    assert start.status_code == 200
    second = client.post("/api/recording/start")
    assert second.status_code == 409
    data = second.get_json()
    assert data["ok"] is False
    assert "already" in data["error"].lower()
    assert data["state"] == "recording"

    time.sleep(0.6)
    stop = client.post("/api/recording/stop")
    assert stop.status_code == 200
    idle = client.post("/api/recording/stop")
    assert idle.status_code == 409
    idle_data = idle.get_json()
    assert idle_data["ok"] is False
    assert "no recording" in idle_data["error"].lower()


def test_http_start_without_frame_returns_503(tmp_path):
    config = build_config(
        source="synthetic",
        recording_dir=tmp_path / "recordings",
        snapshot_dir=tmp_path / "snapshots",
    )
    buffer = FrameBuffer()
    service = CaptureService(config, buffer)
    # Do not start capture, so no frames exist.
    app = create_app(config, service, buffer)
    client = app.test_client()
    response = client.post("/api/recording/start")
    assert response.status_code == 503
    data = response.get_json()
    assert data["ok"] is False
    assert "frame" in data["error"].lower()
    assert list((tmp_path / "recordings").glob("recording_*.avi")) == []
    service.stop(timeout=2.0)


def test_status_api_includes_recording_block(flask_app):
    client = flask_app.test_client()
    data = client.get("/api/status").get_json()
    recording = data["recording"]
    assert recording["state"] == "idle"
    assert recording["recording"] is False
    assert recording["writer_fps"] == 15.0
    assert recording["preferred_codec"] == "MJPG"
    assert recording["preferred_container"] == "AVI"
    assert "container timestamp rate" in recording["writer_fps_meaning"]


def test_index_page_has_recording_controls(flask_app):
    html = flask_app.test_client().get("/").get_data(as_text=True)
    assert "Start recording" in html
    assert "Stop recording" in html
    assert "Save snapshot" in html
    assert "Motion detection" in html
    assert "AVI" in html
    assert "Motion JPEG" in html


@pytest.mark.parametrize(
    "running_app",
    [["--source", "synthetic", "--server", "waitress"]],
    indirect=True,
)
def test_real_entry_point_records_playable_file(running_app, tmp_path):
    host, port = running_app.host, running_app.port
    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/")
        page = connection.getresponse()
        body = page.read().decode("utf-8", errors="replace")
        assert page.status == 200
        assert "Start recording" in body
        assert "Stop recording" in body
    finally:
        connection.close()

    deadline = time.monotonic() + 6.0
    payload = None
    status = None
    while time.monotonic() < deadline:
        connection = HTTPConnection(host, port, timeout=8)
        try:
            connection.request(
                "POST",
                "/api/recording/start",
                body=json.dumps({"filename": "../escape.avi", "path": "/tmp/x.avi"}),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            status = response.status
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
        if status == 200 and payload and payload.get("ok"):
            break
        if status == 503:
            time.sleep(0.05)
            continue
        break
    assert status == 200
    assert payload["ok"] is True
    assert payload["state"] == "recording"
    assert payload["codec"] == "MJPG"
    assert payload["container"] == "AVI"
    filename = payload["current_filename"]
    assert is_safe_recording_filename(filename)

    # Existing stream still works while recording.
    _response, parts = read_mjpeg_parts(host, port, count=2, timeout=8)
    assert len(parts) >= 2
    decode_jpeg(parts[0])

    time.sleep(1.4)
    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("POST", "/api/recording/stop")
        stop = connection.getresponse()
        stopped = json.loads(stop.read().decode("utf-8"))
        assert stop.status == 200
    finally:
        connection.close()
    assert stopped["ok"] is True
    assert stopped["state"] == "idle"
    saved = tmp_path / "recordings" / stopped["last_filename"]
    assert saved.is_file()
    info = validate_recorded_file(
        saved, expected_width=640, expected_height=480, expected_min_frames=3
    )
    assert info["frames"] >= 3
    cap_fps = info["reported_fps"]
    # Container timestamp rate should be the configured writer FPS (15).
    if cap_fps:
        assert abs(cap_fps - 15.0) < 0.5

    # Capture was not re-opened for recording.
    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/api/status")
        data = json.loads(connection.getresponse().read().decode("utf-8"))
    finally:
        connection.close()
    assert data["source_open_count"] == 1
    assert data["capture_start_count"] == 1


@pytest.mark.parametrize(
    "running_app",
    [["--source", "synthetic", "--server", "waitress"]],
    indirect=True,
)
def test_shutdown_during_recording_finalizes_or_errors_cleanly(running_app, tmp_path):
    host, port = running_app.host, running_app.port
    deadline = time.monotonic() + 6.0
    payload = None
    status = None
    while time.monotonic() < deadline:
        connection = HTTPConnection(host, port, timeout=8)
        try:
            connection.request("POST", "/api/recording/start")
            response = connection.getresponse()
            status = response.status
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
        if status == 200 and payload and payload.get("ok"):
            break
        if status == 503:
            time.sleep(0.05)
            continue
        break
    assert status == 200
    filename = payload["current_filename"]
    time.sleep(1.2)

    process = running_app.process
    process.send_signal(signal.SIGTERM)
    exit_deadline = time.monotonic() + 10.0
    return_code = None
    while time.monotonic() < exit_deadline:
        return_code = process.poll()
        if return_code is not None:
            break
        time.sleep(0.1)
    assert return_code is not None, "app.py did not exit after SIGTERM"
    assert return_code in {0, -signal.SIGTERM}

    saved = tmp_path / "recordings" / filename
    assert saved.exists(), "Shutdown dropped the recording path entirely."
    # Finalised success: the file opens and has frames. A clearly failed
    # shutdown must not leave a silently unreadable file claimed as success;
    # if the file cannot be opened, it should have been removed or be empty.
    if saved.is_file() and saved.stat().st_size > 0:
        info = validate_recorded_file(
            saved, expected_width=640, expected_height=480, expected_min_frames=1
        )
        assert info["frames"] >= 1
    else:
        pytest.fail("Shutdown left a missing or empty recording file.")


def test_writer_candidates_prefer_verified_mjpg_avi():
    assert WRITER_CANDIDATES[0].fourcc == "MJPG"
    assert WRITER_CANDIDATES[0].container == "AVI"
    assert WRITER_CANDIDATES[0].extension == ".avi"
