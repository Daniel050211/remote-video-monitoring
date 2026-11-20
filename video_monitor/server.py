"""Process startup, HTTP server selection, and clean shutdown."""

from __future__ import annotations

import atexit
import sys

from waitress import serve

from video_monitor.capture import CaptureService
from video_monitor.config import Config
from video_monitor.frames import FrameBuffer
from video_monitor.snapshots import SnapshotStore, PROJECT_ROOT
from video_monitor.web import create_app

LAN_WARNING = """
WARNING: The server is binding to {host}:{port}, which can accept connections
from other computers. Use this only on a trusted local network for a course
demonstration. This is not a production-secure surveillance system.
Do not expose it to the public Internet, and do not forward this port
through a router or cloud firewall.
"""


def run_server(config: Config) -> None:
    frame_buffer = FrameBuffer()
    capture_service = CaptureService(config, frame_buffer)
    snapshot_store = SnapshotStore(config.snapshot_dir)
    capture_service.start()
    app = create_app(config, capture_service, frame_buffer, snapshot_store)

    stopped = {"done": False}

    def shutdown() -> None:
        if stopped["done"]:
            return
        stopped["done"] = True
        # CaptureService.stop() also finalises an active recording.
        capture_service.stop()

    atexit.register(shutdown)
    _print_startup(config, capture_service, snapshot_store)

    if _is_non_local_bind(config.host):
        print(LAN_WARNING.format(host=config.host, port=config.port), file=sys.stderr)

    try:
        if config.server == "waitress":
            # Several worker threads are required so two long-lived MJPEG
            # clients and the status/page routes can run at the same time.
            serve(
                app,
                host=config.host,
                port=config.port,
                threads=8,
                channel_timeout=120,
                ident="remote-video-monitoring",
            )
        elif config.server == "werkzeug":
            # Fallback only. Reloader stays off so the camera is not opened twice.
            app.run(
                host=config.host,
                port=config.port,
                debug=False,
                use_reloader=False,
                threaded=True,
            )
        else:
            raise ValueError(f"Unsupported server: {config.server}")
    finally:
        shutdown()


def _is_non_local_bind(host: str) -> bool:
    return host not in {"127.0.0.1", "localhost", "::1"}


def _print_startup(
    config: Config,
    capture_service: CaptureService,
    snapshot_store: SnapshotStore,
) -> None:
    status = capture_service.status_dict()
    display_host = "127.0.0.1" if config.host in {"0.0.0.0", "::"} else config.host
    def _banner(message: str) -> None:
        print(message, flush=True)

    _banner("Remote Video Monitoring")
    _banner("  Entry point : python app.py")
    _banner(f"  HTTP server : {config.server}")
    _banner(f"  Page        : http://{display_host}:{config.port}/")
    _banner(f"  Stream      : http://{display_host}:{config.port}/video_feed")
    _banner(f"  Status API  : http://{display_host}:{config.port}/api/status")
    _banner(
        "  Configured  : "
        f"{config.width}x{config.height} at {config.fps:g} FPS "
        f"(configured target, not a measured browser rate), "
        f"JPEG quality {config.jpeg_quality}"
    )
    _banner(f"  Source      : requested={config.source}, active={status['active_source']}")
    overlay = (
        "on (Asia/Hong_Kong, HKT, UTC+8)"
        if config.timestamp_overlay
        else "off"
    )
    _banner(f"  Timestamp   : {overlay}")
    try:
        snapshot_display = snapshot_store.directory.relative_to(PROJECT_ROOT)
    except ValueError:
        snapshot_display = snapshot_store.directory.name
    _banner(
        f"  Snapshots   : {snapshot_display} "
        "(server-generated JPEG names, not committed)"
    )
    recorder = capture_service.recorder
    rec_status = recorder.status_dict()
    try:
        recording_display = recorder.directory.relative_to(PROJECT_ROOT)
    except ValueError:
        recording_display = recorder.directory.name
    _banner(
        f"  Recordings  : {recording_display} "
        f"(manual start/stop; preferred "
        f"{rec_status['preferred_codec']} in "
        f"{rec_status['preferred_container']}; "
        "writer FPS is the configured container timestamp rate)"
    )
    motion_state = "on" if config.motion_enabled else "off"
    _banner(
        f"  Motion      : {motion_state}, sensitivity {config.motion_sensitivity} "
        f"(1=least, 100=most), cooldown {config.motion_cooldown_seconds:g}s, "
        f"log bound {config.motion_log_size}"
    )
    face_state = "on" if config.face_detection_enabled else "off"
    _banner(
        f"  Faces       : {face_state} (detection only, not recognition), "
        f"Haar cascade haarcascade_frontalface_default.xml, "
        f"every {config.face_detect_every_n_frames} frame(s), "
        f"scale {config.face_detect_scale:g} "
        f"(configured trade-off, not a measured FPS)"
    )
    _banner(
        "  Transport   : MJPEG over HTTP "
        "(multipart/x-mixed-replace, JPEG images). Not H.264/H.265/WebRTC."
    )
    _banner(
        "  Recording   : Motion JPEG (MJPG) in an AVI container when the "
        "writer is available. This is a saved file, not the live HTTP "
        "stream, and not H.264 or WebRTC. Windows codec support is unverified."
    )
    if status["notice"]:
        _banner(f"  Notice      : {status['notice']}")
    if status["error"]:
        _banner(f"  Error       : {status['error']}")
    _banner("Press Ctrl+C to stop. The capture thread will be released on shutdown.")
