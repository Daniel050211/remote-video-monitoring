"""Command-line configuration and input validation."""

from __future__ import annotations

import argparse
import socket
from pathlib import Path
from dataclasses import dataclass

ALLOWED_SOURCES = ("auto", "camera", "synthetic")
ALLOWED_SERVERS = ("waitress", "werkzeug")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT_DIR = _PROJECT_ROOT / "data" / "snapshots"
DEFAULT_RECORDING_DIR = _PROJECT_ROOT / "data" / "recordings"

MIN_WIDTH, MAX_WIDTH = 160, 1920
MIN_HEIGHT, MAX_HEIGHT = 120, 1080
MIN_FPS, MAX_FPS = 1.0, 60.0
MIN_JPEG_QUALITY, MAX_JPEG_QUALITY = 1, 100
MIN_PORT, MAX_PORT = 1, 65535

# Keep these numeric defaults here so config can load without importing
# the OpenCV-backed motion module (avoids a config <-> motion cycle).
# tests/test_config.py checks that they stay aligned with video_monitor.motion.
MIN_MOTION_SENSITIVITY, MAX_MOTION_SENSITIVITY = 1, 100
DEFAULT_MOTION_SENSITIVITY = 50
MIN_MOTION_COOLDOWN_SECONDS, MAX_MOTION_COOLDOWN_SECONDS = 0.0, 30.0
DEFAULT_MOTION_COOLDOWN_SECONDS = 2.0
MIN_MOTION_LOG_SIZE, MAX_MOTION_LOG_SIZE = 5, 200
DEFAULT_MOTION_LOG_SIZE = 50

# Face-detection defaults live here so config can load without importing
# the OpenCV-backed faces module (avoids a config <-> faces cycle).
# tests/test_config.py checks that they stay aligned with video_monitor.faces.
DEFAULT_FACE_DETECTION_ENABLED = True
MIN_FACE_DETECT_EVERY_N_FRAMES, MAX_FACE_DETECT_EVERY_N_FRAMES = 1, 15
DEFAULT_FACE_DETECT_EVERY_N_FRAMES = 2
MIN_FACE_DETECT_SCALE, MAX_FACE_DETECT_SCALE = 0.25, 1.0
DEFAULT_FACE_DETECT_SCALE = 0.5


class ConfigError(ValueError):
    """Raised when a configuration value is invalid."""


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 5000
    source: str = "auto"
    width: int = 640
    height: int = 480
    fps: float = 15.0
    jpeg_quality: int = 80
    camera_index: int = 0
    server: str = "waitress"
    timestamp_overlay: bool = True
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR
    recording_dir: Path = DEFAULT_RECORDING_DIR
    motion_enabled: bool = True
    motion_sensitivity: int = DEFAULT_MOTION_SENSITIVITY
    motion_cooldown_seconds: float = DEFAULT_MOTION_COOLDOWN_SECONDS
    motion_log_size: int = DEFAULT_MOTION_LOG_SIZE
    face_detection_enabled: bool = DEFAULT_FACE_DETECTION_ENABLED
    face_detect_every_n_frames: int = DEFAULT_FACE_DETECT_EVERY_N_FRAMES
    face_detect_scale: float = DEFAULT_FACE_DETECT_SCALE


