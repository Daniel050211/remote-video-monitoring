"""Image processing: timestamp overlay and JPEG compression.

Transport and container notes (for documentation, not implemented here):
- This module only compresses individual images as JPEG.
- The HTTP layer later sends those JPEGs as an MJPEG stream
  (multipart/x-mixed-replace). That is not H.264, H.265, or WebRTC.
"""

from __future__ import annotations

import math
from datetime import datetime

import cv2
import numpy as np
from zoneinfo import ZoneInfo

from video_monitor.config import MAX_JPEG_QUALITY, MIN_JPEG_QUALITY

# Clock used on every stamped frame. Hong Kong has no daylight-saving time,
# so HKT is UTC+8 year-round. zoneinfo provides the real IANA timezone.
TIMESTAMP_TIMEZONE = "Asia/Hong_Kong"
TIMESTAMP_ZONE_LABEL = "HKT"
TIMESTAMP_UTC_OFFSET = "UTC+8"
_TIMESTAMP_TZ = ZoneInfo(TIMESTAMP_TIMEZONE)


def format_timestamp(when: datetime | None = None) -> str:
    """Return a display timestamp in Asia/Hong_Kong (HKT, UTC+8).

    The string always looks like ``2026-11-17 22:28:05 HKT``.
    Naive datetimes are treated as already being in Asia/Hong_Kong.
    Aware datetimes are converted to Asia/Hong_Kong.
    """
    if when is None:
        moment = datetime.now(_TIMESTAMP_TZ)
    elif when.tzinfo is None:
        moment = when.replace(tzinfo=_TIMESTAMP_TZ)
    else:
        moment = when.astimezone(_TIMESTAMP_TZ)
    return moment.strftime(f"%Y-%m-%d %H:%M:%S {TIMESTAMP_ZONE_LABEL}")


def overlay_timestamp(
    frame: np.ndarray,
    text: str | None = None,
    when: datetime | None = None,
) -> np.ndarray:
    """Draw a readable timestamp on a BGR frame and return the same array.

    The overlay is drawn in place (cheap Hershey font, no external font
    file). Callers that must keep the original pixels should copy first.
    A dark background plus a dark outline keeps the white text readable
    on both light and dark scenes.
    """
    if frame is None or frame.size == 0:
        raise ValueError("Cannot overlay a timestamp on an empty frame.")
    label = text if text is not None else format_timestamp(when)
    height, width = frame.shape[:2]
    scale = 0.55 if width >= 480 else 0.45
    thickness = 1
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_w, text_h), baseline = cv2.getTextSize(label, font, scale, thickness)
    pad_x, pad_y = 8, 6
    margin = 8
    box_w = text_w + pad_x * 2
    box_h = text_h + baseline + pad_y * 2
    x2 = width - margin
    y2 = height - margin
    x1 = max(0, x2 - box_w)
    y1 = max(0, y2 - box_h)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 0), -1)
    origin = (x1 + pad_x, y2 - pad_y - baseline)
    cv2.putText(frame, label, origin, font, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(frame, label, origin, font, scale, (255, 255, 255), thickness, cv2.LINE_AA)
    return frame


def prepare_display_frame(
    frame: np.ndarray,
    timestamp_overlay: bool = True,
    when: datetime | None = None,
) -> np.ndarray:
    """Apply display processing that must happen once before JPEG encoding."""
    if timestamp_overlay:
        overlay_timestamp(frame, when=when)
    return frame


def encode_jpeg(frame: np.ndarray, quality: int) -> bytes:
    """Compress a BGR image to JPEG bytes using OpenCV."""
    quality = int(quality)
    if not MIN_JPEG_QUALITY <= quality <= MAX_JPEG_QUALITY:
        raise ValueError(
            "JPEG quality must be between "
            f"{MIN_JPEG_QUALITY} and {MAX_JPEG_QUALITY}."
        )
    if frame is None or frame.size == 0:
        raise ValueError("Cannot encode an empty frame.")
    ok, buffer = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), quality],
    )
    if not ok:
        raise RuntimeError("OpenCV failed to encode a JPEG frame.")
    return buffer.tobytes()


def decode_jpeg(data: bytes) -> np.ndarray:
    """Decode JPEG bytes to a BGR image. Useful in tests."""
    if not data:
        raise ValueError("Cannot decode empty JPEG data.")
    array = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("OpenCV failed to decode JPEG data.")
    return frame


SYNTHETIC_BANNER_BGR = (0, 0, 180)


