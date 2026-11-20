# Progress log

## Iteration 1 — first runnable vertical slice

Date: 17 November 2026, 22:18–22:26 HKT (Asia/Hong_Kong).
Environment: Linux development box, Python 3.13.5, no webcam used.
The team's Windows PC was not used.

### Objective

Build the smallest working path in `/workspace/remote-video-monitoring`:
synthetic or test video source → JPEG compression → MJPEG over HTTP →
simple monitoring page. Run automated tests on this box. Do not implement
P1/P2 features.

### Files created (single project directory; one entry point: `app.py`)

- `app.py`, `requirements.txt`, `.gitignore`, `pytest.ini`, `README.md`
- `video_monitor/` — `config.py`, `frames.py`, `processing.py`, `capture.py`,
  `web.py`, `server.py`
- `templates/index.html`, `static/style.css`, `static/app.js`
- `tests/` — config, processing, capture, web, and startup tests
- `docs/` — architecture, progress, test results, demo checklist, report
  outline, and copies of the course brief and report template under
  `docs/references/`
- `.venv/` — project-local virtual environment (gitignored)

### Commands actually executed

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install flask opencv-python waitress pytest
# Then pinned the imported versions in requirements.txt and:
pip install -r requirements.txt   # already satisfied after pinning
python -m compileall -q app.py video_monitor tests
python -c "import app; ..."
python -m pytest -v --tb=short
python app.py --source synthetic --host 127.0.0.1 --port 8765 --server waitress
# HTTP checks with curl against /, /api/status, and /video_feed
# (two overlapping curl clients). Then SIGTERM; the process exited and
# port 8765 was free.
python -m pytest --tb=short   # rerun after a small startup-log flush fix
```

Installed and imported versions on this box: Flask 3.1.3, Werkzeug 3.1.9,
opencv-python 5.0.0.93 (cv2 5.0.0), Waitress 3.0.2, pytest 9.2.0,
NumPy 2.5.5.

### Results

- `python -m pytest -v`: **34 passed in 1.82s**, then **34 passed in 1.88s**
  after the log-flush change. No failures.
- `GET /` returned 200 with the monitoring page.
- `GET /api/status` reported `active_source=synthetic`, configured
  640×480 at 15 FPS, JPEG quality 80, one capture instance.
- Waitress served a long-lived MJPEG stream (`Content-Type:
  multipart/x-mixed-replace; boundary=frame`, `Transfer-Encoding:
  chunked`). It did not appear to buffer the stream unusable: curl
  received JPEG parts immediately. A 4-second curl read collected 61
  JPEG parts (640×480, decodable). Two overlapping 3-second curl
  clients each collected 46 JPEG parts. These counts are informal
  observations of HTTP parts received on localhost; they are **not** a
  formal capture-FPS or browser-FPS measurement.
- Missing-camera path (`--source camera --camera-index 99999`) kept the
  process running and returned a useful error on `/api/status`.
- Shutdown with SIGTERM stopped the process and released the port.

### Limitations

- No webcam was available or used. `source=auto` was not formally
  measured against a real device on this box.
- No desktop browser was opened; the page and stream were checked over
  HTTP (pytest and curl).
- Windows Python 3.12.10 was not executed. PyPI has matching wheels
  for the pinned direct dependencies; that is not a runtime test.
- End-to-end latency was not measured.
- P1/P2 features are not implemented.

### Pending manual verification

- Real webcam capture on the team's Windows PC.
- Local browser display (Chrome/Firefox) of the live stream.
- Viewing from a second computer on a trusted LAN.
- Visual confirmation of the UI, including the synthetic-source banner.

### Known issues

- OpenCV's requested 640×480 may be adjusted by a real camera driver.
  The status API reports configured size and, when different, the size
  reported by the capture device.
- Binding to `0.0.0.0` is documented for a later trusted-LAN demo only.
  It is not production-secure and was not used for testing.
- Course brief typo: page 1 says the report is due “November 39, 2026
  (Sunday)”; the Assessment section says “November 29, 2026 (Sunday)”.
  29 November 2026 is a Sunday and is treated as the intended deadline.

### Next action

Keep this directory and `app.py` as the only application. Next iteration
should support the students' Windows manual P0 checks (venv, webcam,
local browser). After those are evidenced, add the first P1 item
(timestamp overlay) only if the baseline stream stays stable.


## Iteration 2 — timestamp overlay (P1 item 1)

Date: 17 November 2026, 22:29–22:31 HKT (Asia/Hong_Kong).
Environment: Linux development box, Python 3.13.5, project venv at
`/workspace/remote-video-monitoring/.venv`. No webcam used. The team's
Windows PC was not used. Work stayed in the existing project directory
and the existing `app.py` entry point.

### Objective

Add a readable current-time overlay to every outgoing display/stream
frame, applied once in the capture/processing path before JPEG encoding.
Do not add snapshots, motion detection, recording, or face detection.

### Files changed (in place; no renamed app copies)

- `video_monitor/processing.py` — `format_timestamp()`, `overlay_timestamp()`,
  `prepare_display_frame()`
- `video_monitor/config.py` — `timestamp_overlay` (default on), `--no-timestamp`
- `video_monitor/capture.py` — overlay once in the capture loop before encode
- `video_monitor/web.py` — waiting-frame path uses the same helper
- `video_monitor/server.py` — startup log notes the clock
- `templates/index.html`, `static/app.js` — status pill "Timestamp overlay"
- `tests/test_timestamp.py` — new focused tests
- `tests/test_config.py`, `tests/test_web.py` — default/flag and status/page checks
- `README.md`, `docs/architecture.md`, `docs/progress.md`,
  `docs/test-results.md`, `docs/demo-checklist.md`

### Commands actually executed

```bash
source .venv/bin/activate
python -m compileall -q app.py video_monitor tests
python -m pytest -v --tb=short
# First run: 41 passed, 1 failed (banner colour-channel typo in a new test).
# After a one-line test fix:
python -m pytest -v --tb=short
# 42 passed in 1.90s
python app.py --source synthetic --host 127.0.0.1 --port 33981 --server waitress
# HTTP checks against /, /api/status, and /video_feed (finite timeout,
# two overlapping clients). Then SIGTERM; the process exited and the
# port was free.
```

### Results

- Final pytest run: **42 passed in 1.90s**. The original 34 iteration-1
  behaviours still passed; 8 new/extended checks cover the overlay.
- Timestamp format is `YYYY-MM-DD HH:MM:SS HKT`, using
  `zoneinfo.ZoneInfo("Asia/Hong_Kong")` (UTC+8, no DST).
- Overlay is drawn once on the capture thread before `cv2.imencode`.
  Two viewers reading the same `FrameBuffer` snapshot receive identical
  JPEG bytes.
- Missing-camera path still serves a decodable information frame and
  does not crash; the error frame is also stamped.
- Manual HTTP check of `python app.py`: `GET /` 200, status API reported
  `timestamp_overlay=true` and timezone `Asia/Hong_Kong` / `HKT` /
  `UTC+8`, MJPEG `multipart/x-mixed-replace; boundary=frame` delivered
  decodable 640×480 JPEGs. A decoded sample from the stream showed
  `2026-11-17 22:31:28 HKT` in the bottom-right corner and still showed
  the `SYNTHETIC SOURCE` banner. Two concurrent clients each received
  3 parts; `capture_start_count` and `source_open_count` stayed 1.
  Informal part counts only — not a measured capture or browser FPS.
- The server was stopped with SIGTERM (process exit -15); port 33981
  was free afterwards.

### Limitations

- No webcam was used. Overlay on a real camera image is unimplemented
  in the sense of verification only; the same code path will stamp
  camera frames, but that has not been seen.
- No desktop browser was opened; the page and stream were checked over
  HTTP (pytest and a short `app.py` client).
- End-to-end latency and measured FPS were not collected.
- Snapshots, motion detection, recording, and face detection are not
  implemented.

### Pending manual verification

- Real webcam capture on the team's Windows PC, with the timestamp
  readable on live camera frames.
- Local browser display (Chrome/Firefox) of the stamped stream.
- Viewing from a second computer on a trusted LAN.

### Known issues

- A real camera may not honour the configured 640×480; the status API
  still reports both sizes.
- The first `/api/status` call immediately after startup can show
  `frames_produced=0` if it wins the race before the first captured
  frame. Later calls increase the counter. This is a startup timing
  observation, not a hang.
- Course brief typo (November 39 vs 29) is unchanged: 29 November 2026
  is treated as the report deadline.

### Next action

Keep this directory and `app.py` as the only application. Next
iteration should add snapshot capture with safe local storage, without
disturbing the stamped MJPEG path.


## Iteration 3 — snapshot capture (P1 item 2)

Date: 17 November 2026, 22:34–22:36 HKT (Asia/Hong_Kong).
Environment: Linux development box, Python 3.13.5, project venv at
`/workspace/remote-video-monitoring/.venv`. No webcam used. The team's
Windows PC was not used. Work stayed in the existing project directory
and the existing `app.py` entry point. No renamed application copies
were created.

### Objective

Add snapshot capture with safe local storage, triggered from the
monitoring page, without disturbing the stamped MJPEG path. Do not add
motion detection, recording, or face detection.

### Files changed (in place; no renamed app copies)

- `video_monitor/snapshots.py` — new storage module (path checks, unique
  names, atomic writes, latest-file helper)
- `video_monitor/config.py` — `snapshot_dir` (default `data/snapshots/`),
  `--snapshot-dir`
- `video_monitor/web.py` — `POST /api/snapshot`, `GET /api/snapshot/latest`
- `video_monitor/server.py` — create the store at startup and log it
- `templates/index.html`, `static/app.js`, `static/style.css` — Save
  snapshot button, last result, last-image preview
- `tests/test_snapshots.py` — new tests (temp dirs only)
- `tests/conftest.py`, `tests/test_config.py`, `tests/test_web.py`,
  `tests/test_startup.py` — fixture and regression updates
- `.gitignore`, `README.md`, `docs/architecture.md`, `docs/progress.md`,
  `docs/test-results.md`, `docs/demo-checklist.md`, `docs/report-outline.md`

### Commands actually executed

```bash
source .venv/bin/activate
python -m compileall -q app.py video_monitor tests
python -m pytest -v --tb=short
# After a status-code match fix and a missing `import time` in one test:
python -m compileall -q app.py video_monitor tests
python -m pytest -v --tb=short
# 72 passed in 2.41s
python app.py --source synthetic --host 127.0.0.1 --port 42131 --server waitress --snapshot-dir <temp dir>
# HTTP checks against /, /api/status, /video_feed (finite timeout, two
# overlapping clients), POST /api/snapshot (client-supplied path ignored),
# and GET /api/snapshot/latest. Saved JPEG opened and decoded. Then
# SIGTERM; the process exited and the port was free.
```

### Results

- Final pytest run: **72 passed in 2.41s**. The previous 42 iteration-1
  and iteration-2 checks still passed.
- Snapshots are saved under a server-controlled directory (default
  `data/snapshots/`, gitignored). The HTTP API never accepts a client
  path or filename. Names are `snapshot_YYYYMMDD_HHMMSS_<8-hex>.jpg`.
- Concurrent writes use a lock, a unique suffix, and `os.replace` after
  a temp file, so names do not collide and files are not torn.
- If no frame is in the shared buffer yet, `POST /api/snapshot` returns
  HTTP 503 and a useful error; the process does not crash.
- Manual HTTP check of `python app.py`: `GET /` 200 with a "Save
  snapshot" button; status API still reported one synthetic capture
  with the HKT overlay; MJPEG delivered decodable 640×480 JPEGs (4
  parts in 0.252 s on localhost — informal, not a measured FPS). Two
  concurrent clients each received 3 parts; `capture_start_count` and
  `source_open_count` stayed 1. `POST /api/snapshot` with a body of
  `{"filename":"../escape.jpg","path":"/tmp/evil.jpg"}` still returned
  `ok=true` and `filename=snapshot_20261117_223629_b694ee7e.jpg` (basename
  only). That file was opened and decoded as a 640×480 JPEG (28,985
  bytes). `GET /api/snapshot/latest` returned the same bytes. No
  escape file was created. The server was stopped with SIGTERM (exit
  -15); port 42131 was free afterwards.

### Limitations

- No webcam was used. A snapshot of a real camera frame uses the same
  path, but that has not been seen.
- No desktop browser was opened; the button and POST were checked over
  HTTP (pytest and a short `app.py` client).
- End-to-end latency and measured FPS were not collected.
- Motion detection, recording, and face detection are not implemented.

### Pending manual verification

- Real webcam capture on the team's Windows PC, including a snapshot
  of a live camera frame.
- Local browser use of the Save snapshot button, and confirmation that
  the file appears under `data/snapshots/`.
- Viewing from a second computer on a trusted LAN.

### Known issues

- A real camera may not honour the configured 640×480; the status API
  still reports both sizes.
- The first `/api/status` call immediately after startup can show
  `frames_produced=0` if it wins the race before the first captured
  frame. Later calls increase the counter. A snapshot requested in
  that window returns HTTP 503 until a frame exists.
- Course brief typo (November 39 vs 29) is unchanged: 29 November 2026
  is treated as the report deadline.

### Next action

Keep this directory and `app.py` as the only application. Next
iteration should add motion detection (enable/disable, sensitivity,
visual indicator, cooldown, and a bounded event log) without
disturbing the stamped MJPEG path or snapshots.

## Iteration 4 — P1 motion detection

Date: 17 November 2026, 22:40–22:43 HKT (Asia/Hong_Kong).
Environment: Linux development box, Python 3.13.5, project venv at
`/workspace/remote-video-monitoring/.venv`. No webcam used. The team's
Windows PC was not used. Work stayed in the existing project directory
and the existing `app.py` entry point.

### Objective

Add motion detection with enable/disable, sensitivity, a visual
indicator, a 2.0 s event cooldown, and a bounded event log. Run
detection once on the capture/processing thread. Do not add recording
or face detection.

### Files changed (in place; no app_v2 or duplicate entry point)

- `video_monitor/motion.py` — new detector, cooldown, bounded log,
  static and deliberate-motion synthetic scenes, MOTION badge
- `video_monitor/config.py` — `--no-motion`, `--motion-sensitivity`,
  `--motion-cooldown`, `--motion-log-size`, and validated defaults
- `video_monitor/capture.py` — one motion pass per usable video frame,
  before the timestamp overlay
- `video_monitor/web.py` — `POST /api/motion`, `GET /api/motion/events`,
  motion block on `/api/status`
- `video_monitor/server.py` — startup banner
- `video_monitor/processing.py` — mid-band moving block on the default
  synthetic pattern so a synthetic demo can produce events at the
  default sensitivity, without covering the banner or timestamp
- `templates/index.html`, `static/app.js`, `static/style.css` — toggle,
  sensitivity slider, status pills, event list
- `tests/test_motion.py` — new acceptance and HTTP tests
- `tests/test_config.py`, `tests/test_startup.py` — defaults, validation,
  and import updates
- `README.md`, `docs/architecture.md`, `docs/progress.md`,
  `docs/test-results.md`, `docs/demo-checklist.md`,
  `docs/report-outline.md`

### Commands actually executed

```bash
source .venv/bin/activate
python -m compileall -q app.py video_monitor tests
python -m pytest -v --tb=short
# 95 passed in 3.42s (before a small synthetic-pattern tweak)
# After adding a mid-band moving block to the default synthetic source:
python -m compileall -q app.py video_monitor tests
python -m pytest -v --tb=short
# 95 passed in 3.33s
python app.py --source synthetic --host 127.0.0.1 --port 53623 --server waitress --snapshot-dir <temp dir>
# HTTP checks against /, /api/status, POST /api/motion, GET /api/motion/events,
# /video_feed (finite timeout), and POST /api/snapshot. Then SIGTERM;
# the process exited and the port was free.
```

### Results

- Final pytest run: **95 passed in 3.33s**. The previous iteration 1–3
  checks still passed (the suite had 72 tests at the end of iteration 3).
- Static synthetic scene (identical pixels, 10 frames, cooldown 0):
  **zero events**.
- Deliberate-motion synthetic scene (a large moving box, default
  sensitivity 50): **at least one event** after the baseline frame.
  Measured changed-pixel percentage on that test scene was about 8.7%,
  above the default 2.12% threshold. This is a test-setup observation,
  not a camera measurement.
- Disabling detection stopped new events while frames kept moving.
  Enabling again used a fresh baseline and then recorded a new event.
- A 2.0 s cooldown with a test clock allowed one event, ignored further
  motion for 1.0 s, then recorded another event after 2.1 s.
- Injecting 8 events into a log of capacity 5 kept only the latest 5;
  `events_recorded_total` stayed 8.
- Missing-camera frames produced no motion events and did not crash.
- Manual HTTP check of `python app.py` (synthetic, Waitress, port 53623):
  after about 13 produced frames, `/api/status` showed motion enabled,
  sensitivity 50, cooldown 2.0 s, `log_count=1`,
  `events_recorded_total=1`, `currently_detected=true`,
  `last_event_at=2026-11-17 22:43:14 HKT`, and an event message
  "Motion detected (4.2% of pixels changed)". `POST /api/motion` with
  `enabled=false` (and an ignored `path` field) froze the total at 1
  while `frames_produced` continued to 25. Re-enabling with
  sensitivity 80 worked. `GET /video_feed` returned 4 decodable 640×480
  JPEGs in 0.204 s (informal localhost observation, not a measured FPS).
  `POST /api/snapshot` still saved a 640×480 JPEG.
  SIGTERM exit code -15; port 53623 was free afterwards.

### Limitations

- No webcam was used. Real lighting, auto-exposure, and camera noise
  were not tested. The detector is not promised false-positive-free.
- Synthetic lighting is not real lighting. A quiet static test scene
  does not prove zero false positives on a webcam.
- No desktop browser was opened; the toggle, slider, and event list
  were checked through the HTML/API and automated tests, not by a
  person clicking in Chrome or Firefox.
- End-to-end latency and measured FPS were not collected.
- Recording and face detection are not implemented.

### Pending manual verification

- Real webcam motion (wave a hand, walk in front of the camera) on the
  team's Windows PC, including enable/disable and sensitivity.
- Local browser confirmation of the MOTION badge, status pills, and
  event log.
- Viewing from a second computer on a trusted LAN.

### Known issues

- A real camera may not honour the configured 640×480; the status API
  still reports both sizes.
- The first `/api/status` call immediately after startup can show
  `frames_produced=0` and an empty motion log if it wins the race
  before the first compared pair.
- The default synthetic pattern now includes a mid-band moving block so
  that a camera-less demo can show events at sensitivity 50. That is
  still a synthetic source, not a webcam proof.
- Course brief typo (November 39 vs 29) is unchanged: 29 November 2026
  is treated as the report deadline.

### Next action

Keep this directory and `app.py` as the only application. Status labels
for motion are already defined in the API (do not treat
`frames_checked` as a frame rate). The next iteration should add P2
manual start/stop recording and validate that the saved file is
playable, without disturbing the stream, timestamp, snapshot, or
motion path.

## Iteration 5 — P2 manual recording

Date: 17 November 2026, 22:46–22:49 HKT (Asia/Hong_Kong).
Environment: Linux development box, Python 3.13.5, project venv at
`/workspace/remote-video-monitoring/.venv`. No webcam used. The team's
Windows PC was not used. Work stayed in the existing project directory
and the existing `app.py` entry point.

### Objective

Add manual start/stop recording that consumes the existing display-frame
path, stores files only under a controlled directory, and validates that
stopping a session produces a playable file. Do not add motion-triggered
recording or face detection.

### Files changed (in place; no app_v2 or duplicate entry point)

- `video_monitor/recording.py` — new recorder, path safety, writer probe,
  start/stop state, post-stop OpenCV validation
- `video_monitor/config.py` — `--recording-dir` with the same relative-path
  safety rule as snapshots
- `video_monitor/capture.py` — offer the processed display frame to the
  recorder; finalise a session on shutdown
- `video_monitor/web.py` — `POST /api/recording/start`,
  `POST /api/recording/stop`, recording block on `/api/status`
- `video_monitor/server.py` — startup banner
- `templates/index.html`, `static/app.js`, `static/style.css` — Start /
  Stop recording buttons and status
- `tests/test_recording.py` — new acceptance and HTTP tests
- `tests/conftest.py`, `tests/test_config.py`, `tests/test_web.py`,
  `tests/test_startup.py` — temp recording dir, defaults, UI, imports
- `README.md`, `docs/architecture.md`, `docs/progress.md`,
  `docs/test-results.md`, `docs/demo-checklist.md`,
  `docs/report-outline.md`

### Codec probe (this Linux box, OpenCV 5.0.0, ffmpeg/ffprobe present)

Tried opening `cv2.VideoWriter`, writing 30 synthetic 640×480 frames at
a 15 FPS writer rate, then opening the file with `cv2.VideoCapture` and
`ffprobe`:

- `MJPG` in `.avi` (default and FFMPEG backends): playable. ffprobe
  reported `codec_name=mjpeg`, `codec_tag_string=MJPG`, 640×480, 15 FPS,
  30 readable frames. **Selected as the preferred writer.**
- `XVID` in `.avi`: also playable (MPEG-4 Part 2). Kept as a same-
  container fallback if MJPG fails to open.
- `mp4v` in `.mp4`: also playable here (MPEG-4 Part 2), not selected,
  so the default filename/container stay AVI.
- `avc1`, `H264`, and `X264` in `.mp4`: `VideoWriter.isOpened()` was
  false (`h264_v4l2m2m` could not be configured). Not used.
- GStreamer `MJPG`: did not open. Not used.

Windows codec availability was not tested and is not claimed.

Live viewing remains MJPEG over HTTP (JPEG images). That is a different
claim from a recorded Motion JPEG AVI file, and neither is H.264 or
WebRTC.

### Commands actually executed

```bash
source .venv/bin/activate
python -m compileall -q app.py video_monitor tests
python -m pytest -v --tb=short
# After a JSON error-field ordering fix:
python -m compileall -q app.py video_monitor tests
python -m pytest -v --tb=short
# 127 passed in 10.68s
python app.py --source synthetic --host 127.0.0.1 --port 45561 \
  --server waitress --snapshot-dir <temp dir> --recording-dir <temp dir>
