# Test results

Status labels used in this project:

- Implemented but unverified
- Automatically verified
- Manually verified, with user-provided evidence
- Blocked

No result below is claimed without a command that was actually run.
Nothing here marks a real webcam, a real browser window, or a LAN
remote-PC demo as passed.

## Iteration 1 — 17 November 2026, about 22:22–22:26 HKT (Asia/Hong_Kong)

Environment: Linux, Python 3.13.5, project venv at
`/workspace/remote-video-monitoring/.venv`. Packages imported:
Flask 3.1.3, opencv-python 5.0.0.93 (cv2 5.0.0), Waitress 3.0.2,
pytest 9.2.0, Werkzeug 3.1.9.

### Commands and actual output

1. Syntax and import check

   `python -m compileall -q app.py video_monitor tests` — success
   (exit 0). `import app` and package imports succeeded.

2. Automated tests against the real `app.py` entry point and in-process
   components

   ```
   python -m pytest -v --tb=short
   ============================= 34 passed in 1.82s ==============================
   ```

   After a small change to flush startup logs:

   ```
   python -m pytest --tb=short
   34 passed in 1.88s
   ```

   Coverage of the required checks:

   | Check | Result | Status |
   |-------|--------|--------|
   | Synthetic source produces frames | Passed (unit + HTTP) | Automatically verified |
   | JPEG encode works | Passed; round-trip decode 640×480 | Automatically verified |
   | `GET /` returns 200 and the monitoring page | Passed | Automatically verified |
   | `GET /video_feed` yields multipart JPEG with a finite timeout | Passed; tests close after a few parts | Automatically verified |
   | Two concurrent clients do not start two captures | Passed; `capture_start_count` and `source_open_count` stayed 1 | Automatically verified |
   | Missing camera (`source=camera`, index 99999) returns a useful error and does not crash | Passed; process stayed up, `/api/status` had an error, stream still sent an information JPEG | Automatically verified |
   | Shutdown releases resources | Passed; capture thread joined, fake/real `VideoCapture.release()` called, `app.py` exited after SIGTERM | Automatically verified |
   | Real entry-point startup (`python app.py`) | Passed | Automatically verified |
   | Waitress long-lived MJPEG for two clients | Passed (see manual curl below) | Automatically verified |

   Werkzeug fallback (`--server werkzeug`) was implemented but **not**
   used as the default, because Waitress streamed successfully. It remains
   available if a later Windows check finds a problem.

3. Manual HTTP check of the same entry point (not a browser, not a camera)

   ```
   python app.py --source synthetic --host 127.0.0.1 --port 8765 --server waitress
   ```

   - `GET /` → HTTP 200, `Content-Type: text/html`, page title present.
   - `GET /api/status` → JSON with `ok=true`, `is_synthetic=true`,
     configured 640×480, fps 15.0, jpeg_quality 80,
     `stream_transport=MJPEG over HTTP (multipart/x-mixed-replace)`,
     `image_compression=JPEG`, `capture_start_count=1`,
     `source_open_count=1`.
   - `GET /video_feed` → HTTP 200,
     `Content-Type: multipart/x-mixed-replace; boundary=frame`,
     `Transfer-Encoding: chunked`. First part began with `--frame` and a
     decodable 640×480 JPEG. A 4-second curl read received 61 JPEG parts
     (~1.6 MB). Two overlapping 3-second curl clients each received 46
     JPEG parts (~1.2 MB each). Informal localhost observation only —
     not a formal FPS or latency measurement, and not a browser display
     rate.
   - SIGTERM stopped the process; port 8765 was free afterwards. No
     server was left running.

### Not verified in this iteration

| Item | Status |
|------|--------|
| Real webcam capture | Implemented but unverified |
| Local browser display of the stream | Implemented but unverified |
| Second computer viewing over a trusted LAN | Implemented but unverified |
| Windows Python 3.12.10 install and run | Implemented but unverified (PyPI wheels exist; runtime not executed) |
| Configured 15 FPS as a measured capture or browser rate | Not measured |
| End-to-end latency | Not measured |
| P1/P2 features (timestamp, snapshot, motion, recording, face detection) | Not implemented |

### Blocked

None for this slice. The absence of a webcam on the development box was
handled with the synthetic source and a simulated/unavailable camera
index; it did not block the automated tests.