def build_config(
    host: str = "127.0.0.1",
    port: int = 5000,
    source: str = "auto",
    width: int = 640,
    height: int = 480,
    fps: float = 15.0,
    jpeg_quality: int = 80,
    camera_index: int = 0,
    server: str = "waitress",
    timestamp_overlay: bool = True,
    snapshot_dir: str | Path | None = None,
    recording_dir: str | Path | None = None,
    motion_enabled: bool = True,
    motion_sensitivity: int = DEFAULT_MOTION_SENSITIVITY,
    motion_cooldown_seconds: float = DEFAULT_MOTION_COOLDOWN_SECONDS,
    motion_log_size: int = DEFAULT_MOTION_LOG_SIZE,
    face_detection_enabled: bool = DEFAULT_FACE_DETECTION_ENABLED,
    face_detect_every_n_frames: int = DEFAULT_FACE_DETECT_EVERY_N_FRAMES,
    face_detect_scale: float = DEFAULT_FACE_DETECT_SCALE,
) -> Config:
    """Validate and return a Config. Raises ConfigError on bad input."""
    host = _validate_host(host)
    port = _as_int("port", port)
    if not MIN_PORT <= port <= MAX_PORT:
        raise ConfigError(f"port must be between {MIN_PORT} and {MAX_PORT}.")

    source = str(source).strip().lower()
    if source not in ALLOWED_SOURCES:
        raise ConfigError(
            f"source must be one of: {', '.join(ALLOWED_SOURCES)}."
        )

    width = _as_int("width", width)
    height = _as_int("height", height)
    if not MIN_WIDTH <= width <= MAX_WIDTH:
        raise ConfigError(
            f"width must be between {MIN_WIDTH} and {MAX_WIDTH} pixels."
        )
    if not MIN_HEIGHT <= height <= MAX_HEIGHT:
        raise ConfigError(
            f"height must be between {MIN_HEIGHT} and {MAX_HEIGHT} pixels."
        )

    try:
        fps = float(fps)
    except (TypeError, ValueError) as exc:
        raise ConfigError("fps must be a number.") from exc
    if not MIN_FPS <= fps <= MAX_FPS:
        raise ConfigError(f"fps must be between {MIN_FPS:g} and {MAX_FPS:g}.")

    jpeg_quality = _as_int("jpeg-quality", jpeg_quality)
    if not MIN_JPEG_QUALITY <= jpeg_quality <= MAX_JPEG_QUALITY:
        raise ConfigError(
            "jpeg-quality must be between "
            f"{MIN_JPEG_QUALITY} and {MAX_JPEG_QUALITY}."
        )

    camera_index = _as_int("camera-index", camera_index)
    if camera_index < 0:
        raise ConfigError("camera-index must be 0 or a positive integer.")

    server = str(server).strip().lower()
    if server not in ALLOWED_SERVERS:
        raise ConfigError(
            f"server must be one of: {', '.join(ALLOWED_SERVERS)}."
        )

    timestamp_overlay = _as_bool("timestamp-overlay", timestamp_overlay)
    resolved_snapshot_dir = _resolve_controlled_dir(
        snapshot_dir,
        default=DEFAULT_SNAPSHOT_DIR,
        flag_name="snapshot-dir",
    )
    resolved_recording_dir = _resolve_controlled_dir(
        recording_dir,
        default=DEFAULT_RECORDING_DIR,
        flag_name="recording-dir",
    )
    motion_enabled = _as_bool("motion-enabled", motion_enabled)
    # Imported lazily to keep config importable without a motion/OpenCV cycle.
    from video_monitor.motion import (
        MotionConfigError,
        validate_cooldown,
        validate_log_size,
        validate_sensitivity,
    )

    try:
        motion_sensitivity = validate_sensitivity(motion_sensitivity)
        motion_cooldown_seconds = validate_cooldown(motion_cooldown_seconds)
        motion_log_size = validate_log_size(motion_log_size)
    except MotionConfigError as exc:
        raise ConfigError(str(exc)) from exc

    face_detection_enabled = _as_bool("face-detection-enabled", face_detection_enabled)
    from video_monitor.faces import (
        FaceConfigError,
        validate_detect_every_n_frames,
        validate_detect_scale,
    )

    try:
        face_detect_every_n_frames = validate_detect_every_n_frames(
            face_detect_every_n_frames
        )
        face_detect_scale = validate_detect_scale(face_detect_scale)
    except FaceConfigError as exc:
        raise ConfigError(str(exc)) from exc

    return Config(
        host=host,
        port=port,
        source=source,
        width=width,
        height=height,
        fps=fps,
        jpeg_quality=jpeg_quality,
        camera_index=camera_index,
        server=server,
        timestamp_overlay=timestamp_overlay,
        snapshot_dir=resolved_snapshot_dir,
        recording_dir=resolved_recording_dir,
        motion_enabled=motion_enabled,
        motion_sensitivity=motion_sensitivity,
        motion_cooldown_seconds=motion_cooldown_seconds,
        motion_log_size=motion_log_size,
        face_detection_enabled=face_detection_enabled,
        face_detect_every_n_frames=face_detect_every_n_frames,
        face_detect_scale=face_detect_scale,
    )


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        description=(
            "Remote Video Monitoring server. "
            "Default bind is 127.0.0.1 (this computer only)."
        )
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address. Default: 127.0.0.1. Use 0.0.0.0 only on a trusted LAN.",
    )
    parser.add_argument("--port", type=int, default=5000, help="TCP port (default: 5000).")
    parser.add_argument(
        "--source",
        choices=ALLOWED_SOURCES,
        default="auto",
        help="Video source. 'auto' tries the camera, then falls back to synthetic.",
    )
    parser.add_argument("--width", type=int, default=640, help="Configured capture width.")
    parser.add_argument("--height", type=int, default=480, help="Configured capture height.")
    parser.add_argument(
        "--fps",
        type=float,
        default=15.0,
        help="Configured capture loop target FPS (not a measured browser FPS).",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=80,
        dest="jpeg_quality",
        help="JPEG quality 1-100 (default: 80).",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        dest="camera_index",
        help="OpenCV camera index (default: 0).",
    )
    parser.add_argument(
        "--server",
        choices=ALLOWED_SERVERS,
        default="waitress",
        help="WSGI server (default: waitress). Use werkzeug only as a fallback.",
    )
    parser.add_argument(
        "--no-timestamp",
        action="store_true",
        help="Disable the timestamp overlay (enabled by default, Asia/Hong_Kong HKT).",
    )
    parser.add_argument(
        "--snapshot-dir",
        default=None,
        dest="snapshot_dir",
        help=(
            "Directory for saved JPEG snapshots. Default: data/snapshots "
            "under the project (not committed). Clients cannot choose this path."
        ),
    )
    parser.add_argument(
        "--recording-dir",
        default=None,
        dest="recording_dir",
        help=(
            "Directory for manual recordings. Default: data/recordings "
            "under the project (not committed). Relative paths must stay "
            "inside the project. Clients cannot choose this path."
        ),
    )
    parser.add_argument(
        "--no-motion",
        action="store_true",
        help="Disable motion detection at startup (enabled by default).",
    )
    parser.add_argument(
        "--motion-sensitivity",
        type=int,
        default=DEFAULT_MOTION_SENSITIVITY,
        dest="motion_sensitivity",
        help=(
            f"Motion sensitivity {MIN_MOTION_SENSITIVITY}-{MAX_MOTION_SENSITIVITY} "
            f"(default: {DEFAULT_MOTION_SENSITIVITY}). Higher values treat "
            "smaller changes as motion."
        ),
    )
    parser.add_argument(
        "--motion-cooldown",
        type=float,
        default=DEFAULT_MOTION_COOLDOWN_SECONDS,
        dest="motion_cooldown_seconds",
        help=(
            f"Seconds to wait before logging another motion event "
            f"(default: {DEFAULT_MOTION_COOLDOWN_SECONDS:g}; "
            f"range {MIN_MOTION_COOLDOWN_SECONDS:g}-{MAX_MOTION_COOLDOWN_SECONDS:g}). "
            "The on-screen MOTION mark is not delayed by this cooldown."
        ),
    )
    parser.add_argument(
        "--motion-log-size",
        type=int,
        default=DEFAULT_MOTION_LOG_SIZE,
        dest="motion_log_size",
        help=(
            f"Maximum motion-event log length "
            f"(default: {DEFAULT_MOTION_LOG_SIZE}; "
            f"range {MIN_MOTION_LOG_SIZE}-{MAX_MOTION_LOG_SIZE}). Oldest events are dropped."
        ),
    )
    parser.add_argument(
        "--no-faces",
        action="store_true",
        help="Disable face detection at startup (enabled by default). Detection only, not recognition.",
    )
    parser.add_argument(
        "--face-detect-every",
        type=int,
        default=DEFAULT_FACE_DETECT_EVERY_N_FRAMES,
        dest="face_detect_every_n_frames",
        help=(
            f"Run Haar detection every Nth frame "
            f"(default: {DEFAULT_FACE_DETECT_EVERY_N_FRAMES}; "
            f"range {MIN_FACE_DETECT_EVERY_N_FRAMES}-{MAX_FACE_DETECT_EVERY_N_FRAMES}). "
            "A configured trade-off, not a measured camera or browser FPS. "
            "Boxes from the last detection are reused on skipped frames."
        ),
    )
    parser.add_argument(
        "--face-detect-scale",
        type=float,
        default=DEFAULT_FACE_DETECT_SCALE,
        dest="face_detect_scale",
        help=(
            f"Scale applied to a copy of the frame before Haar detection "
            f"(default: {DEFAULT_FACE_DETECT_SCALE:g}; "
            f"range {MIN_FACE_DETECT_SCALE:g}-{MAX_FACE_DETECT_SCALE:g}). "
            "A configured trade-off, not a measured camera or browser FPS."
        ),
    )
    args = parser.parse_args(argv)
    try:
        return build_config(
            host=args.host,
            port=args.port,
            source=args.source,
            width=args.width,
            height=args.height,
            fps=args.fps,
            jpeg_quality=args.jpeg_quality,
            camera_index=args.camera_index,
            server=args.server,
            timestamp_overlay=not args.no_timestamp,
            snapshot_dir=args.snapshot_dir,
            recording_dir=args.recording_dir,
            motion_enabled=not args.no_motion,
            motion_sensitivity=args.motion_sensitivity,
            motion_cooldown_seconds=args.motion_cooldown_seconds,
            motion_log_size=args.motion_log_size,
            face_detection_enabled=not args.no_faces,
            face_detect_every_n_frames=args.face_detect_every_n_frames,
            face_detect_scale=args.face_detect_scale,
        )
    except ConfigError as exc:
        parser.error(str(exc))
        raise  # pragma: no cover — parser.error already exits


