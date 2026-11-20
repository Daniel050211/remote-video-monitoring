# Architecture (iterations 1–6)

This slice implements one data path:

```
Camera (OpenCV VideoCapture)  or  Synthetic test pattern
                |
                v
     CaptureService  (single owner thread)
                |
                v
     Motion + face analysis  (once each, on the raw frame)
       Face boxes + Faces: N badge (top-left), if enabled
       optional MOTION badge (top-right)
                |
                v
     Timestamp overlay  (once, bottom-right, Asia/Hong_Kong / HKT, UTC+8)
                |
                v
     JPEG compression  (OpenCV cv2.imencode)
                |
                v
     FrameBuffer  (one latest JPEG, lock + condition)
                |
       +--------+--------+------------------+
       |                 |                  |
  Viewer 1          Viewer 2         POST /api/snapshot
  HTTP MJPEG        HTTP MJPEG       SnapshotStore
  multipart/x-mixed-replace          (data/snapshots/)
       |                 |                  |
       v                 v                  v
  Browser <img>     Browser <img>    JPEG file (server-named)

The same display BGR frame (after face boxes, motion badge, and
timestamp) is also offered to RecordingManager when a manual session
is active. The recorder writes those frames with OpenCV VideoWriter.
It does not open a second camera and does not read a client-supplied
path. Snapshots also copy that already-drawn JPEG, so face boxes may
appear in saved images and recordings.

     Display BGR frame  --(if recording)-->  VideoWriter
                                            MJPG in AVI
                                            data/recordings/
```

Motion detection and face detection both run only on the capture
thread, on the raw frame, before badges and the timestamp are drawn.
That stops the changing clock text from looking like motion, and
stops Haar from seeing the overlays as part of the scene. Viewers
read the already-processed JPEG; they do not run a second detector.

## Design choices

- **One capture owner.** `CaptureService` is started once when `app.py`
  starts. HTTP clients never open a new `VideoCapture`.
- **Shared latest frame, not a queue.** Slow viewers skip frames. Memory
  does not grow with a backlog of unread frames.
- **Explicit synchronization.** The buffer uses a `threading.Lock` and a
  `Condition` so the capture thread can publish a new JPEG and viewers can
  wait for it.
- **Separated modules.** Configuration, capture, JPEG processing, web
  routes, and the WSGI server are separate files. `app.py` only parses
  arguments and starts the server.
- **Timestamp overlay (iteration 2).** `prepare_display_frame()` in
  `video_monitor/processing.py` draws the current Asia/Hong_Kong time
  (`YYYY-MM-DD HH:MM:SS HKT`) once on the capture thread, before JPEG
  encoding. Viewers read the already-stamped JPEG from the shared
  buffer; the overlay is not drawn separately per client. The clock
  uses the standard-library `zoneinfo` timezone `Asia/Hong_Kong`
  (HKT, UTC+8, no daylight-saving time). A dark box and a dark outline
  keep the white text readable on light and dark scenes. The overlay
  is on by default and can be disabled with `--no-timestamp`.
- **Snapshots (iteration 3).** `video_monitor/snapshots.py` writes the
  current shared display JPEG under a server-controlled directory
  (default `data/snapshots/`). The HTTP route is thin: `POST /api/snapshot`
  never reads a path or filename from the client. The store generates a
  unique `snapshot_YYYYMMDD_HHMMSS_<8-hex>.jpg` name, writes to a
  temporary file, then `os.replace`s it into place under a lock so
  concurrent requests cannot tear a file or share a name. The JSON
  response returns only the generated basename. `GET /api/snapshot/latest`
  serves the last file from a fixed server-controlled path. Allowlisted
  filename helpers reject traversal, absolute paths, and other unsafe
  names. Snapshots do not open a second camera.
- **Motion detection (iteration 4).** `video_monitor/motion.py` owns the
  detector, the cooldown, and the bounded event log. The capture loop
  calls it once per usable video frame and then, if motion is currently
  detected, draws a MOTION badge at the top-right. Message / missing-
  camera frames are not analysed and do not invent events. Runtime
  enable/disable and sensitivity changes go through `POST /api/motion`;
  the log is also at `GET /api/motion/events`. Defaults: enabled, 
  sensitivity 50, cooldown 2.0 s, log bound 50. Disabling stops new
  events, clears the baseline and cooldown, and keeps existing log
  entries. This method is not promised false-positive-free; lighting
  changes can look like motion, and synthetic lighting is not real
  lighting.
- **Synthetic source.** Automated tests and camera-less development use a
  generated pattern with a visible `SYNTHETIC SOURCE` banner. Those results
  do not prove that a real camera or a LAN demo works.
- **Missing camera.** If `--source camera` and the device cannot be opened,
  the process stays up, `/api/status` returns a useful error, and the stream
  shows an information frame.