## Iteration 2 — 17 November 2026, about 22:29–22:31 HKT (Asia/Hong_Kong)

Environment: Linux, Python 3.13.5, same project venv. Packages unchanged:
Flask 3.1.3, opencv-python 5.0.0.93 (cv2 5.0.0), Waitress 3.0.2,
pytest 9.2.0, Werkzeug 3.1.9. Timezone data came from the standard
library `zoneinfo` (`Asia/Hong_Kong`).

### Commands and actual output

1. Syntax check

   `python -m compileall -q app.py video_monitor tests` — success (exit 0).

2. Automated tests

   First run after the feature was added (one new test used the blue
   channel instead of the red channel when checking the synthetic
   banner after JPEG decode):

   ```
   python -m pytest -v --tb=short
   FAILED tests/test_timestamp.py::test_synthetic_source_frames_are_stamped_and_shared_by_viewers
   1 failed, 41 passed in 1.98s
   ```

   After a one-line fix in that test (check BGR channel 2, the red
   banner colour):

   ```
   python -m pytest -v --tb=short
   ============================== 42 passed in 1.90s ==============================
   ```

   All 34 iteration-1 checks still passed. New or extended coverage:

   | Check | Result | Status |
   |-------|--------|--------|
   | Timestamp string format (`YYYY-MM-DD HH:MM:SS HKT`) and UTC→HKT conversion | Passed | Automatically verified |
   | Overlay changes the bottom-right region versus the raw frame | Passed | Automatically verified |
   | Overlay is applied before JPEG encode; decoded JPEG differs from the unstamped frame | Passed | Automatically verified |
   | Two buffer readers see the same stamped JPEG (same sequence, same bytes) | Passed | Automatically verified |
   | Synthetic banner remains after stamping | Passed | Automatically verified |
   | `--no-timestamp` / `timestamp_overlay=False` leaves pixels unchanged | Passed | Automatically verified |
   | Missing-camera path does not crash; error JPEG is decodable and stamped | Passed | Automatically verified |
   | Default config enables the overlay; page and `/api/status` report it | Passed | Automatically verified |
   | Previous P0 behaviours (page, MJPEG timeout, two clients, shutdown) | Passed (same suite) | Automatically verified |

3. Manual HTTP check of the real entry point (not a browser, not a camera)

   ```
   python app.py --source synthetic --host 127.0.0.1 --port 33981 --server waitress
   ```

   - `GET /` → HTTP 200, page title present, "Timestamp overlay" and
     "On (HKT, UTC+8)" present.
   - `GET /api/status` → JSON with `ok=true`, `is_synthetic=true`,
     `timestamp_overlay=true`, `timestamp_timezone=Asia/Hong_Kong`,
     `timestamp_zone_label=HKT`, `timestamp_utc_offset=UTC+8`,
     configured 640×480 at 15 FPS (configured target), JPEG quality 80,
     transport MJPEG over HTTP, `capture_start_count=1`,
     `source_open_count=1`.
   - `GET /video_feed` → HTTP 200,
     `Content-Type: multipart/x-mixed-replace; boundary=frame`.
     Eight JPEG parts were read with a finite timeout (640×480,
     decodable). Informal observation: 8 parts in 0.519 s on localhost
     — **not** a formal capture-FPS or browser-FPS measurement.
   - A decoded sample JPEG from that stream showed the synthetic banner
     and a bottom-right stamp `2026-11-17 22:31:28 HKT`. This is a
     decoded HTTP part on the development box, not a browser screenshot
     and not a real webcam frame.
   - Two overlapping clients each received 3 JPEG parts with no errors.
     `capture_start_count` and `source_open_count` remained 1.
   - SIGTERM stopped the process (exit code -15). Port 33981 was free
     afterwards. No server was left running.

### Not verified in this iteration

| Item | Status |
|------|--------|
| Real webcam capture, including a readable stamp on camera frames | Implemented but unverified |
| Local browser display of the stamped stream | Implemented but unverified |
| Second computer viewing over a trusted LAN | Implemented but unverified |
| Windows Python 3.12.10 install and run | Implemented but unverified |
| Configured 15 FPS as a measured capture or browser rate | Not measured |
| End-to-end latency | Not measured |
| Snapshots, motion detection, recording, face detection | Not implemented |