# HTTP checks against /, /api/status, POST /api/recording/start (with an
# ignored client path), /video_feed (finite timeout), POST /api/snapshot,
# and POST /api/recording/stop. The saved file was opened with OpenCV
# and ffprobe. Then SIGTERM; the process exited and the port was free.
```

### Results

- Final pytest run: **127 passed in 10.68s**. All iteration 1–4 tests
  remained in the suite and passed (the suite had 95 tests at the end of
  iteration 4).
- Start then stop created a server-named `.avi` under the temp directory.
  OpenCV opened the file and read frames at 640×480.
- Starting twice while already recording was rejected (HTTP 409) and did
  not open a second capture (`source_open_count` stayed 1).
- Stop when idle was a useful HTTP 409 error, not a crash.
- Client-supplied paths such as `../escape.avi` were ignored.
- A forced unavailable writer was reported as an error and did not leave
  a success file.
- Shutdown during an active recording (SIGTERM in the automated test)
  left a playable file and released the writer.
- Manual HTTP check of `python app.py` (synthetic, Waitress, port 45561):
  start at 22:49:25 HKT created `recording_20261117_224925_8db85e32.avi`.
  After a short session, stop reported `frames_written=34` and
  `validated_frames=34`. OpenCV read 34 frames at 640×480 with a reported
  15.0 FPS. ffprobe reported `codec_name=mjpeg`, `codec_tag_string=MJPG`,
  `format_name=avi`, `nb_frames=34`, duration 2.266667 s, size 1026262
  bytes. The 15 FPS figure is the configured writer/container timestamp
  rate, not a measured capture or browser rate. The live stream still
  returned 4 decodable 640×480 JPEGs in 0.212 s (informal localhost
  observation). `POST /api/snapshot` still saved a 640×480 JPEG.
  `source_open_count` stayed 1. SIGTERM exit code -15; port 45561 was
  free afterwards.

### Limitations

- No webcam was used. A real camera recording has not been checked.
- No desktop player or browser was used to play the file; validation was
  OpenCV VideoCapture and ffprobe on Linux.
- Windows Python 3.12.10 and Windows OpenCV VideoWriter availability
  were not executed.
- End-to-end latency and measured FPS were not collected.
- Motion-triggered recording and face detection are not implemented.

### Pending manual verification

- Real webcam recording on the team's Windows PC, including start/stop
  from a browser and opening the saved file in a player.
- Confirm that MJPG/AVI (or the fallback) actually opens on that Windows
  OpenCV install.
- Viewing from a second computer on a trusted LAN.

### Known issues

- A real camera may not honour the configured 640×480; the writer uses
  the actual display-frame size published in the shared buffer.
- The first start request immediately after startup can return HTTP 503
  until a frame exists (observed once in the manual HTTP check, then
  start succeeded).
- If the preferred writer cannot be opened, the server tries XVID/AVI
  or reports a clear error. It does not pretend to record.
- Course brief typo (November 39 vs 29) is unchanged: 29 November 2026
  is treated as the report deadline.

### Next action

Keep this directory and `app.py` as the only application. Recording is
solid on the Linux synthetic path. Recommended next work is UI polish
and, when the team can use the Windows PC, P0 camera / browser / LAN
verification of the existing features. Face detection (detection only,
not recognition) can stay a single stretch item after that verification;
do not add motion-triggered recording until manual recording is confirmed
on the demonstration machine.

## Iteration 6 — face detection only (not recognition)

Date: 17 November 2026, 22:54–22:57 HKT (Asia/Hong_Kong).
Environment: Linux development box, Python 3.13.5, no webcam used.
The team's Windows PC was not used.

### Objective

Add one stretch feature in the existing application (`app.py` only):
OpenCV Haar / Viola-Jones **face detection** (boxes and a count), with
enable/disable, no second camera, and no recognition, identification,
or tracking IDs. Keep iterations 1–5 working.

### Files changed (in place; no duplicate app)

- New: `video_monitor/faces.py`, `video_monitor/data/haarcascade_frontalface_default.xml`,
  `video_monitor/data/SOURCE.txt`, `tests/test_faces.py`,
  `tests/fixtures/astronaut_face.png`, `tests/fixtures/SOURCE.txt`
- Updated in place: `video_monitor/config.py`, `capture.py`, `web.py`,
  `server.py`, `templates/index.html`, `static/app.js`, `static/style.css`,
  `tests/test_config.py`, `tests/test_startup.py`, `tests/test_web.py`,
  `requirements.txt`, `README.md`, and the docs in this folder
- Entry point remains `python app.py`

### Dependency change (same OpenCV version)

OpenCV 5 removed `cv2.CascadeClassifier` from the main package (it now
lives in contrib). `opencv-python==5.0.0.93` was uninstalled in the
project venv and replaced with `opencv-contrib-python==5.0.0.93`. The
two packages cannot be installed together. Capture, JPEG, motion, and
recording APIs used by iterations 1–5 remain in this wheel. PyPI also
publishes a `cp37-abi3-win_amd64` wheel for 5.0.0.93; that is **not** a
Windows runtime test. The 5.0.0.93 wheel does not ship Haar XML files
under `cv2.data.haarcascades`, so the official cascade is bundled in
the project.

### Commands actually executed

```bash
source .venv/bin/activate
python -m pip uninstall -y opencv-python
python -m pip install "opencv-contrib-python==5.0.0.93"
# Bundled official cascade from opencv_contrib 5.x, and the public-domain
# NASA astronaut fixture from scikit-image v0.25.2 (see SOURCE.txt files).
python -m compileall -q app.py video_monitor tests
python -m pytest -v --tb=short
# 146 passed in 12.21s
python app.py --source synthetic --host 127.0.0.1 --port 43489 \
  --server waitress --snapshot-dir <temp dir> --recording-dir <temp dir>
