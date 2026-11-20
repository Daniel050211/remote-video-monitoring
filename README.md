# Remote Video Monitoring

EIE4428 Multimedia Communications mini-project (2026/27).

This repository is the working application for the course mini-project.
A single capture owner produces JPEG frames. Motion detection, Haar
face *detection* (not recognition), and a timestamp are applied once in
the processing path, and a simple web page displays the result as an
**MJPEG stream over HTTP**. The same shared display frame can be saved
as a JPEG snapshot, or recorded to a file under a server-controlled
folder. It is not a finished demonstration system. Real-webcam viewing
and remote-PC LAN viewing have **not** been verified yet.

The live stream is **MJPEG over HTTP** (`multipart/x-mixed-replace`
carrying JPEG images). It is **not** H.264, H.265, or WebRTC.
Manual recordings, when the writer starts successfully, are **Motion
JPEG (MJPG) in an AVI container**. That is a saved file, not the live
HTTP transport, and also not H.264 or WebRTC.

## What this slice does

- Starts with one command: `python app.py`
- Captures from a webcam when available, or from a clearly labelled
  **synthetic test source**
- Overlays the current time in **Asia/Hong_Kong (HKT, UTC+8)** on each
  frame once, before JPEG encoding, so every viewer sees the same stamp
  (format: `2026-11-17 22:28:05 HKT`; disable with `--no-timestamp`)
- Compresses each frame as JPEG
- Serves a monitoring page at `http://127.0.0.1:5000/`
- Lets more than one browser tab share the **same** capture (no new camera
  per viewer)
- Reports camera/server errors in the page and at `/api/status` without
  crashing the process
- Releases the capture thread and camera on shutdown
- Saves a JPEG snapshot of the current display frame (already timestamped
  if the overlay is on) when the user clicks **Save snapshot**. The file
  is written only under `data/snapshots/` (gitignored). The filename is
  generated on the server; the browser cannot choose a path.
- Detects motion once on the capture thread using grayscale frame
  differencing. The page can enable or disable detection, change
  sensitivity, show a MOTION mark, and list a bounded event log.
- Manually starts and stops a recording of the same display frames
  (timestamp, MOTION badge, and face boxes may appear in the file). The
  file is written only under `data/recordings/` (gitignored) with a
  server-generated name. The browser cannot choose a path.
- Detects roughly frontal faces **once** on the capture thread using an
  OpenCV Haar cascade (classical Viola-Jones). This is **detection
  only**, not recognition or identification: the page can enable or
  disable it, and the stream shows boxes plus a count. The system does
  not name or track people.

Default configuration (these are **configured** values, not measured rates):

- Bind: `127.0.0.1:5000` (this computer only)
- Resolution: 640×480
- Capture-loop target: 15 FPS
- JPEG quality: 80
- Source: `auto` (try the camera, then fall back to synthetic)
- Timestamp overlay: on, Asia/Hong_Kong (HKT, UTC+8)
- Snapshots: `data/snapshots/` inside the project (not committed)
- Recordings: `data/recordings/` inside the project (not committed);
  preferred writer is MJPG in AVI; writer FPS is the configured
  container timestamp rate (15), not a measured capture rate
- Motion detection: on, sensitivity 50 (1=least, 100=most), cooldown 2.0 s,
  event log bound 50 (oldest events dropped)
- Face detection: on (detection only, not recognition), official
  `haarcascade_frontalface_default.xml`, every 2nd frame, scale 0.5
  (configured trade-off, not a measured FPS)

## Requirements

- Python 3.12 or 3.13 (the course machines are expected to use Windows
  Python 3.12.10; this slice was executed on Linux Python 3.13.5)
- A webcam is required later for the course demonstration. It is **not**
  required to start the application or to run the automated tests.

Dependencies are listed in `requirements.txt`. Versions were installed and
imported on Linux Python 3.13.5. PyPI also publishes Windows/Python 3.12
wheels (or `abi3` / `py3-none-any` wheels) for the pinned direct
dependencies. That is **not** a guarantee that a Windows runtime test has
already passed.

## Setup and launch

Always work inside the project directory and use the project virtual
environment. There is **one** entry point: `app.py`.

### Windows PowerShell

```powershell
cd path\to\remote-video-monitoring
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution for the venv, run this once in the
current window, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Then open [http://127.0.0.1:5000/](http://127.0.0.1:5000/) in Chrome or Firefox.

Useful variants:

```powershell
python app.py --source synthetic
python app.py --source camera
python app.py --help
```

### Linux (commands actually used on the development box)

```bash
cd /workspace/remote-video-monitoring
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py --source synthetic
```

Then open `http://127.0.0.1:5000/`.

Run the automated tests (from the project directory, with the venv active):

```bash
python -m pytest
```

On Windows PowerShell, after activation:

```powershell
python -m pytest
```

Stop the server with Ctrl+C.

## Trusted-LAN demonstration (later)

By default the server is **not** reachable from other computers. For a later
demo on a trusted local network only:

```powershell
python app.py --host 0.0.0.0 --source camera
```