### Blocked

None for this slice. The absence of a webcam on the development box was
handled with the synthetic source and the missing-camera path.


## Iteration 3 — 17 November 2026, about 22:34–22:36 HKT (Asia/Hong_Kong)

Environment: Linux, Python 3.13.5, same project venv. Packages unchanged:
Flask 3.1.3, opencv-python 5.0.0.93 (cv2 5.0.0), Waitress 3.0.2,
pytest 9.2.0, Werkzeug 3.1.9.

### Commands and actual output

1. Syntax check

   `python -m compileall -q app.py video_monitor tests` — success (exit 0).

2. Automated tests

   First runs after the feature was added failed three snapshot tests:
   the no-frame error message did not contain the substring used to
   choose HTTP 503, and one entry-point test was missing `import time`.
   After those two repairs (no product behaviour change beyond a correct
   503 status, plus the test import):

   ```
   python -m compileall -q app.py video_monitor tests
   python -m pytest -v --tb=short
   ============================== 72 passed in 2.41s ==============================
   ```

   All 42 iteration-1 and iteration-2 checks still passed. New coverage:

   | Check | Result | Status |
   |-------|--------|--------|
   | Snapshot writes a decodable JPEG under a temp directory | Passed; 640×480 | Automatically verified |
   | Filename is server-generated, unique, and a basename only | Passed | Automatically verified |
   | Path traversal, absolute paths, and unsafe names are rejected | Passed (parametrized) | Automatically verified |
   | Client-supplied path/filename in POST JSON or query is ignored | Passed | Automatically verified |
   | No frame in the buffer returns a useful error and does not crash | Passed; HTTP 503 | Automatically verified |
   | Concurrent snapshot writes are unique and not torn | Passed (8 threads) | Automatically verified |
   | `GET /api/snapshot/latest` serves the last saved JPEG from a fixed path | Passed | Automatically verified |
   | Real `python app.py` entry point can save and decode a snapshot | Passed | Automatically verified |
   | Previous P0/P1 behaviours (page, timestamp, MJPEG timeout, two clients, missing camera, shutdown) | Passed (same suite) | Automatically verified |

3. Manual HTTP check of the real entry point (not a browser, not a camera)

   ```
   python app.py --source synthetic --host 127.0.0.1 --port 42131 --server waitress --snapshot-dir <temp dir>
   ```

   - `GET /` → HTTP 200, page title present, "Save snapshot" present.
   - `GET /api/status` → JSON with `ok=true`, `is_synthetic=true`,
     `timestamp_overlay=true`, transport MJPEG over HTTP,
     `capture_start_count=1`, `source_open_count=1`. The first call
     in this check saw `frames_produced=0` (startup race; later
     activity proved frames were being produced).
   - `GET /video_feed` → HTTP 200,
     `Content-Type: multipart/x-mixed-replace; boundary=frame`.
     Four JPEG parts were read with a finite timeout (640×480,
     decodable). Informal observation: 4 parts in 0.252 s on localhost
     — **not** a formal capture-FPS or browser-FPS measurement.
   - Two overlapping clients each received 3 JPEG parts with no errors.
   - `POST /api/snapshot` with a body attempting `../escape.jpg` and
     `/tmp/evil.jpg` → HTTP 200,
     `{"ok": true, "filename": "snapshot_20261117_223629_b694ee7e.jpg",
     "width": 640, "height": 480}`. The filename is a basename, not
     an absolute path. The file in the temp directory was opened and
     decoded as a 640×480 JPEG (28,985 bytes). No escape file was
     created in the project directory.
   - `GET /api/snapshot/latest` → HTTP 200, `image/jpeg`, bytes
     identical to the saved file, decodable 640×480.
   - After the snapshot, `capture_start_count` and `source_open_count`
     remained 1.
   - SIGTERM stopped the process (exit code -15). Port 42131 was free
     afterwards. No server was left running. The temporary snapshot
     directory was removed after the check.

### Not verified in this iteration

| Item | Status |
|------|--------|
| Real webcam capture, including a snapshot of a camera frame | Implemented but unverified |
| Local browser use of the Save snapshot button | Implemented but unverified |
| Second computer viewing over a trusted LAN | Implemented but unverified |
| Windows Python 3.12.10 install and run | Implemented but unverified |
| Configured 15 FPS as a measured capture or browser rate | Not measured |
| End-to-end latency | Not measured |
| Motion detection, recording, face detection | Not implemented |

