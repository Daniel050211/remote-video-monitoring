"""Flask routes: monitoring page, status API, MJPEG stream, snapshots, and recording."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

from video_monitor.faces import FaceConfigError
from video_monitor.motion import MotionConfigError

from video_monitor.config import Config
from video_monitor.capture import CaptureService
from video_monitor.frames import FrameBuffer
from video_monitor.processing import encode_jpeg, prepare_display_frame, render_message_frame
from video_monitor.recording import RecordingError, RecordingManager
from video_monitor.snapshots import SnapshotError, SnapshotStore, save_latest_frame

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOUNDARY = "frame"
STALL_TIMEOUT_SECONDS = 1.0


def create_app(
    config: Config,
    capture_service: CaptureService,
    frame_buffer: FrameBuffer,
    snapshot_store: SnapshotStore | None = None,
    recorder: RecordingManager | None = None,
) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.config["DEBUG"] = False
    app.config["TESTING"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = True

    if snapshot_store is None:
        snapshot_store = SnapshotStore(config.snapshot_dir)
    else:
        snapshot_store.ensure_directory()

    if recorder is None:
        recorder = capture_service.recorder

    @app.get("/")
    def index():
        return render_template("index.html", config=config)

    @app.get("/api/status")
    def api_status():
        return jsonify(capture_service.status_dict())

    @app.get("/api/motion/events")
    def api_motion_events():
        motion = capture_service.motion.status_dict()
        return jsonify(
            {
                "ok": True,
                "enabled": motion["enabled"],
                "log_count": motion["log_count"],
                "log_capacity": motion["log_capacity"],
                "events": motion["events"],
            }
        )

    @app.post("/api/motion")
    def api_motion():
        # Runtime enable/disable and sensitivity. Unknown keys such as
        # path or filename are ignored. Clients cannot set a filesystem path.
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return jsonify(
                {"ok": False, "error": "Motion settings must be a JSON object."}
            ), 400
        try:
            if "enabled" in payload:
                capture_service.motion.set_enabled(_as_request_bool(payload["enabled"]))
            if "sensitivity" in payload:
                capture_service.motion.set_sensitivity(payload["sensitivity"])
        except (MotionConfigError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        status = capture_service.motion.status_dict()
        return jsonify({"ok": True, **status})

    @app.post("/api/faces")
    def api_faces():
        # Runtime enable/disable. Unknown keys such as path or filename
        # are ignored. Clients cannot set a filesystem path. This endpoint
        # only toggles detection; it does not perform recognition.
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return jsonify(
                {"ok": False, "error": "Face-detection settings must be a JSON object."}
            ), 400
        try:
            if "enabled" in payload:
                capture_service.faces.set_enabled(_as_request_bool(payload["enabled"]))
        except (FaceConfigError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        status = capture_service.faces.status_dict()
        return jsonify({"ok": True, **status})

    @app.get("/video_feed")
    def video_feed():
        return Response(
            stream_mjpeg(frame_buffer, config),
            mimetype=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/snapshot")
    def api_snapshot():
        # Storage path and filename are chosen on the server. Any
        # client-supplied path, filename, or JSON body is ignored.
        try:
            saved = save_latest_frame(frame_buffer, snapshot_store)
        except SnapshotError as exc:
            return jsonify({"ok": False, "error": str(exc)}), exc.status_code
        return jsonify(
            {
                "ok": True,
                "filename": saved.filename,
                "width": saved.width,
                "height": saved.height,
            }
        )

    @app.get("/api/snapshot/latest")
    def api_snapshot_latest():
        path = snapshot_store.latest_path()
        if path is None:
            return jsonify(
                {"ok": False, "error": "No snapshot has been saved yet."}
            ), 404
        return send_file(
            path,
            mimetype="image/jpeg",
            as_attachment=False,
            download_name=path.name,
            max_age=0,
            etag=False,
            conditional=False,
        )

    @app.post("/api/recording/start")
    def api_recording_start():
        # Storage path and filename are chosen on the server. Any
        # client-supplied path, filename, or JSON body is ignored.
        request.get_json(silent=True)
        snapshot = frame_buffer.latest()
        if snapshot is None or snapshot.width <= 0 or snapshot.height <= 0:
            payload = {
                **recorder.status_dict(),
                "ok": False,
                "error": (
                    "No video frame is available yet. Wait for the stream "
                    "to start, then try again."
                ),
            }
            return jsonify(payload), 503
        try:
            recorder.start(width=snapshot.width, height=snapshot.height)
        except RecordingError as exc:
            return jsonify(
                {**recorder.status_dict(), "ok": False, "error": str(exc)}
            ), exc.status_code
        return jsonify({**recorder.status_dict(), "ok": True, "error": None})

    @app.post("/api/recording/stop")
    def api_recording_stop():
        request.get_json(silent=True)
        try:
            status = recorder.stop()
        except RecordingError as exc:
            return jsonify(
                {**recorder.status_dict(), "ok": False, "error": str(exc)}
            ), exc.status_code
        return jsonify({**status, "ok": True, "error": None})

    @app.get("/favicon.ico")
    def favicon():
        return send_file(
            PROJECT_ROOT / "static" / "favicon.ico",
            mimetype="image/x-icon",
            max_age=86400,
            conditional=True,
        )

    return app


def pack_mjpeg_part(jpeg: bytes) -> bytes:
    return (
        b"--" + BOUNDARY.encode("ascii") + b"\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg)).encode("ascii") + b"\r\n"
        b"\r\n" + jpeg + b"\r\n"
    )


def stream_mjpeg(frame_buffer: FrameBuffer, config: Config):
    """Yield an endless MJPEG multipart body.

    Callers (tests and browsers) must close the HTTP connection when they
    are done. Never wait for this generator to finish on its own.
    """
    last_sequence = -1
    while True:
        snapshot = frame_buffer.wait_for_frame(last_sequence, STALL_TIMEOUT_SECONDS)
        if snapshot is None:
            waiting = render_message_frame(
                config.width,
                config.height,
                "WAITING",
                "Starting video source...",
            )
            waiting = prepare_display_frame(
                waiting,
                timestamp_overlay=config.timestamp_overlay,
            )
            yield pack_mjpeg_part(encode_jpeg(waiting, config.jpeg_quality))
            continue
        if snapshot.sequence == last_sequence:
            continue
        last_sequence = snapshot.sequence
        yield pack_mjpeg_part(snapshot.jpeg)


def _as_request_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValueError("enabled must be true or false.")
