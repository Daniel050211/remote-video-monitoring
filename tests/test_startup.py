"""Startup, shutdown, and import checks against the real app.py entry point."""

from __future__ import annotations

import json
import signal
import time
from http.client import HTTPConnection

import pytest

from tests.conftest import read_mjpeg_parts
from video_monitor import __version__


def test_package_version_and_imports():
    import app as app_module
    import video_monitor.capture
    import video_monitor.config
    import video_monitor.frames
    import video_monitor.processing
    import video_monitor.server
    import video_monitor.snapshots
    import video_monitor.motion
    import video_monitor.recording
    import video_monitor.faces
    import video_monitor.web

    assert __version__
    assert callable(app_module.main)
    assert video_monitor.web.create_app
    assert video_monitor.server.run_server
    assert video_monitor.capture.CaptureService
    assert video_monitor.frames.FrameBuffer
    assert video_monitor.config.build_config
    assert video_monitor.processing.encode_jpeg
    assert video_monitor.snapshots.SnapshotStore
    assert video_monitor.motion.MotionDetector
    assert video_monitor.recording.RecordingManager
    assert video_monitor.faces.FaceDetector


@pytest.mark.parametrize("running_app", [["--source", "synthetic", "--server", "waitress"]], indirect=True)
def test_real_entry_point_starts_and_stops_cleanly(running_app):
    host, port = running_app.host, running_app.port
    connection = HTTPConnection(host, port, timeout=8)
    try:
        connection.request("GET", "/api/status")
        data = json.loads(connection.getresponse().read().decode("utf-8"))
    finally:
        connection.close()
    assert data["capture_running"] is True
    assert data["is_synthetic"] is True

    _response, parts = read_mjpeg_parts(host, port, count=1, timeout=8)
    assert parts

    process = running_app.process
    process.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + 10.0
    return_code = None
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            break
        time.sleep(0.1)
    assert return_code is not None, "app.py did not exit after SIGTERM within 10 seconds"
    # Waitress/Python typically exit 0 on SIGTERM; accept 0 or negative signal codes.
    assert return_code in {0, -signal.SIGTERM}