### Blocked

None for this slice. The absence of a webcam on the development box was
handled with the synthetic source and temporary snapshot directories.

## Iteration 4 — 17 November 2026, about 22:40–22:43 HKT (Asia/Hong_Kong)

Environment: Linux, Python 3.13.5, project venv at
`/workspace/remote-video-monitoring/.venv`. Same packages as iteration 3.
No webcam. The team's Windows PC was not used.

### Commands and actual output

1. Syntax check

   `python -m compileall -q app.py video_monitor tests` — success (exit 0).

2. Automated tests against the real `app.py` entry point and in-process
   components

   ```
   python -m pytest -v --tb=short
   ============================== 95 passed in 3.33s ==============================
   ```

   That was the final run after a small tweak to the default synthetic
   pattern (a mid-band moving block so a synthetic demo can exceed the
   default 2.12% threshold). An earlier run in this iteration, before
   that tweak, was also `95 passed in 3.42s`. All iteration 1–3 tests
   remained in the suite and passed.

   Coverage of the required checks:

   | Check | Result | Status |
   |-------|--------|--------|
   | Static synthetic scene does not flood the log | Passed; 10 identical 640×480 frames, cooldown 0, **0 events** | Automatically verified |
   | Deliberate-motion synthetic scene produces an event | Passed; large moving box at sensitivity 50, first frame baseline, second frame recorded an event | Automatically verified |
   | Disabling motion stops new events | Passed; moving frames after disable added no events; re-enable used a new baseline then recorded again | Automatically verified |
   | Cooldown prevents flooding | Passed; default 2.0 s with a test clock: 1 event, then no events for 1.0 s of continuous motion, then a second event at 2.1 s | Automatically verified |
   | Event log is bounded | Passed; 8 recorded events, capacity 5, log kept the latest 5 | Automatically verified |
   | Missing camera / no frames does not crash or spam | Passed; camera index 99999, 8+ information frames, 0 motion events | Automatically verified |
   | Existing stream, timestamp, and snapshot tests | Passed as part of the same 95-test run | Automatically verified |
   | Real `app.py` HTTP enable/disable and MJPEG | Passed (see below) | Automatically verified |

   Test setup notes (synthetic only):

   - Static scene: `render_static_synthetic_scene()` — fixed background
     and a still rectangle; pixels do not depend on frame index.
   - Deliberate-motion scene: `render_motion_synthetic_scene()` — the
     same background plus a large bright box that jumps each frame
     (about 1/4 of the width and 1/3 of the height). At default
     thresholds a consecutive pair changed about 8.7% of pixels.
   - Sensitivity 50 maps to pixel threshold 25 and about 2.12% minimum
     changed area. These are configured mappings, not measured accuracy.

3. Manual HTTP check of the same entry point (not a browser, not a camera)

   ```
   python app.py --source synthetic --host 127.0.0.1 --port 53623 --server waitress --snapshot-dir <temp dir>
   ```

   - `GET /` → HTTP 200, page included “Motion detection” and “Save snapshot”.
   - `GET /api/status` after about 13 produced frames → motion
     `enabled=true`, `sensitivity=50`, `cooldown_seconds=2.0`,
     `log_count=1`, `events_recorded_total=1`,
     `currently_detected=true`,
     `last_event_at=2026-11-17 22:43:14 HKT`,
     event message “Motion detected (4.2% of pixels changed)”,
     `frames_checked=13`. `frames_checked` is a count, not a frame rate.
   - `POST /api/motion` with `{"enabled": false, "path": "/tmp/evil"}`
     → `enabled=false`; the ignored path did not change storage.
     After 0.8 s, `events_recorded_total` was still 1 while
     `frames_produced` had risen to 25 and `currently_detected` was
     false.
   - Re-enable with `sensitivity=80` → `enabled=true`, `sensitivity=80`.
     `GET /api/motion/events` later reported `log_count=2`, capacity 50.
   - `GET /video_feed` → HTTP 200,
     `Content-Type: multipart/x-mixed-replace; boundary=frame`,
     4 decodable 640×480 JPEGs in 0.204 s on localhost (informal, not a
     measured FPS or browser rate).
   - `POST /api/snapshot` → 640×480 JPEG saved under the temp directory.
   - SIGTERM stopped the process (exit code -15). Port 53623 was free
     afterwards. No server was left running.

