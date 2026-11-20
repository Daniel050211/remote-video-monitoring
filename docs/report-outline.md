# Report outline (skeleton)

Aligned with the official EIE4428 mini-project report template. This is a
planning aid, not the report itself. Do not invent measurements,
screenshots, citations, or individual contributions.

## Cover sheet

- Group members and student IDs: *to be filled by the team*

## Summary of the Project

- Short description of a browser-based remote video monitoring system.
- Development platform: **Python, Flask, OpenCV, Waitress** (not WebRTC).
- Current slice: MJPEG over HTTP, JPEG compression, timestamp overlay
  (Asia/Hong_Kong, HKT, UTC+8), local JPEG snapshots, grayscale frame-
  difference motion detection, Haar face detection (not recognition),
  manual Motion JPEG / AVI recording, video only.

## Functionalities of the System (planned table)

| Item | Planned / current value | Status |
|------|-------------------------|--------|
| Basic Remote Monitoring Function | Video only (no audio) | In progress |
| Achieved Video Frame Rate | Configured target 15 FPS; measured rates not yet recorded | Not measured |
| Video Format | Live view: MJPEG over HTTP, JPEG images. Recording (Linux-verified): Motion JPEG (MJPG) in an AVI container. Neither is H.264, H.265, or WebRTC. Windows recording codec is unverified. | Implemented, synthetic-tested (live + recording on Linux) |
| Video Resolution | Configured 640×480 | Implemented, synthetic-tested |
| Audio Format | None (out of scope initially) | N/A |
| Concurrent Access to the Server | Target: 2 viewers, one shared capture | Automated on Linux (synthetic); LAN not verified |
| Assessment via Internet | No initially (trusted LAN only later) | Not started |

## Special Features of the System

- Timestamp overlay (iteration 2): current time in Asia/Hong_Kong
  (`YYYY-MM-DD HH:MM:SS HKT`) drawn once before JPEG encoding. Automatically
  verified on synthetic/error frames; not yet verified on a real webcam or
  in a browser.
- Snapshots (iteration 3): Save snapshot writes the current shared display
  JPEG under `data/snapshots/` with a server-generated name. Automatically
  verified (path safety, decode, concurrent writes, HTTP); not yet verified
  from a browser or a real webcam. Snapshot files are not committed.
- Motion detection (iteration 4): enable/disable, sensitivity 1–100,
  2.0 s event cooldown, MOTION badge, bounded log of 50 events.
  Automatically verified on synthetic static and deliberate-motion
  scenes; not yet verified on a real webcam or in a browser. Not
  promised false-positive-free.
- Manual recording (iteration 5): start/stop writes the same display
  frames to `data/recordings/` as Motion JPEG (MJPG) in an AVI
  container (verified on Linux; Windows codec unverified). Automatically
  verified with OpenCV read-back and ffprobe; not yet verified on a
  real webcam or in a browser.
- Face detection (iteration 6): OpenCV Haar / Viola-Jones cascade,
  enable/disable, boxes and count on the current processed frame.
  This is detection only, not recognition or identification.
  Automatically verified with a documented public-domain NASA
  fixture; not yet verified on a real webcam or in a browser.
  Limits (frontal faces, lighting, pose, false positives) must be
  stated in the report. Motion-triggered recording is not implemented.

## Details of the Project

Use `docs/architecture.md` for the block diagram and for highlighting
custom code versus libraries.

## Implementation Details

Record commands, versions, and test evidence from `docs/progress.md` and
`docs/test-results.md` as work proceeds. Do not copy unverified numbers
into the final report.

## Design of User Interface

Simple monitoring page: live image, connection/source status, configured
resolution and FPS, visible synthetic-source banner, error messages.
English UI text. Candidate screenshots (to capture later on Windows):

- Local live view with a real camera
- Synthetic-source banner
- Missing-camera error
- Snapshot saved from the monitoring page (filename shown; file on disk)
- Motion detection on and off, sensitivity control, MOTION badge, event log
- Manual recording start/stop, status, and a playable saved file
- Face detection on and off, boxes and count (do not present this as recognition)
- Second-PC LAN view

## Co-operation between Group Members

**Proposed** division of work (not yet confirmed, and not a record of
actual contributions):

- Member A: capture, backend, later motion detection and recording
- Member B: frontend, integration testing, evaluation, documentation

Both members should understand the end-to-end system. Actual contributions
will be written only after the team confirms them.

## Conclusions and References

To be written later. References already consulted are listed in
`docs/references/` (course brief and report template) plus library
documentation used during implementation (Flask, OpenCV, Waitress, pytest).
Do not invent citations.