On the server PC, Windows may show a firewall prompt. This project does not
change firewall rules for you. If you allow access, open

`http://<server-lan-ip>:5000/`

from a second computer on the same trusted LAN.

This mode is **not** a production-secure surveillance system. Do not expose
the server to the public Internet, and do not forward the port through a
router or cloud firewall.

## Snapshots

Click **Save snapshot** on the monitoring page, or send `POST /api/snapshot`.
The request does not accept a filesystem path or filename from the client.
The server copies the current shared display JPEG (the same bytes that
viewers are seeing, including the timestamp overlay when it is enabled)
into `data/snapshots/` under the project directory.

- Filenames look like `snapshot_YYYYMMDD_HHMMSS_<8-hex>.jpg` and use
  Asia/Hong_Kong time plus a unique suffix.
- The JSON response returns the generated filename, not a full server
  path, together with `ok` or an error message.
- If no frame is available yet, the server returns HTTP 503 and a useful
  error; the process does not crash.
- `GET /api/snapshot/latest` returns the last snapshot saved in this
  process (a fixed server-controlled path). It does not take a
  client-supplied file path.
- These image files are listed in `.gitignore` and must not be committed.
  They may contain camera pictures.

Operators can point the store at another directory with `--snapshot-dir`
(for tests or a custom location). Relative values must stay inside the
project. Clients still cannot choose the path.

## Manual recording

Click **Start recording** and later **Stop recording** on the monitoring
page, or send `POST /api/recording/start` and `POST /api/recording/stop`.
The request does not accept a filesystem path or filename from the client.
The recorder consumes the same display frames already prepared for
viewers, so face boxes may appear in the file when detection is on.
It does not open a second camera.

- On the Linux development box, the writer that was actually verified
  is **Motion JPEG (OpenCV fourcc MJPG)** inside an **AVI** container.
  `XVID` in AVI also produced a playable file in the same probe and is
  kept as a fallback if MJPG cannot be opened. H.264 (`avc1` / `H264`
  / `X264`) did **not** open here.
- The writer FPS is the **configured container timestamp rate**
  (default 15). That is not a measured capture rate or browser rate.
- Filenames look like `recording_YYYYMMDD_HHMMSS_<8-hex>.avi` and use
  Asia/Hong_Kong time plus a unique suffix.
- The JSON response returns the generated basename, recording state
  (`idle` / `recording` / `error`), start time, elapsed time while
  recording, and an error message when something fails.
- Stopping a recording releases the writer and then opens the file to
  confirm it contains frames at the expected size. A truncated or
  unreadable file is reported as an error, not as success.
- If no frame is available yet, start returns HTTP 503. Starting twice,
  or stopping when idle, returns HTTP 409 with a useful message.
- These video files are listed in `.gitignore` and must not be committed.
  They may contain camera pictures.
- **Windows codec availability has not been verified.** The same MJPG/AVI
  choice is often available in OpenCV on Windows, but that is not a
  runtime result from the students' PC.

Operators can point the store at another directory with `--recording-dir`.
Relative values must stay inside the project. Clients still cannot choose
the path.

## Motion detection

Motion is evaluated **once** on the capture/processing thread, on the
raw frame, **before** the timestamp overlay and JPEG encoding. Viewers
never run their own detector and never open a second camera.

Algorithm (student-explainable grayscale frame differencing, not a
trained model):

1. Convert the current and previous frames to grayscale.
2. Apply a 5×5 Gaussian blur to reduce small noise.
3. Take the absolute difference between those two images.
4. A pixel is “changed” if the difference is greater than a pixel
   threshold derived from sensitivity (25 gray levels at the default
   of 50).
5. If the percentage of changed pixels is at least
   `min_changed_percent` (about 2.12% at sensitivity 50), the frame is
   treated as containing motion.
6. The first usable frame after enable, or after a size change, is only
   a baseline: it is stored and no event is recorded.
7. A **cooldown of 2.0 seconds** (default, configured, not measured)
   limits how often a new event is appended. The on-screen MOTION badge
   follows the current frame comparison and is not delayed by the
   cooldown.

Sensitivity is an integer from 1 (least sensitive) to 100 (most
sensitive). Higher values treat smaller changes as motion. It is a
configuration knob, not a measured accuracy figure.

The event log keeps at most **50** entries (oldest dropped). It is shown
on the monitoring page and at `/api/status` and `GET /api/motion/events`.
`POST /api/motion` can change `enabled` and `sensitivity`. Unknown JSON
keys such as a file path are ignored.

Turning detection off stops new events, clears the current-detection
flag and the previous-frame baseline, and clears the cooldown. Existing
log entries are kept. Turning it back on uses the next frame as a fresh
baseline, after which a moving scene can be logged immediately.

This is **not** promised false-positive-free. Lighting changes, camera
noise, and auto-exposure can look like motion. Synthetic lighting is
not real lighting. Useful command-line flags: `--no-motion`,
`--motion-sensitivity`, `--motion-cooldown`, `--motion-log-size`.