def synthetic_banner_height_for(frame_height: int) -> int:
    """Return the painted height of the SYNTHETIC SOURCE banner."""
    return max(40, int(frame_height) // 10)


def detect_synthetic_source_banner_height(frame: np.ndarray) -> int:
    """Return the SYNTHETIC SOURCE banner height, or 0 if it is absent.

    ``render_synthetic_frame`` paints a full-width red bar of height
    ``synthetic_banner_height_for(height)`` in BGR (0, 0, 180). This
    inspects a mid-frame strip so left-hand banner text does not affect
    the check. It is intended for raw BGR frames, before JPEG encoding.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return 0
    height, width = frame.shape[:2]
    if height < 10 or width < 40:
        return 0
    expected = synthetic_banner_height_for(height)
    x0 = max(0, width // 2 - 16)
    x1 = min(width, x0 + 32)
    limit = min(expected, height)
    sample = frame[0:limit, x0:x1]
    blue = int(sample[:, :, 0].mean())
    green = int(sample[:, :, 1].mean())
    red = int(sample[:, :, 2].mean())
    if red < 150 or green > 40 or blue > 40:
        return 0
    # A fully red frame is not a banner. The bar should end near
    # the expected height, with a clearly different colour below.
    if limit < height:
        below = frame[limit : min(height, limit + 6), x0:x1]
        if below.size:
            below_red = int(below[:, :, 2].mean())
            below_green = int(below[:, :, 1].mean())
            below_blue = int(below[:, :, 0].mean())
            still_banner = (
                below_red >= 150 and below_green <= 40 and below_blue <= 40
            )
            if still_banner:
                return 0
    return expected


def render_synthetic_frame(
    width: int,
    height: int,
    frame_index: int,
    fps: float,
) -> np.ndarray:
    """Build a clearly labelled test pattern that changes every frame."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    # Dark teal background with a subtle moving tint so frames differ.
    tint = int(25 + 20 * math.sin(frame_index / max(fps, 1.0)))
    frame[:, :] = (40 + tint, 55, 30)

    # Light grid for a "monitor" look.
    grid_color = (70, 80, 55)
    step = 40
    for x in range(0, width, step):
        cv2.line(frame, (x, 0), (x, height), grid_color, 1)
    for y in range(0, height, step):
        cv2.line(frame, (0, y), (width, y), grid_color, 1)

    # Moving markers — prove the stream is live, not a still image.
    # The mid-band block is large enough that default motion detection
    # can record events during a synthetic demonstration. It stays clear
    # of the top banner and the bottom-right timestamp region.
    period = max(fps * 4.0, 1.0)
    angle = (frame_index / period) * 2.0 * math.pi
    radius_x = width * 0.32
    radius_y = height * 0.28
    cx = int(width / 2 + radius_x * math.sin(angle))
    cy = int(height / 2 + 20 + radius_y * math.cos(angle))
    cv2.circle(frame, (cx, cy), max(16, min(width, height) // 20), (0, 200, 255), -1)
    cv2.circle(frame, (cx, cy), max(16, min(width, height) // 20), (255, 255, 255), 2)

    bar_w = max(48, width // 5)
    bar_h = max(28, height // 8)
    bar_y = max(height // 3, (height - bar_h) // 2)
    # Keep the bar out of the bottom-right timestamp box and the top banner.
    banner_height = synthetic_banner_height_for(height)
    bar_y = min(max(bar_y, banner_height + 8), height - bar_h - 80)
    travel = max(1, width - bar_w - 24)
    step = max(40, width // 8)
    bar_x = 12 + int(frame_index * step) % travel
    cv2.rectangle(
        frame,
        (bar_x, bar_y),
        (bar_x + bar_w, bar_y + bar_h),
        (0, 180, 255),
        -1,
    )

    banner_height = synthetic_banner_height_for(height)
    cv2.rectangle(frame, (0, 0), (width, banner_height), SYNTHETIC_BANNER_BGR, -1)
    _put_text(
        frame,
        "SYNTHETIC SOURCE",
        (12, banner_height - 12),
        scale=0.9 if width >= 480 else 0.6,
        color=(255, 255, 255),
        thickness=2,
    )

    _put_text(
        frame,
        f"Frame {frame_index}",
        (12, height - 42),
        scale=0.6,
        color=(240, 240, 240),
        thickness=1,
    )
    _put_text(
        frame,
        f"{width}x{height}  configured {fps:g} FPS",
        (12, height - 16),
        scale=0.5,
        color=(200, 200, 200),
        thickness=1,
    )
    return frame


def render_message_frame(
    width: int,
    height: int,
    title: str,
    message: str,
    banner: str | None = None,
) -> np.ndarray:
    """Build a still information frame (errors, waiting, camera missing)."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = (36, 32, 28)

    if banner:
        cv2.rectangle(frame, (0, 0), (width, 40), (0, 90, 180), -1)
        _put_text(frame, banner, (12, 28), scale=0.7, color=(255, 255, 255), thickness=2)

    _put_text(
        frame,
        title,
        (24, height // 2 - 20),
        scale=0.9 if width >= 480 else 0.6,
        color=(80, 80, 240),
        thickness=2,
    )
    y = height // 2 + 20
    for line in _wrap_text(message, max_chars=max(24, width // 14)):
        _put_text(frame, line, (24, y), scale=0.55, color=(230, 230, 230), thickness=1)
        y += 28
    return frame


def _put_text(frame, text, origin, scale, color, thickness) -> None:
    cv2.putText(
        frame,
        text,
        origin,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def _wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines
