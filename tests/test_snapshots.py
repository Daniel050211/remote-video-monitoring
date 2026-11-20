"""Snapshot storage and HTTP tests. Files are written only under tmp dirs."""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from video_monitor.capture import CaptureService
from video_monitor.config import build_config
from video_monitor.frames import FrameBuffer
from video_monitor.processing import (
    decode_jpeg,
    encode_jpeg,
    prepare_display_frame,
    render_synthetic_frame,
)
from video_monitor.snapshots import (
    SAFE_FILENAME_PATTERN,
    SnapshotError,
    SnapshotStore,
    is_safe_snapshot_filename,
    resolve_under_directory,
    save_latest_frame,
)
from video_monitor.web import create_app


def _stamped_jpeg(width: int = 640, height: int = 480, index: int = 1) -> bytes:
    frame = render_synthetic_frame(width, height, index, 15.0)
    frame = prepare_display_frame(frame, timestamp_overlay=True)
    return encode_jpeg(frame, 80)


@pytest.mark.parametrize(
    "name",
    [
        "../secret.jpg",
        r"..\secret.jpg",
        "/tmp/evil.jpg",
        r"C:\Windows\x.jpg",
        "snapshot/../../etc/passwd",
        "data/snapshots/../README.md",
        "",
        ".",
        "..",
        "snapshot_20260101_000000_abcdabcd.png",
        "SNAPSHOT_20260101_000000_abcdabcd.jpg",
        "snapshot_20260101_000000_abcdabcd.jpg.exe",
        "foo.jpg",
        "snapshot_20260101_000000_zzzzzzzz.jpg",
        "snapshot_20260101_000000_abcdabcd.jpg/../../x",
        "snapshot_20260101_000000_abcdabcd",
        ".snapshot_20260101_000000_abcdabcd.jpg",
        "snapshot_2026-01-01_000000_abcdabcd.jpg",
    ],
)
def test_unsafe_names_are_rejected(name, tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    assert not is_safe_snapshot_filename(name)
    with pytest.raises(SnapshotError):
        resolve_under_directory(store.directory, name)


def test_safe_generated_name_resolves_inside_directory(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    name = "snapshot_20261117_223500_deadbeef.jpg"
    assert is_safe_snapshot_filename(name)
    resolved = resolve_under_directory(store.directory, name)
    assert resolved.parent == store.directory
    assert resolved.name == name
    assert resolved.is_relative_to(store.directory)


def test_save_jpeg_writes_unique_decodable_file(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    jpeg = _stamped_jpeg()
    saved = store.save_jpeg(jpeg, width=640, height=480, sequence=3)
    assert is_safe_snapshot_filename(saved.filename)
    assert SAFE_FILENAME_PATTERN.fullmatch(saved.filename)
    path = store.directory / saved.filename
    assert path.is_file()
    assert path.parent == store.directory.resolve()
    decoded = decode_jpeg(path.read_bytes())
    assert decoded.shape == (480, 640, 3)
    assert store.latest_filename() == saved.filename
    assert store.latest_path() == path
    # Response-style name is a basename, not an absolute path.
    assert "/" not in saved.filename
    assert "\\" not in saved.filename


def test_empty_or_non_jpeg_data_is_rejected(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    with pytest.raises(SnapshotError):
        store.save_jpeg(b"")
    with pytest.raises(SnapshotError):
        store.save_jpeg(b"not-a-jpeg")


def test_save_latest_frame_uses_shared_buffer_and_fails_without_frame(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    buffer = FrameBuffer()
    with pytest.raises(SnapshotError, match="No video frame is available yet"):
        save_latest_frame(buffer, store)
    jpeg = _stamped_jpeg()
    buffer.update(jpeg, 640, 480)
    saved = save_latest_frame(buffer, store)
    assert (store.directory / saved.filename).read_bytes() == jpeg
    assert saved.width == 640
    assert saved.height == 480
    assert saved.sequence == 0


def test_concurrent_saves_are_unique_and_not_torn(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    jpeg = _stamped_jpeg()
    results: list = []
    errors: list[BaseException] = []

    def worker():
        try:
            results.append(store.save_jpeg(jpeg, width=640, height=480))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert errors == []
    assert len(results) == 8
    names = [item.filename for item in results]
    assert len(set(names)) == 8
    leftover_tmps = list(store.directory.glob("*.tmp"))
    assert leftover_tmps == []
    for item in results:
        path = store.directory / item.filename
        decoded = decode_jpeg(path.read_bytes())
        assert decoded.shape == (480, 640, 3)


def test_post_snapshot_saves_current_frame(flask_app, tmp_path):
    client = flask_app.test_client()
    response = client.post("/api/snapshot")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert is_safe_snapshot_filename(data["filename"])
    assert data["width"] == 640
    assert data["height"] == 480
    saved = tmp_path / "snapshots" / data["filename"]
    assert saved.is_file()
    decoded = decode_jpeg(saved.read_bytes())
    assert decoded.shape == (480, 640, 3)
    latest = client.get("/api/snapshot/latest")
    assert latest.status_code == 200
    assert latest.content_type == "image/jpeg"
    assert latest.get_data() == saved.read_bytes()
    decode_jpeg(latest.get_data())


def test_post_snapshot_ignores_client_supplied_paths(flask_app, tmp_path):
    client = flask_app.test_client()
    response = client.post(
        "/api/snapshot?path=/etc/passwd&filename=../escape.jpg",
        json={"path": "/tmp/evil.jpg", "filename": "../README.md", "dir": str(tmp_path)},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    filename = data["filename"]
    assert is_safe_snapshot_filename(filename)
    assert ".." not in filename
    assert not filename.startswith("/")
    assert ":" not in filename
    saved = tmp_path / "snapshots" / filename
    assert saved.is_file()
    # Nothing was written from the client-supplied names.
    assert not (tmp_path / "evil.jpg").exists()
    project_readme = Path("/workspace/remote-video-monitoring/README.md")
    # The README size must be unchanged by this request; we only check it still
    # exists as a document and that no escape file was created next to it.
    assert project_readme.is_file()
    assert not (project_readme.parent / "escape.jpg").exists()


def test_snapshot_without_frame_returns_useful_error(tmp_path):
    config = build_config(source="synthetic")
    buffer = FrameBuffer()
    service = CaptureService(config, buffer)
    store = SnapshotStore(tmp_path / "snapshots")
    app = create_app(config, service, buffer, snapshot_store=store)
    client = app.test_client()
    response = client.post("/api/snapshot")
    assert response.status_code == 503
    data = response.get_json()
    assert data["ok"] is False
    assert "frame" in data["error"].lower()
    assert list((tmp_path / "snapshots").glob("*.jpg")) == []


def test_latest_snapshot_before_any_save_is_404(flask_app):
    client = flask_app.test_client()
    response = client.get("/api/snapshot/latest")
    assert response.status_code == 404
    data = response.get_json()
    assert data["ok"] is False


@pytest.mark.parametrize(
    "running_app",
    [["--source", "synthetic", "--server", "waitress"]],
    indirect=True,
)
def test_real_entry_point_snapshot_roundtrip(running_app, tmp_path):
    host, port = running_app.host, running_app.port
    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/")
        page = connection.getresponse()
        body = page.read().decode("utf-8", errors="replace")
        assert page.status == 200
        assert "Save snapshot" in body
    finally:
        connection.close()

    # Wait until the capture thread has published at least one frame.
    deadline = time.monotonic() + 6.0
    payload = None
    status = None
    while time.monotonic() < deadline:
        connection = HTTPConnection(host, port, timeout=8)
        try:
            connection.request(
                "POST",
                "/api/snapshot",
                body=json.dumps({"filename": "../escape.jpg", "path": "/tmp/x.jpg"}),
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
    filename = payload["filename"]
    assert is_safe_snapshot_filename(filename)
    saved = tmp_path / "snapshots" / filename
    assert saved.is_file()
    decoded = decode_jpeg(saved.read_bytes())
    assert decoded.shape == (480, 640, 3)

    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/api/snapshot/latest")
        latest = connection.getresponse()
        jpeg = latest.read()
        assert latest.status == 200
        assert "image/jpeg" in (latest.getheader("Content-Type") or "")
    finally:
        connection.close()
    assert jpeg == saved.read_bytes()
    decode_jpeg(jpeg)