def _resolve_controlled_dir(
    value: str | Path | None,
    *,
    default: Path,
    flag_name: str,
) -> Path:
    """Resolve a server-controlled directory from operator config, not client input.

    Relative paths must stay inside the project directory (same rule for
    snapshots and recordings). Absolute paths are accepted for tests and
    custom operator locations.
    """
    if value is None:
        return default
    if not isinstance(value, (str, Path)):
        raise ConfigError(f"{flag_name} must be a directory path.")
    raw_text = str(value).strip()
    if not raw_text or "\x00" in raw_text:
        raise ConfigError(f"{flag_name} must be a non-empty directory path.")
    raw = Path(raw_text)
    if not raw.is_absolute():
        resolved = (_PROJECT_ROOT / raw).resolve()
        if not resolved.is_relative_to(_PROJECT_ROOT.resolve()):
            raise ConfigError(
                f"A relative {flag_name} must stay inside the project directory."
            )
        return resolved
    return raw.resolve()


def _resolve_snapshot_dir(snapshot_dir: str | Path | None) -> Path:
    """Resolve the snapshot directory from operator config, not client input."""
    return _resolve_controlled_dir(
        snapshot_dir,
        default=DEFAULT_SNAPSHOT_DIR,
        flag_name="snapshot-dir",
    )


def _as_bool(name: str, value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"{name} must be a boolean (true/false).")


def _as_int(name: str, value: object) -> int:
    try:
        if isinstance(value, bool):
            raise TypeError
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer.") from exc
    return number


def _validate_host(host: object) -> str:
    if not isinstance(host, str):
        raise ConfigError("host must be a text address, not a file path.")
    value = host.strip()
    if not value or len(value) > 253:
        raise ConfigError("host must be a non-empty bind address.")
    if "/" in value or "\\" in value or ":" in value and value.count(":") > 7:
        # Reject filesystem paths. IPv6 is allowed via inet_pton below.
        if "/" in value or "\\" in value:
            raise ConfigError("host must be an IP address or hostname, not a file path.")

    if value in {"localhost", "0.0.0.0"}:
        return value

    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, value)
            return value
        except OSError:
            continue

    # Simple hostname: letters, digits, dots, hyphens only.
    labels = value.split(".")
    if not labels or any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
        or not all(c.isalnum() or c == "-" for c in label)
        for label in labels
    ):
        raise ConfigError(
            "host must be a valid IPv4/IPv6 address or a simple hostname."
        )
    return value
