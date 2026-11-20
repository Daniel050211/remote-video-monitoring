"""Thread-safe shared latest-frame buffer.

Viewers always read the most recent JPEG. Slow clients skip older frames
instead of growing an unbounded per-client queue.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class FrameSnapshot:
    jpeg: bytes
    sequence: int
    captured_at: float
    width: int
    height: int


class FrameBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._snapshot: FrameSnapshot | None = None

    def update(self, jpeg: bytes, width: int, height: int) -> int:
        if not jpeg:
            raise ValueError("Cannot store an empty JPEG frame.")
        with self._condition:
            sequence = 0 if self._snapshot is None else self._snapshot.sequence + 1
            self._snapshot = FrameSnapshot(
                jpeg=jpeg,
                sequence=sequence,
                captured_at=time.time(),
                width=width,
                height=height,
            )
            self._condition.notify_all()
            return sequence

    def latest(self) -> FrameSnapshot | None:
        with self._lock:
            return self._snapshot

    def wait_for_frame(
        self, last_sequence: int, timeout: float
    ) -> FrameSnapshot | None:
        """Return a newer snapshot than last_sequence, or the current one on timeout."""
        deadline = time.monotonic() + max(timeout, 0.0)
        with self._condition:
            while True:
                if self._snapshot is not None and self._snapshot.sequence != last_sequence:
                    return self._snapshot
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._snapshot
                self._condition.wait(remaining)
