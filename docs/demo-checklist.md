# Demonstration checklist

Plan against the earliest demonstration date: **25 November 2026**.
Demonstration window: 25–28 November 2026. Report deadline on the brief's
Assessment page: **29 November 2026 (Sunday)**. Page 1 of the brief has a
typographical error ("November 39, 2026"); 29 November 2026 is the Sunday
and is treated as the intended date.

This list will be ticked only with real evidence. Synthetic tests do not
tick camera or LAN items.

## P0 — required for a satisfactory demo

- [ ] Application starts on the demonstration Windows PC with `python app.py`
- [ ] Real webcam produces frames
- [ ] Local browser on the server PC shows the live stream
- [ ] A second computer on the trusted LAN shows the live stream
- [ ] UI is simple and usable (source, configured resolution and FPS, errors)
- [ ] Missing or busy camera shows an error and does not crash
- [ ] Shutdown with Ctrl+C releases the camera
- [ ] Two viewing clients do not open two cameras
      (automated on Linux with a synthetic source; still needs a Windows check)

## P1 — after P0 is stable

- [ ] Timestamp overlay (implemented in iteration 2; automatically
      verified on synthetic and missing-camera frames; not yet visually
      verified on a real webcam or in a browser)
- [ ] Snapshot to a safe local folder (implemented in iteration 3;
      automatically verified with a synthetic frame and a temp
      directory; not yet verified from a browser or a real webcam)
- [ ] Motion detection with enable/disable, sensitivity, visual indicator, cooldown
      (implemented in iteration 4; automatically verified on synthetic
      static and deliberate-motion scenes; not yet verified on a real
      webcam, in a browser, or with real lighting)
- [ ] Bounded motion-event log (implemented in iteration 4;
      automatically verified; not yet verified in a browser)
- [ ] Status metrics with clearly labelled definitions
      (configured FPS, frames_checked, and event counts are defined
      in the API; do not read them as browser FPS. No measured rates yet.)

## P2 / stretch — only after P1 regression tests pass

- [ ] Manual start/stop recording and a playable saved file
      (implemented in iteration 5; automatically verified on the
      Linux box with a synthetic source and MJPG/AVI; not yet
      verified on a real webcam, in a desktop browser, or on Windows)
- [ ] Face detection only (not recognition): enable/disable, boxes, count
      (implemented in iteration 6; automatically verified with a
      documented public-domain NASA fixture and with the synthetic
      pattern producing zero detections; not yet verified on a real
      webcam, in a browser, or with real lighting/pose)
- [ ] UI polish (current page is consistent enough for rehearsal;
      do not add more features before Windows camera / LAN checks)
- [ ] Motion-triggered recording is **not** implemented and should
      stay out of scope unless the core demo is already solid

## Measurement notes (when numbers are recorded)

- Distinguish configured FPS from measured capture FPS.
- Do not label server capture FPS as browser FPS.
- Do not infer end-to-end latency from capture time alone.
- Record resolution, JPEG quality, client count, hardware, and network
  conditions. Mark latency as not measured until an external-clock method
  is used.

## Suggested rehearsal order on the demonstration Windows PC

Do not treat this list as already passed. Work through it on the
students' machine before 25 November 2026:

1. Create the venv, install `requirements.txt`, launch with `python app.py`.
2. Confirm the local browser shows the live camera stream, timestamp,
   and status pills.
3. Toggle motion detection and face detection; take a snapshot; start
   and stop a short recording and open the file in a player.
4. From a second computer on the trusted LAN, open
   `http://<server-lan-ip>:5000/` (bind with `--host 0.0.0.0` only for
   that demo; do not expose the port to the Internet).
5. Confirm two viewers still use one camera, then practise Ctrl+C
   shutdown and a missing-camera / busy-camera recovery.