Status fields are defined in the API (and must not be read as frame
rates): `frames_checked` is a count of valid frames submitted to the
detector while it was enabled; `currently_detected` is the latest
comparison result, not a duration; `events_recorded_total` includes
events later dropped from the bounded log.

## Face detection (not recognition)

Face detection runs **once** on the capture/processing thread, on the
raw frame, **before** badges and the timestamp are drawn. Viewers never
run their own detector and never open a second camera.

This is **detection only**. The detector draws rectangles and reports
how many faces are on the **current processed display frame**. It does
not identify a person, does not assign tracking IDs, and does not
match biometric templates.

Algorithm (student-explainable classical computer vision, not a custom
trained model):

1. Optionally shrink a copy of the raw frame (`--face-detect-scale`,
   default 0.5).
2. Convert that copy to grayscale.
3. Run OpenCV's `CascadeClassifier` with the official
   `haarcascade_frontalface_default.xml` (Viola-Jones Haar cascade).
4. Scale the boxes back to the original frame size.
5. Draw green boxes and a `Faces: N` badge on the shared display frame.

Draw order on that shared frame: face boxes and count (top-left), then
the MOTION badge (top-right), then the timestamp (bottom-right). The
later overlays stay readable if a box overlaps those corners.
Snapshots and recordings use the same display frame, so boxes may
appear in saved files.

Performance: detection runs on the downscaled copy and only every Nth
frame (default every 2). Boxes from the last detection are reused on
skipped frames. These values are a **configured trade-off** so the
live stream stays responsive; they are not a measured camera or
browser FPS.

The cascade XML is bundled under `video_monitor/data/` (official OpenCV
5 / `opencv_contrib` file, Intel/OpenCV BSD-style license retained in
the XML header). The loader uses that copy first. OpenCV 5 moved
`cv2.CascadeClassifier` into the contrib package, so
`requirements.txt` pins `opencv-contrib-python` (not `opencv-python`;
the two cannot be installed together) at the same 5.0.0.93 version
already used for capture and JPEG encoding. The 5.0.0.93 wheel does
not ship the XML under `cv2.data.haarcascades`.

Limits: this works best on roughly frontal, well-lit faces. Pose,
occlusion, glasses, scale, and lighting can cause missed detections or
false positives. A count of zero does not prove that no person is
present. The default synthetic test pattern does not contain a face
and is not expected to produce detections.

`POST /api/faces` can change `enabled`. Unknown JSON keys such as a
file path are ignored. Useful flags: `--no-faces`,
`--face-detect-every`, `--face-detect-scale`.

## Security baseline

- Debug mode and the Flask reloader are off (the reloader can open the
  camera twice).
- Default bind is localhost only.
- Configuration comes from the command line, not from client-supplied
  filesystem paths.
- Snapshots are written only under a server-controlled directory with a
  server-generated name. Path traversal, absolute paths, and
  client-supplied names are ignored or rejected. Recordings use the
  same rule under `data/recordings/` with a server-generated name.

## Project layout

- `app.py` — the only launch entry point
- `video_monitor/` — configuration, capture, shared frame buffer, JPEG
  processing, motion detection, face detection, snapshot storage,
  recording, Flask routes, and server startup
- `video_monitor/data/haarcascade_frontalface_default.xml` — bundled
  official OpenCV Haar cascade (detection only)
- `templates/index.html`, `static/` — monitoring page
- `tests/` — automated tests (synthetic source and HTTP)
- `docs/` — short architecture, progress, test results, demo and report notes

## What is and is not verified

See `docs/test-results.md` for the evidence from this iteration.

Automatically tested on the Linux development box with the synthetic source:

- JPEG encoding
- Timestamp overlay format, drawing, and shared encode path
- Capture loop and clean shutdown
- Missing-camera error path (no crash; error frames remain servable)
- Monitoring page and status API
- MJPEG stream with a finite read timeout
- Two concurrent clients sharing one capture instance
- Startup of the real `app.py` entry point
- Snapshot save to a temporary directory, path-safety checks, and JPEG
  decode of the saved file
- Motion detection on static vs deliberate-motion synthetic scenes,
  cooldown, bounded log, enable/disable, and HTTP control of the same
  `app.py` entry point
- Manual start/stop recording to a temporary directory, path-safety
  checks, playable-file validation (OpenCV read-back), failed-writer
  handling, and shutdown while a recording is active
- Face detection (Haar / Viola-Jones) on a documented public-domain
  NASA test photograph, enable/disable, no detections on the plain
  synthetic pattern, and HTTP control of the same `app.py` entry point

**Not verified:** real webcam capture, local browser display of a real
camera, and viewing from a second PC on a LAN. Synthetic-source results do
not prove those items.

## HTTP server

The default WSGI server is **Waitress** (Windows-compatible, `threads=8`).
If Waitress were to buffer or break the long-lived MJPEG response, the same
`app.py` can be started with `--server werkzeug` (threaded, reloader off).
The choice used after verification is recorded in `docs/test-results.md`.
