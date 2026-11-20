"""Safe local snapshot storage.

Snapshots are written only under a server-controlled directory. HTTP
clients cannot choose a filesystem path or filename. Filenames are
generated on the server (Hong Kong time plus a unique suffix).
"""

from __future__ import annotations

import os
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from video_monitor.frames import FrameBuffer

# Same clock as the on-frame overlay. Used only for the generated filename.
_FILENAME_TZ = ZoneInfo("Asia/Hong_Kong")

# snapshot_YYYYMMDD_HHMMSS_<8 lowercase hex chars>.jpg
SAFE_FILENAME_PATTERN = re.compile(r"^snapshot_\d{8}_\d{6}_[0-9a-f]{8}\.jpg$")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots"


class SnapshotError(Exception):
    """A snapshot could not be saved, or a path was rejected."""

    status_code = 500


class SnapshotUnavailable(SnapshotError):
    """No display frame is available in the shared buffer yet."""

    status_code = 503


@dataclass(frozen=True)
class SavedSnapshot:
    filename: str
    width: int
    height: int
    sequence: int
    size_bytes: int


def is_safe_snapshot_filename(name: str) -> bool:
    """Return True only for a server-generated snapshot basename."""
    if not isinstance(name, str) or not name or name != name.strip():
        return False
    if any(sep in name for sep in ("/", "\\", ":", "\x00")):
        return False
    if name.startswith(".") or ".." in name:
        return False
    return SAFE_FILENAME_PATTERN.fullmatch(name) is not None


def resolve_under_directory(directory: Path, filename: str) -> Path:
    """Resolve an allowlisted snapshot name under directory, or raise.

    Absolute paths, parent segments, and any name that does not match the
    generated-filename pattern are rejected. The resolved path must stay
    inside the snapshot directory.
    """
    if not is_safe_snapshot_filename(filename):
        raise SnapshotError("Invalid snapshot filename.")
    root = Path(directory).resolve()
    candidate = (root / filename).resolve()
    if not candidate.is_relative_to(root) or candidate.parent != root:
        raise SnapshotError("Snapshot path is outside the snapshot directory.")
    return candidate


class SnapshotStore:
    """Thread-safe writer for JPEG snapshots under one controlled directory."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._last_filename: str | None = None
        self.ensure_directory()

    def ensure_directory(self) -> Path:
        path = Path(self.directory)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SnapshotError("Could not create the snapshot directory.") from exc
        resolved = path.resolve()
        if not resolved.is_dir():
            raise SnapshotError("The snapshot path exists and is not a directory.")
        self.directory = resolved
        return resolved

    def save_jpeg(
        self,
        jpeg: bytes,
        *,
        width: int = 0,
        height: int = 0,
        sequence: int = -1,
        when: datetime | None = None,
    ) -> SavedSnapshot:
        if not jpeg:
            raise SnapshotError("Cannot save an empty snapshot.")
        if not jpeg.startswith(b"\xff\xd8"):
            raise SnapshotError("Snapshot data is not a JPEG image.")

        self.ensure_directory()
        moment = when or datetime.now(_FILENAME_TZ)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=_FILENAME_TZ)
        else:
            moment = moment.astimezone(_FILENAME_TZ)

        with self._lock:
            filename = self._allocate_filename(moment)
            final_path = self.directory / filename
            tmp_path = self.directory / f".{filename}.tmp"
            try:
                tmp_path.write_bytes(jpeg)
                os.replace(tmp_path, final_path)
            except OSError as exc:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
                raise SnapshotError("Could not write the snapshot file.") from exc
            self._last_filename = filename

        return SavedSnapshot(
            filename=filename,
            width=int(width),
            height=int(height),
            sequence=int(sequence),
            size_bytes=len(jpeg),
        )

    def latest_filename(self) -> str | None:
        with self._lock:
            return self._last_filename

    def latest_path(self) -> Path | None:
        name = self.latest_filename()
        if not name:
            return None
        try:
            path = resolve_under_directory(self.directory, name)
        except SnapshotError:
            return None
        if not path.is_file():
            return None
        return path

    def _allocate_filename(self, when: datetime) -> str:
        stamp = when.strftime("%Y%m%d_%H%M%S")
        for _ in range(32):
            name = f"snapshot_{stamp}_{secrets.token_hex(4)}.jpg"
            if not (self.directory / name).exists() and not (
                self.directory / f".{name}.tmp"
            ).exists():
                return name
        raise SnapshotError("Could not allocate a unique snapshot filename.")


def save_latest_frame(frame_buffer: FrameBuffer, store: SnapshotStore) -> SavedSnapshot:
    """Save the current shared display JPEG. Does not open a camera."""
    snapshot = frame_buffer.latest()
    if snapshot is None or not snapshot.jpeg:
        raise SnapshotUnavailable(
            "No video frame is available yet. Wait for the stream to start, then try again."
        )
    return store.save_jpeg(
        snapshot.jpeg,
        width=snapshot.width,
        height=snapshot.height,
        sequence=snapshot.sequence,
    )