- **Manual recording (iteration 5).** `video_monitor/recording.py`
  owns start/stop, a server-controlled directory (default
  `data/recordings/`), unique `recording_YYYYMMDD_HHMMSS_<8-hex>.avi`
  names, writer probing, and post-stop file validation. The capture
  loop offers the already-processed display frame to the recorder; a
  second camera is never opened. Start/stop go through
  `POST /api/recording/start` and `POST /api/recording/stop`. Client
  path or filename fields are ignored. On this Linux box the writer
  that was actually verified is Motion JPEG (OpenCV fourcc `MJPG`)
  in an AVI container. `XVID` in AVI was a playable fallback in the
  same probe; H.264 / `avc1` did not open. Windows codec availability
  is unverified. The writer FPS is the configured container timestamp
  rate (default 15), not a measured capture rate. Timestamp and
  MOTION overlays already burned into the display frame may appear
  in the file. Shutdown finalises an active recording (or records a
  clear error) and releases the writer.
- **Face detection (iteration 6).** `video_monitor/faces.py` owns the
  Haar / Viola-Jones detector. This is **detection only**, not
  recognition or identification: it reports bounding boxes and a
  count on the current processed display frame. It does not name
  people, assign tracking IDs, or match biometric templates. The
  official `haarcascade_frontalface_default.xml` is bundled under
  `video_monitor/data/` and loaded first (a fallback to
  `cv2.data.haarcascades` exists if the file is missing). OpenCV 5
  moved `cv2.CascadeClassifier` into contrib, so the project depends
  on `opencv-contrib-python==5.0.0.93` rather than `opencv-python`.
  Detection runs on a downscaled grayscale copy (default scale 0.5)
  and every Nth frame (default 2); held boxes are reused on skipped
  frames. Those values are a configured trade-off, not a measured
  FPS. Draw order on the shared frame: face boxes + `Faces: N`
  (top-left), MOTION badge (top-right), timestamp (bottom-right).
  Runtime enable/disable goes through `POST /api/faces`. Disabling
  clears held boxes so the next frame has no rectangles. Defaults:
  enabled. Limits: best on roughly frontal, well-lit faces; pose,
  occlusion, and lighting can cause misses or false positives. The
  default synthetic pattern is not expected to produce detections.
- **Shutdown.** Stop sets an event, joins the capture thread with a
  timeout, releases `VideoCapture`, and finalises an in-progress
  recording if one is active.

## Transport and compression (do not confuse these)

| Stage        | What this slice uses                                      |
|--------------|-----------------------------------------------------------|
| Capture      | OpenCV `VideoCapture` or a generated BGR image            |
| Processing   | Motion check (grayscale frame difference) and Haar face detection (once each on the raw frame), then face boxes, MOTION badge, and timestamp overlay, all before encode (HKT, UTC+8). Face detection is not recognition. |
| Compression  | JPEG (`cv2.imencode`, quality 1–100)                      |
| Transport    | HTTP `multipart/x-mixed-replace` (MJPEG)                  |
| Browser      | `<img src="/video_feed">` displays the JPEG parts         |
| Snapshot     | Same display JPEG written under `data/snapshots/`         |
| Recording    | Motion JPEG (MJPG) in an AVI container (verified on this Linux box). This is a saved file, not the live HTTP stream, and not H.264 or WebRTC. Windows codec support is unverified. Writer FPS is the configured container timestamp rate. |

Live MJPEG here is a sequence of JPEG images over HTTP. It is not H.264,
H.265, or WebRTC. A recorded `.avi` file that happens to use Motion JPEG
is still a file container, not the live HTTP transport.

Configured FPS is the capture-loop target. It is not a measured capture
rate and not a browser display rate. End-to-end latency has not been
measured.

## Libraries versus custom code

| Piece | Source |
|-------|--------|
| Webcam open, frame read, JPEG encode/decode, grayscale/blur/diff, Haar cascade classification, drawing text/boxes on test, error, timestamp, motion, and face frames | OpenCV (`opencv-contrib-python`; required in OpenCV 5 for `cv2.CascadeClassifier`) |
| Timezone for the timestamp overlay | Python standard library `zoneinfo` (`Asia/Hong_Kong`) |
| HTTP routes, HTML template, static files | Flask |
| WSGI HTTP server (default) | Waitress |
| Fallback WSGI server | Werkzeug (`app.run`, threaded, reloader off) |
| Automated tests | pytest |
| Snapshot path checks, unique names, and atomic file writes | Custom code in `video_monitor/snapshots.py` |
| Motion thresholds, cooldown, bounded event log, and enable/disable state | Custom code in `video_monitor/motion.py` |
| Official frontal-face Haar cascade XML (Viola-Jones model data) | Bundled OpenCV / Intel cascade in `video_monitor/data/` (not trained by this project) |
| Face-detection enable/disable, downscale / every-Nth-frame schedule, box scaling, and status definitions | Custom code in `video_monitor/faces.py` |
| VideoWriter open, frame write, and file open/read-back | OpenCV (`cv2.VideoWriter` / `cv2.VideoCapture`) |
| Recording path checks, unique names, start/stop state, codec probe, and post-stop validation | Custom code in `video_monitor/recording.py` |
| Capture thread, latest-frame buffer, MJPEG packaging, configuration, monitoring UI | Custom code in this project |

## Default bind and LAN use

`127.0.0.1` is the default. `--host 0.0.0.0` is for a later trusted-LAN
demo only and prints a warning. That mode is not production-secure.