### Not verified in this iteration

| Item | Status |
|------|--------|
| Real webcam capture, including motion under real lighting | Implemented but unverified |
| Local browser use of the motion toggle, slider, badge, and log | Implemented but unverified |
| Second computer viewing over a trusted LAN | Implemented but unverified |
| Windows Python 3.12.10 install and run | Implemented but unverified |
| Configured 15 FPS as a measured capture or browser rate | Not measured |
| End-to-end latency | Not measured |
| Recording, face detection | Not implemented |

### Blocked

None for this slice. The absence of a webcam on the development box was
handled with static and deliberate-motion synthetic scenes.

## Iteration 5 — 17 November 2026, about 22:46–22:49 HKT (Asia/Hong_Kong)

Environment: Linux, Python 3.13.5, project venv at
`/workspace/remote-video-monitoring/.venv`. Same packages as iteration 4
(Flask 3.1.3, opencv-python 5.0.0.93 / cv2 5.0.0, Waitress 3.0.2,
pytest 9.2.0, Werkzeug 3.1.9). No webcam. The team's Windows PC was not
used. ffprobe/ffmpeg were available at `/usr/bin/ffprobe` and
`/usr/bin/ffmpeg`.

### Codec probe (executed before implementation)

30 synthetic 640×480 frames were written at a 15 FPS writer rate, then
opened with OpenCV `VideoCapture` and `ffprobe`.

| Writer | Container | Result on this Linux box |
|--------|-----------|--------------------------|
| MJPG (default and FFMPEG) | AVI (`.avi`) | Playable; ffprobe `codec_name=mjpeg`, 30 frames, 640×480, 15 FPS. **Preferred choice.** |
| XVID (default and FFMPEG) | AVI | Playable; ffprobe `codec_name=mpeg4`. Fallback only. |
| mp4v | MP4 | Playable; MPEG-4 Part 2. Not selected (keep AVI as the default container). |
| avc1 / H264 / X264 | MP4 | Failed to open (`h264_v4l2m2m` could not be configured). |
| MJPG via GStreamer | AVI | Failed to open. |

Windows codec availability: **Implemented but unverified**.

### Commands and actual output

1. Syntax check

   `python -m compileall -q app.py video_monitor tests` — success (exit 0).

2. Automated tests against the real `app.py` entry point and in-process
   components

   An earlier run in this iteration failed two HTTP tests because the
   recorder `status_dict()` `error` field overwrote the HTTP error
   string. After fixing the JSON field order:

   ```
   python -m pytest -v --tb=short
   ============================= 127 passed in 10.68s ==============================
   ```

   All iteration 1–4 tests remained in the suite and passed (95 tests
   at the end of iteration 4; this iteration added recording tests and
   a few config/UI assertions).

   Coverage of the required checks:

   | Check | Result | Status |
   |-------|--------|--------|
   | Start then stop creates a file under the controlled temp dir | Passed; server-generated `recording_YYYYMMDD_HHMMSS_<8-hex>.avi` | Automatically verified |
   | File opens and contains frames at the recorded size | Passed; OpenCV read-back, 640×480, tolerant frame count for elapsed test time | Automatically verified |
   | Starting twice while already recording is rejected | Passed; HTTP 409 / `RecordingConflict`; `source_open_count` stayed 1 | Automatically verified |
   | Stop when not recording is a useful error | Passed; HTTP 409, no crash, no file | Automatically verified |
   | Client-supplied paths/names are ignored | Passed; `../escape.avi` did not become the filename | Automatically verified |
   | Unavailable / failed writer is not reported as success | Passed; forced closed writer, error state, no leftover file | Automatically verified |
   | Stream, timestamp, snapshot, and motion tests still pass | Passed as part of the same 127-test run | Automatically verified |
   | Shutdown during an active recording finalises or errors cleanly | Passed; SIGTERM on `app.py` left a playable 640×480 file | Automatically verified |
   | Real `app.py` HTTP start/stop and file validation | Passed (see below) | Automatically verified |

