"""Configuration validation tests."""

from __future__ import annotations

import pytest

from video_monitor.config import (
    DEFAULT_MOTION_COOLDOWN_SECONDS,
    DEFAULT_MOTION_LOG_SIZE,
    DEFAULT_MOTION_SENSITIVITY,
    DEFAULT_SNAPSHOT_DIR,
    DEFAULT_RECORDING_DIR,
    DEFAULT_FACE_DETECTION_ENABLED,
    DEFAULT_FACE_DETECT_EVERY_N_FRAMES,
    DEFAULT_FACE_DETECT_SCALE,
    ConfigError,
    build_config,
    parse_args,
)
from video_monitor import faces as faces_mod
from video_monitor import motion as motion_mod


def test_defaults():
    config = build_config()
    assert config.host == "127.0.0.1"
    assert config.port == 5000
    assert config.source == "auto"
    assert config.width == 640
    assert config.height == 480
    assert config.fps == 15.0
    assert config.jpeg_quality == 80
    assert config.camera_index == 0
    assert config.server == "waitress"
    assert config.timestamp_overlay is True
    assert config.snapshot_dir == DEFAULT_SNAPSHOT_DIR
    assert config.recording_dir == DEFAULT_RECORDING_DIR
    assert config.motion_enabled is True
    assert config.motion_sensitivity == DEFAULT_MOTION_SENSITIVITY == 50
    assert config.motion_cooldown_seconds == DEFAULT_MOTION_COOLDOWN_SECONDS == 2.0
    assert config.motion_log_size == DEFAULT_MOTION_LOG_SIZE == 50
    assert DEFAULT_MOTION_SENSITIVITY == motion_mod.DEFAULT_SENSITIVITY
    assert DEFAULT_MOTION_COOLDOWN_SECONDS == motion_mod.DEFAULT_COOLDOWN_SECONDS
    assert DEFAULT_MOTION_LOG_SIZE == motion_mod.DEFAULT_LOG_SIZE
    assert config.face_detection_enabled is True
    assert config.face_detect_every_n_frames == DEFAULT_FACE_DETECT_EVERY_N_FRAMES == 2
    assert config.face_detect_scale == DEFAULT_FACE_DETECT_SCALE == 0.5
    assert DEFAULT_FACE_DETECTION_ENABLED is faces_mod.DEFAULT_ENABLED
    assert DEFAULT_FACE_DETECT_EVERY_N_FRAMES == faces_mod.DEFAULT_DETECT_EVERY_N_FRAMES
    assert DEFAULT_FACE_DETECT_SCALE == faces_mod.DEFAULT_DETECT_SCALE


@pytest.mark.parametrize(
    "kwargs",
    [
        {"port": 0},
        {"port": 70000},
        {"width": 10},
        {"height": 10},
        {"fps": 0},
        {"fps": 120},
        {"jpeg_quality": 0},
        {"jpeg_quality": 101},
        {"camera_index": -1},
        {"source": "webcam"},
        {"server": "gunicorn"},
        {"host": "/tmp/evil"},
        {"host": "C:\\Windows\\system32"},
        {"host": ""},
        {"timestamp_overlay": "maybe"},
        {"motion_enabled": "maybe"},
        {"motion_sensitivity": 0},
        {"motion_sensitivity": 101},
        {"motion_cooldown_seconds": -1},
        {"motion_cooldown_seconds": 60},
        {"motion_log_size": 1},
        {"motion_log_size": 999},
        {"face_detection_enabled": "maybe"},
        {"face_detect_every_n_frames": 0},
        {"face_detect_every_n_frames": 99},
        {"face_detect_scale": 0.1},
        {"face_detect_scale": 2.0},
    ],
)
def test_invalid_values_are_rejected(kwargs):
    with pytest.raises(ConfigError):
        build_config(**kwargs)


def test_parse_args_accepts_explicit_values():
    config = parse_args(
        [
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
            "--source",
            "synthetic",
            "--width",
            "320",
            "--height",
            "240",
            "--fps",
            "10",
            "--jpeg-quality",
            "60",
            "--camera-index",
            "1",
            "--server",
            "werkzeug",
        ]
    )
    assert config.host == "0.0.0.0"
    assert config.port == 8080
    assert config.source == "synthetic"
    assert config.width == 320
    assert config.height == 240
    assert config.fps == 10.0
    assert config.jpeg_quality == 60
    assert config.camera_index == 1
    assert config.server == "werkzeug"
    assert config.timestamp_overlay is True


def test_parse_args_no_timestamp_disables_overlay():
    config = parse_args(["--source", "synthetic", "--no-timestamp"])
    assert config.timestamp_overlay is False
    config_on = parse_args(["--source", "synthetic"])
    assert config_on.timestamp_overlay is True


def test_parse_args_rejects_bad_port():
    with pytest.raises(SystemExit):
        parse_args(["--port", "99999"])


def test_relative_snapshot_dir_stays_inside_project(tmp_path):
    config = parse_args(["--snapshot-dir", "data/snapshots"])
    assert config.snapshot_dir == DEFAULT_SNAPSHOT_DIR

    with pytest.raises(SystemExit):
        parse_args(["--snapshot-dir", "../outside-snapshots"])


def test_absolute_snapshot_dir_is_accepted_from_cli(tmp_path):
    target = tmp_path / "custom-snapshots"
    config = parse_args(["--snapshot-dir", str(target)])
    assert config.snapshot_dir == target.resolve()


def test_relative_recording_dir_stays_inside_project(tmp_path):
    config = parse_args(["--recording-dir", "data/recordings"])
    assert config.recording_dir == DEFAULT_RECORDING_DIR

    with pytest.raises(SystemExit):
        parse_args(["--recording-dir", "../outside-recordings"])


def test_absolute_recording_dir_is_accepted_from_cli(tmp_path):
    target = tmp_path / "custom-recordings"
    config = parse_args(["--recording-dir", str(target)])
    assert config.recording_dir == target.resolve()



def test_parse_args_no_motion_and_sensitivity():
    config = parse_args(
        [
            "--source",
            "synthetic",
            "--no-motion",
            "--motion-sensitivity",
            "80",
            "--motion-cooldown",
            "3.5",
            "--motion-log-size",
            "20",
        ]
    )
    assert config.motion_enabled is False
    assert config.motion_sensitivity == 80
    assert config.motion_cooldown_seconds == 3.5
    assert config.motion_log_size == 20
    enabled = parse_args(["--source", "synthetic"])
    assert enabled.motion_enabled is True
    assert enabled.motion_sensitivity == 50


def test_parse_args_no_faces_and_performance_flags():
    config = parse_args(
        [
            "--source",
            "synthetic",
            "--no-faces",
            "--face-detect-every",
            "3",
            "--face-detect-scale",
            "0.75",
        ]
    )
    assert config.face_detection_enabled is False
    assert config.face_detect_every_n_frames == 3
    assert config.face_detect_scale == 0.75
    enabled = parse_args(["--source", "synthetic"])
    assert enabled.face_detection_enabled is True
    assert enabled.face_detect_every_n_frames == 2
    assert enabled.face_detect_scale == 0.5