# HTTP checks against /, /api/status, /video_feed (finite timeout),
# POST /api/faces (disable/enable, ignored client path), and
# POST /api/snapshot. Then SIGTERM; the process exited and the port
# was free.
```

### Results

- Final pytest run: **146 passed in 12.21s**. The suite had 127 tests
  at the end of iteration 5; all of those remaining tests still passed.
- The bundled official cascade loads and is not empty.
- The documented NASA / scikit-image astronaut fixture produced at
  least one Haar detection at the default scale of 0.5. The same
  fixture produced zero detections when the detector was disabled.
- The plain synthetic pattern (12 frames) and the static synthetic
  motion-test scene produced zero detections.
- Enable/disable via `POST /api/faces` works; client-supplied paths
  are ignored. Disabling clears held boxes.
- Two HTTP stream clients still share one capture owner while
  detection is enabled (`capture_start_count` and `source_open_count`
  stayed 1). The synthetic stream reported `detected_count=0`, which
  matches the no-face pattern.
- Manual HTTP check of `python app.py` (synthetic, Waitress, port
  43489): `/` returned 200 and included the face-detection controls.
  `/api/status` reported faces enabled, `mode=detection`,
  `recognition=false`, `cascade_source=bundled`,
  `detect_every_n_frames=2`, `detect_scale=0.5`, `detected_count=0`.
  `/video_feed` returned 4 decodable 640×480 JPEGs in 0.219 s
  (informal localhost observation, not a measured capture or browser
  FPS). `POST /api/snapshot` still saved a 640×480 JPEG. SIGTERM exit
  code -15; port 43489 was free afterwards; no leftover process.

An informal still-image microbenchmark on this Linux box was used only
to choose the default trade-off: about 18 ms for Haar on a 640×480
copy of the fixture at scale 1.0, and about 6 ms at scale 0.5. Those
figures are **not** a camera FPS, stream FPS, or browser FPS.

### Limitations

- No webcam was used. Real faces, lighting, and pose have not been
  checked.
- No desktop browser was opened.
- Windows Python 3.12.10 was not executed.
- End-to-end latency and measured FPS were not collected.
- This feature must not be described as face recognition.

### Pending manual verification

- Real webcam face boxes and count on the team's Windows PC, including
  enable/disable from a browser.
- Confirm that overlays stay readable with the timestamp and MOTION
  badge, and that snapshots/recordings include boxes when expected.
- Viewing from a second computer on a trusted LAN.

### Known issues

- Haar works best on roughly frontal, well-lit faces and can miss
  profile or occluded faces, or report false positives.
- When detection runs every Nth frame, boxes may lag by up to N-1
  frames (documented trade-off).
- A real camera may not honour the configured 640×480.
- Course brief typo (November 39 vs 29) is unchanged: 29 November 2026
  is treated as the report deadline.

### Next action

Stop adding features. The UI is consistent enough for rehearsal. The
team should spend remaining time on Windows camera, browser, and
trusted-LAN checks, report evidence, and a short demonstration
rehearsal against `docs/demo-checklist.md`. Do not add
motion-triggered recording or any recognition / identification.


## Iteration 7 — monitoring page redesign (in place)

Date: 17 November 2026, 23:15–23:21 HKT (Asia/Hong_Kong).
Environment: Linux development box, Python 3.13, no webcam and no
desktop browser used. The team's Windows PC was not used.

### Objective

Redesign the existing monitoring page in `/workspace/remote-video-monitoring`
in place, following the Polished UI Skills and UI/UX Kit agent skills
already downloaded on this machine. Keep Python / Flask / vanilla
HTML+CSS+JS, `python app.py`, and existing element IDs / API behaviour.
Fix the on-frame `Faces: N` vs `SYNTHETIC SOURCE` overlay collision and
the missing `/favicon.ico`.

### Files changed (same project; no second app)

- `templates/index.html`, `static/style.css` — control-room layout,
  tokens, skip link, clustered status, quieter footer
- `static/favicon.svg`, `static/favicon.ico` — local mark
- `video_monitor/web.py` — `GET /favicon.ico`
- `video_monitor/processing.py` — detect the synthetic banner height
- `video_monitor/faces.py` — draw `Faces: N` immediately below that
  banner when it is present
- `video_monitor/capture.py` — comment only (draw order unchanged)
- `tests/test_faces.py`, `tests/test_web.py` — overlay position and
  favicon tests
- `DESIGN_SYSTEM.md` — surface profile, concept, tokens, states,
  anti-slop notes, and skill attribution
- `docs/progress.md` — this note

`static/app.js` was not rewritten. Product behaviour was not extended
(no motion-triggered recording, no recognition, no new pages).

### Commands actually executed

```bash
python -m compileall -q app.py video_monitor tests
python -m pytest --tb=no
# 148 passed in 12.40s
```

No browser was opened, so layout at 1440px and 390px was not visually
confirmed.

### Results

- Final pytest run: **148 passed in 12.40s**. The suite had 146 tests
  at the end of iteration 6; two tests were added (face-badge placement
  under the synthetic banner, and `/favicon.ico`).
- The monitoring page was redesigned in place as a camera control room:
  the live feed is the main stage, live state and actions sit in a side
  rail (stacked under the video on narrower widths), remaining metrics
  are grouped into Stream and Activity clusters, and the long technical
  footer is inside a `<details>` disclosure. Honest disclaimers were
  kept.
- On synthetic frames, `Faces: N` is drawn immediately below the red
  top banner so the two labels do not overlap. MOTION stays top-right
  and the timestamp stays bottom-right. Detection logic was not
  changed.
- `/favicon.ico` returns the local icon (HTTP 200 in the new test).
  The page also links `static/favicon.svg`.

### Limitations

- No desktop browser was opened. Visual review at ~1440px and ~390px,
  focus rings, reduced-motion, and touch-target checks are pending.
- No webcam was used.
- Windows was not executed.

### Next action

Visually review the redesigned page in a browser at desktop and phone
widths, then continue Windows camera, trusted-LAN, and demonstration
rehearsal work. Do not add motion-triggered recording or any
recognition / identification.