3. Manual HTTP check of the same entry point (not a browser, not a camera)

   ```
   python app.py --source synthetic --host 127.0.0.1 --port 45561 --server waitress --snapshot-dir <temp dir> --recording-dir <temp dir>
   ```

   - `GET /` → HTTP 200; page included “Start recording”, “Stop recording”,
     “Save snapshot”, and “Motion detection”.
   - The first `POST /api/recording/start` immediately after startup
     returned HTTP 503 (no frame yet). The next start succeeded.
   - `POST /api/recording/start` with `{"path": "/tmp/evil.avi",
     "filename": "../escape.avi"}` → `ok=true`, `state=recording`,
     `codec=MJPG`, `container=AVI`, `writer_fps=15.0`,
     `current_filename=recording_20261117_224925_8db85e32.avi`.
     The client path was ignored.
   - `GET /api/status` while recording: `source_open_count=1`,
     `capture_start_count=1`,
     `stream_transport=MJPEG over HTTP (multipart/x-mixed-replace)`,
     `image_compression=JPEG`.
   - `GET /video_feed` → HTTP 200,
     `Content-Type: multipart/x-mixed-replace; boundary=frame`,
     4 decodable 640×480 JPEGs in 0.212 s on localhost (informal, not a
     measured FPS or browser rate).
   - `POST /api/snapshot` → 640×480 JPEG
     `snapshot_20261117_224925_f2bcc0a2.jpg`.
   - `POST /api/recording/stop` → `ok=true`, `state=idle`,
     `frames_written=34`, `validated_frames=34`, size 1026262 bytes.
   - OpenCV `VideoCapture` on the saved file: opened=true, **34 frames**,
     reported 640×480, first frame shape (480, 640, 3), reported FPS
     15.0 (configured writer/container timestamp rate).
   - ffprobe (exit 0) on the same file:

     - `codec_name=mjpeg`, `codec_long_name=Motion JPEG`,
       `codec_tag_string=MJPG`
     - `format_name=avi`, `format_long_name=AVI (Audio Video Interleaved)`
     - `width=640`, `height=480`, `nb_frames=34`
     - `r_frame_rate=15/1`, `duration=2.266667`, `size=1026262`
   - SIGTERM stopped the process (exit code -15). Port 45561 was free
     afterwards. No server was left running.

### Not verified in this iteration

| Item | Status |
|------|--------|
| Real webcam capture or recording | Implemented but unverified |
| Local browser Start/Stop controls and a desktop video player | Implemented but unverified |
| Second computer viewing over a trusted LAN | Implemented but unverified |
| Windows Python 3.12.10 install, run, and VideoWriter codec | Implemented but unverified |
| Configured 15 FPS as a measured capture or browser rate | Not measured (15 is the writer/container timestamp rate used in the file) |
| End-to-end latency | Not measured |
| Motion-triggered recording, face detection | Not implemented |

### Blocked

None for this slice. The absence of a webcam on the development box was
handled with the synthetic source and temporary recording directories.

## Iteration 6 — 17 November 2026, about 22:54–22:57 HKT (Asia/Hong_Kong)

Environment: Linux, Python 3.13.5, project venv at
`/workspace/remote-video-monitoring/.venv`. Packages imported:
Flask 3.1.3, opencv-contrib-python 5.0.0.93 (cv2 5.0.0; replaces
opencv-python of the same version so `cv2.CascadeClassifier` is
available), Waitress 3.0.2, pytest 9.2.0, Werkzeug 3.1.9.

### Commands and actual output

1. Syntax check

   `python -m compileall -q app.py video_monitor tests` — success
   (exit 0).

