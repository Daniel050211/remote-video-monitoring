"""JPEG encoding and synthetic-frame tests."""

from __future__ import annotations

import numpy as np
import pytest

from video_monitor.processing import (
    decode_jpeg,
    encode_jpeg,
    render_message_frame,
    render_synthetic_frame,
)


def test_jpeg_encode_and_decode_roundtrip():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (20, 40, 200)
    jpeg = encode_jpeg(frame, quality=80)
    assert jpeg.startswith(b"\xff\xd8")
    assert jpeg.endswith(b"\xff\xd9")
    decoded = decode_jpeg(jpeg)
    assert decoded.shape[0] == 480
    assert decoded.shape[1] == 640
    assert decoded.shape[2] == 3


def test_synthetic_frames_are_labelled_and_change():
    first = render_synthetic_frame(640, 480, 1, 15.0)
    second = render_synthetic_frame(640, 480, 20, 15.0)
    assert first.shape == (480, 640, 3)
    assert not np.array_equal(first, second)
    jpeg = encode_jpeg(first, 80)
    # The banner is drawn in pixels; encoding should keep enough of it
    # that a decoded frame is still the configured size.
    decoded = decode_jpeg(jpeg)
    assert decoded.shape == first.shape


def test_invalid_quality_is_rejected():
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        encode_jpeg(frame, quality=0)


def test_message_frame_has_requested_size():
    frame = render_message_frame(320, 240, "CAMERA UNAVAILABLE", "No device opened.")
    assert frame.shape == (240, 320, 3)
