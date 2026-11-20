"""Shared test helpers. Streaming tests use a finite timeout and close early."""

from __future__ import annotations

import http.client
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from video_monitor.capture import CaptureService
from video_monitor.config import Config, build_config
from video_monitor.frames import FrameBuffer
from video_monitor.snapshots import SnapshotStore
from video_monitor.web import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise TimeoutError(f"Server at {host}:{port} did not start: {last_error}")


def read_mjpeg_parts(
    host: str,
    port: int,
    count: int = 1,
    timeout: float = 8.0,
    path: str = "/video_feed",
) -> tuple[http.client.HTTPResponse, list[bytes]]:
    """Read a finite number of JPEG parts, then close. Never wait forever."""
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    connection.request("GET", path)
    response = connection.getresponse()
    parts: list[bytes] = []
    buffer = b""
    deadline = time.monotonic() + timeout
    try:
        while len(parts) < count and time.monotonic() < deadline:
            chunk = response.read(4096)
            if not chunk:
                break
            buffer += chunk
            while True:
                start = buffer.find(b"\xff\xd8")
                end = buffer.find(b"\xff\xd9")
                if start != -1 and end != -1 and end > start:
                    parts.append(buffer[start : end + 2])
                    buffer = buffer[end + 2 :]
                else:
                    break
        return response, parts
    finally:
        connection.close()


@pytest.fixture
def synthetic_config(tmp_path) -> Config:
    return build_config(
        source="synthetic",
        width=640,
        height=480,
        fps=15,
        jpeg_quality=80,
        snapshot_dir=tmp_path / "snapshots",
        recording_dir=tmp_path / "recordings",
    )


@pytest.fixture
def capture_bundle(synthetic_config: Config):
    buffer = FrameBuffer()
    service = CaptureService(synthetic_config, buffer)
    service.start()
    deadline = time.monotonic() + 5.0
    while service.frames_produced < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    yield synthetic_config, service, buffer
    service.stop(timeout=5.0)


@pytest.fixture
def flask_app(capture_bundle, tmp_path):
    config, service, buffer = capture_bundle
    store = SnapshotStore(tmp_path / "snapshots")
    return create_app(config, service, buffer, snapshot_store=store)


class RunningApp:
    def __init__(self, process: subprocess.Popen, port: int, log_path: Path) -> None:
        self.process = process
        self.port = port
        self.host = "127.0.0.1"
        self.log_path = log_path

    def output(self) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def running_app(tmp_path, request) -> Iterator[RunningApp]:
    """Launch the real app.py entry point, then stop it cleanly."""
    port = unused_port()
    extra = list(getattr(request, "param", []))
    log_path = tmp_path / "server.log"
    command = [
        sys.executable,
        str(PROJECT_ROOT / "app.py"),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        *extra,
    ]
    if not any(arg == "--source" or arg.startswith("--source=") for arg in extra):
        command.extend(["--source", "synthetic"])
    if not any(arg == "--snapshot-dir" or arg.startswith("--snapshot-dir=") for arg in extra):
        command.extend(["--snapshot-dir", str(tmp_path / "snapshots")])
    if not any(arg == "--recording-dir" or arg.startswith("--recording-dir=") for arg in extra):
        command.extend(["--recording-dir", str(tmp_path / "recordings")])
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    try:
        wait_for_port("127.0.0.1", port, timeout=15.0)
    except Exception:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log_file.close()
        pytest.fail(f"app.py failed to start.\n{log_path.read_text(encoding='utf-8', errors='replace')}")
    try:
        yield RunningApp(process, port, log_path)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log_file.close()