2. Automated tests against the real `app.py` entry point and in-process
   components

   ```
   python -m pytest -v --tb=short
   ============================= 146 passed in 12.21s ==============================
   ```

   Coverage of the required checks:

   | Check | Result | Status |
   |-------|--------|--------|
   | Iteration 1–5 regression (stream, timestamp, snapshot, motion, recording, missing camera, two clients, shutdown) | All previous tests remained in the suite and passed (127 tests at the end of iteration 5; 146 after this iteration) | Automatically verified |
   | Official bundled Haar cascade loads | Passed; `haarcascade_frontalface_default.xml` from `video_monitor/data/` is not empty | Automatically verified |
   | Enabled + documented fixture yields at least one detection | Passed; NASA / scikit-image `astronaut_face.png` (public domain; source and license in `tests/fixtures/SOURCE.txt`) produced ≥1 box at detect_scale 0.5 | Automatically verified |
   | Disabled + same fixture yields no boxes/events | Passed; count 0, no detection run | Automatically verified |
   | Plain synthetic pattern does not invent detections | Passed; 12 synthetic frames and the static synthetic scene had count 0 | Automatically verified |
   | Enable/disable via `POST /api/faces` | Passed; client path ignored; held boxes cleared when disabled | Automatically verified |
   | Two stream clients share one capture while detection is on | Passed; `capture_start_count` and `source_open_count` stayed 1 | Automatically verified |
   | Missing/empty frames do not invent faces or crash | Passed | Automatically verified |
   | Real `python app.py` HTTP check (synthetic) | Passed; see below | Automatically verified |
   | Real webcam / browser / LAN / Windows | Not run | Implemented but unverified |

   Positive fixture provenance (not a scraped personal photo):

   - File: `tests/fixtures/astronaut_face.png` (512×512 PNG)
   - Content: photograph of astronaut Eileen Collins
   - Obtained from: `https://raw.githubusercontent.com/scikit-image/scikit-image/v0.25.2/skimage/data/astronaut.png`
   - License as documented by scikit-image: no known copyright restrictions, public domain NASA photograph; NASA credited as the source
   - SHA-256: `88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5`

   Cascade provenance:

   - File: `video_monitor/data/haarcascade_frontalface_default.xml`
   - Official OpenCV 5 location: `opencv_contrib` branch `5.x`,
     `modules/xobjdetect/data/haarcascades/haarcascade_frontalface_default.xml`
   - License: Intel/OpenCV BSD-style text retained in the XML header
   - SHA-256: `0f7d4527844eb514d4a4948e822da90fbb16a34a0bbbbc6adc6498747a5aafb0`

3. Manual HTTP check of the same entry point (not a browser, not a camera)

   ```
   python app.py --source synthetic --host 127.0.0.1 --port 43489 --server waitress
   ```

   - `GET /` → HTTP 200; page included Face detection controls.
   - `GET /api/status` → faces `enabled=true`, `mode=detection`,
     `recognition=false`, `detected_count=0`,
     `cascade_name=haarcascade_frontalface_default.xml`,
     `cascade_source=bundled`, `cascade_loaded=true`,
     `detect_every_n_frames=2`, `detect_scale=0.5`, `error=null`,
     `source_open_count=1`, transport still MJPEG over HTTP.
   - `GET /video_feed` → HTTP 200,
     `Content-Type: multipart/x-mixed-replace; boundary=frame`,
     4 decodable 640×480 JPEGs in 0.219 s on localhost (informal, not a
     measured FPS or browser rate).
   - `POST /api/faces` with `{"enabled": false, "path": "../escape"}`
     → `ok=true`, `enabled=false`, `detected_count=0`; `path` was not
     echoed.
   - Re-enable → `enabled=true`, `recognition=false`.
   - `POST /api/snapshot` → 640×480 JPEG
     `snapshot_20261117_225740_9553ef3d.jpg`.
   - SIGTERM stopped the process (exit code -15). Port 43489 was free
     afterwards. No server was left running.

   An informal still-image microbenchmark on this box (used only to
   choose the default scale / every-Nth-frame trade-off, **not** a
   camera or browser measurement): about 18 ms at scale 1.0 and about
   6 ms at scale 0.5 on a 640×480 copy of the fixture.

### Not verified in this iteration

| Item | Status |
|------|--------|
| Real webcam face detection under real lighting and pose | Implemented but unverified |
| Local browser enable/disable, boxes, and count | Implemented but unverified |
| Second computer viewing over a trusted LAN | Implemented but unverified |
| Windows Python 3.12.10 install and run | Implemented but unverified |
| Configured 15 FPS as a measured capture or browser rate | Not measured |
| End-to-end latency | Not measured |
| Face recognition, identification, or tracking IDs | Not implemented (out of scope) |
| Motion-triggered recording | Not implemented |

### Blocked

None for this slice. The absence of a webcam on the development box was
handled with the synthetic source and a documented public-domain fixture.

