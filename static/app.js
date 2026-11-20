(function () {
  "use strict";

  var STATUS_URL = "/api/status";
  var SNAPSHOT_URL = "/api/snapshot";
  var MOTION_URL = "/api/motion";
  var FACES_URL = "/api/faces";
  var RECORDING_START_URL = "/api/recording/start";
  var RECORDING_STOP_URL = "/api/recording/stop";
  var POLL_MS = 2000;
  var els = {
    alert: document.getElementById("alert"),
    connection: document.getElementById("connection"),
    connectionPill: document.getElementById("connection-pill"),
    source: document.getElementById("source"),
    resolution: document.getElementById("resolution"),
    fps: document.getElementById("fps"),
    quality: document.getElementById("quality"),
    timestamp: document.getElementById("timestamp"),
    stream: document.getElementById("stream"),
    badge: document.getElementById("source-badge"),
    snapshotButton: document.getElementById("snapshot-button"),
    snapshotResult: document.getElementById("snapshot-result"),
    snapshotPreview: document.getElementById("snapshot-preview"),
    motionState: document.getElementById("motion-state"),
    motionStatePill: document.getElementById("motion-state-pill"),
    motionSensitivityStatus: document.getElementById("motion-sensitivity-status"),
    motionCooldown: document.getElementById("motion-cooldown"),
    motionLastEvent: document.getElementById("motion-last-event"),
    motionLogCount: document.getElementById("motion-log-count"),
    motionEnabled: document.getElementById("motion-enabled"),
    motionSensitivity: document.getElementById("motion-sensitivity"),
    sensitivityValue: document.getElementById("sensitivity-value"),
    motionControlResult: document.getElementById("motion-control-result"),
    motionLog: document.getElementById("motion-log"),
    recordingState: document.getElementById("recording-state"),
    recordingStatePill: document.getElementById("recording-state-pill"),
    recordingFile: document.getElementById("recording-file"),
    recordingResult: document.getElementById("recording-result"),
    recordingError: document.getElementById("recording-error"),
    startRecording: document.getElementById("start-recording"),
    stopRecording: document.getElementById("stop-recording"),
    faceState: document.getElementById("face-state"),
    faceStatePill: document.getElementById("face-state-pill"),
    faceCount: document.getElementById("face-count"),
    faceEnabled: document.getElementById("face-enabled"),
    faceControlResult: document.getElementById("face-control-result")
  };
  var recordingRequestInFlight = false;
  var motionUpdateInFlight = false;
  var faceUpdateInFlight = false;

  function setText(el, text) {
    if (el) {
      el.textContent = text;
    }
  }

  function showAlert(message, kind) {
    if (!els.alert) {
      return;
    }
    if (!message) {
      els.alert.className = "alert hidden";
      els.alert.textContent = "";
      return;
    }
    els.alert.className = "alert alert-" + (kind || "error");
    els.alert.textContent = message;
  }

  function setConnectionState(ok, label) {
    setText(els.connection, label);
    if (els.connectionPill) {
      els.connectionPill.classList.toggle("ok", !!ok);
      els.connectionPill.classList.toggle("bad", !ok);
    }
  }

  function applyStatus(data) {
    var configured = data.configured || {};
    var actual = data.actual_capture || {};
    var sourceLabel = data.active_source || "unknown";
    if (data.requested_source && data.requested_source !== data.active_source) {
      sourceLabel = data.active_source + " (requested " + data.requested_source + ")";
    }
    setText(els.source, sourceLabel);

    var configuredRes = (configured.width || "—") + "×" + (configured.height || "—");
    if (actual.width && actual.height &&
        (actual.width !== configured.width || actual.height !== configured.height)) {
      setText(
        els.resolution,
        configuredRes + " configured; capture reports " + actual.width + "×" + actual.height
      );
    } else {
      setText(els.resolution, configuredRes);
    }

    if (typeof configured.fps !== "undefined") {
      setText(els.fps, String(configured.fps) + " (configured target)");
    }
    if (typeof configured.jpeg_quality !== "undefined") {
      setText(els.quality, String(configured.jpeg_quality));
    }

    var overlayOn = data.timestamp_overlay;
    if (typeof overlayOn === "undefined" && configured) {
      overlayOn = configured.timestamp_overlay;
    }
    if (typeof overlayOn !== "undefined") {
      if (overlayOn) {
        var zone = data.timestamp_zone_label || "HKT";
        var offset = data.timestamp_utc_offset || "UTC+8";
        setText(els.timestamp, "On (" + zone + ", " + offset + ")");
      } else {
        setText(els.timestamp, "Off");
      }
    }

    if (els.badge) {
      if (data.is_synthetic) {
        els.badge.classList.remove("hidden");
      } else {
        els.badge.classList.add("hidden");
      }
    }

    if (data.error) {
      setConnectionState(false, "Server reached, source error");
      showAlert(data.error, "error");
    } else if (data.notice) {
      setConnectionState(!!data.capture_running, data.capture_running ? "Connected" : "Capture stopped");
      showAlert(data.notice, "notice");
    } else {
      setConnectionState(!!data.ok, data.capture_running ? "Connected" : "Capture stopped");
      showAlert("", "");
    }

    applyMotionStatus(data.motion || {});
    applyFaceStatus(data.faces || {});
    applyRecordingStatus(data.recording || {});
  }

  function applyMotionStatus(motion) {
    var enabled = !!motion.enabled;
    var detected = !!motion.currently_detected;
    var label;
    if (!enabled) {
      label = "Off";
    } else if (detected) {
      label = "Detected";
    } else {
      label = "On (quiet)";
    }
    setText(els.motionState, label);
    if (els.motionStatePill) {
      els.motionStatePill.classList.remove("motion-on", "motion-hit", "motion-off");
      if (!enabled) {
        els.motionStatePill.classList.add("motion-off");
      } else if (detected) {
        els.motionStatePill.classList.add("motion-hit");
      } else {
        els.motionStatePill.classList.add("motion-on");
      }
    }

    if (typeof motion.sensitivity !== "undefined") {
      setText(
        els.motionSensitivityStatus,
        String(motion.sensitivity) + " (1=least, 100=most)"
      );
      if (els.motionSensitivity && !motionUpdateInFlight && document.activeElement !== els.motionSensitivity) {
        els.motionSensitivity.value = String(motion.sensitivity);
      }
      if (els.sensitivityValue && document.activeElement !== els.motionSensitivity) {
        setText(els.sensitivityValue, String(motion.sensitivity));
      }
    }
    if (typeof motion.cooldown_seconds !== "undefined") {
      setText(els.motionCooldown, String(motion.cooldown_seconds) + " s (configured)");
    }
    setText(els.motionLastEvent, motion.last_event_at || "None yet");
    if (typeof motion.log_count !== "undefined") {
      var cap = motion.log_capacity || "—";
      setText(els.motionLogCount, motion.log_count + " / " + cap + " (bounded)");
    }

    if (els.motionEnabled && !motionUpdateInFlight && document.activeElement !== els.motionEnabled) {
      els.motionEnabled.checked = enabled;
    }
    renderMotionLog(motion.events || []);
  }

  function renderMotionLog(events) {
    if (!els.motionLog) {
      return;
    }
    els.motionLog.innerHTML = "";
    if (!events.length) {
      var empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = "No motion events yet.";
      els.motionLog.appendChild(empty);
      return;
    }
    // Newest first for the demonstration list.
    for (var i = events.length - 1; i >= 0; i--) {
      var item = events[i] || {};
      var li = document.createElement("li");
      var time = document.createElement("span");
      time.className = "event-time";
      time.textContent = item.time || "";
      li.appendChild(time);
      li.appendChild(document.createTextNode(item.message || "Motion detected"));
      els.motionLog.appendChild(li);
    }
  }

  function setMotionControlResult(message, ok) {
    if (!els.motionControlResult) {
      return;
    }
    els.motionControlResult.textContent = message || "";
    els.motionControlResult.className = message ? (ok ? "ok" : "bad") : "";
  }

  function postMotionSettings(payload, successMessage) {
    motionUpdateInFlight = true;
    fetch(MOTION_URL, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { okHttp: response.ok, data: data || {} };
        });
      })
      .then(function (result) {
        var data = result.data;
        if (data.ok) {
          applyMotionStatus(data);
          setMotionControlResult(successMessage || "Motion settings updated.", true);
        } else {
          setMotionControlResult(data.error || "Could not update motion settings.", false);
        }
      })
      .catch(function (err) {
        setMotionControlResult("Could not update motion settings. " + err.message, false);
      })
      .finally(function () {
        motionUpdateInFlight = false;
      });
  }

  function applyFaceStatus(faces) {
    var enabled = !!faces.enabled;
    var count = typeof faces.detected_count === "number" ? faces.detected_count : 0;
    var label;
    if (!enabled) {
      label = "Off";
    } else {
      label = "On (detection only)";
    }
    setText(els.faceState, label);
    setText(els.faceCount, String(count));
    if (els.faceStatePill) {
      els.faceStatePill.classList.remove("faces-on", "faces-hit", "faces-off");
      if (!enabled) {
        els.faceStatePill.classList.add("faces-off");
      } else if (count > 0) {
        els.faceStatePill.classList.add("faces-hit");
      } else {
        els.faceStatePill.classList.add("faces-on");
      }
    }
    if (els.faceEnabled && !faceUpdateInFlight && document.activeElement !== els.faceEnabled) {
      els.faceEnabled.checked = enabled;
    }
  }

  function setFaceControlResult(message, ok) {
    if (!els.faceControlResult) {
      return;
    }
    els.faceControlResult.textContent = message || "";
    els.faceControlResult.className = message ? (ok ? "ok" : "bad") : "";
  }

  function postFaceSettings(payload, successMessage) {
    faceUpdateInFlight = true;
    fetch(FACES_URL, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { okHttp: response.ok, data: data || {} };
        });
      })
      .then(function (result) {
        var data = result.data;
        if (data.ok) {
          applyFaceStatus(data);
          setFaceControlResult(successMessage || "Face-detection settings updated.", true);
        } else {
          setFaceControlResult(data.error || "Could not update face-detection settings.", false);
        }
      })
      .catch(function (err) {
        setFaceControlResult("Could not update face-detection settings. " + err.message, false);
      })
      .finally(function () {
        faceUpdateInFlight = false;
      });
  }

  function setRecordingResult(message, ok) {
    if (!els.recordingResult) {
      return;
    }
    els.recordingResult.textContent = message || "";
    els.recordingResult.className = message ? (ok ? "ok" : "bad") : "";
  }

  function setRecordingError(message) {
    if (!els.recordingError) {
      return;
    }
    if (!message) {
      els.recordingError.textContent = "";
      els.recordingError.classList.add("hidden");
      return;
    }
    els.recordingError.textContent = message;
    els.recordingError.classList.remove("hidden");
  }

  function applyRecordingStatus(recording) {
    var state = recording.state || (recording.recording ? "recording" : "idle");
    var label;
    if (state === "recording") {
      label = "Recording";
      if (typeof recording.elapsed_seconds === "number") {
        label += " (" + recording.elapsed_seconds.toFixed(1) + " s)";
      }
    } else if (state === "error") {
      label = "Error";
    } else {
      label = "Not recording";
    }
    setText(els.recordingState, label);
    if (els.recordingStatePill) {
      els.recordingStatePill.classList.remove("recording-on", "recording-idle", "recording-error");
      if (state === "recording") {
        els.recordingStatePill.classList.add("recording-on");
      } else if (state === "error") {
        els.recordingStatePill.classList.add("recording-error");
      } else {
        els.recordingStatePill.classList.add("recording-idle");
      }
    }

    var filename = recording.current_filename || recording.filename || recording.last_filename;
    if (filename) {
      setText(els.recordingFile, filename);
    } else {
      setText(els.recordingFile, "None yet");
    }

    setRecordingError(recording.error || "");

    if (els.startRecording && !recordingRequestInFlight) {
      els.startRecording.disabled = state === "recording";
    }
    if (els.stopRecording && !recordingRequestInFlight) {
      els.stopRecording.disabled = state !== "recording";
    }
  }

  function postRecording(url, successMessage) {
    if (recordingRequestInFlight) {
      return;
    }
    recordingRequestInFlight = true;
    if (els.faceEnabled) {
    els.faceEnabled.addEventListener("change", function () {
      var enabled = !!els.faceEnabled.checked;
      postFaceSettings(
        { enabled: enabled },
        enabled
          ? "Face detection enabled (detection only, not recognition)."
          : "Face detection disabled. New boxes will not be drawn."
      );
    });
  }

  if (els.startRecording) {
      els.startRecording.disabled = true;
    }
    if (els.stopRecording) {
      els.stopRecording.disabled = true;
    }
    fetch(url, {
      method: "POST",
      cache: "no-store",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({})
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { okHttp: response.ok, data: data || {} };
        });
      })
      .then(function (result) {
        var data = result.data;
        applyRecordingStatus(data);
        if (data.ok) {
          setRecordingResult(successMessage || "Recording updated.", true);
        } else {
          setRecordingResult(data.error || "Recording request failed.", false);
        }
      })
      .catch(function (err) {
        setRecordingResult("Recording request failed. " + err.message, false);
      })
      .finally(function () {
        recordingRequestInFlight = false;
        refreshStatus();
      });
  }

  function refreshStatus() {
    fetch(STATUS_URL, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Status request failed (" + response.status + ")");
        }
        return response.json();
      })
      .then(applyStatus)
      .catch(function (err) {
        setConnectionState(false, "Disconnected");
        showAlert(
          "Cannot reach the video server. Check that the application is still running. " +
            err.message,
          "error"
        );
      });
  }

  if (els.stream) {
    els.stream.addEventListener("error", function () {
      setConnectionState(false, "Stream interrupted");
      showAlert("The live stream was interrupted. The page will keep retrying.", "error");
      window.setTimeout(function () {
        els.stream.src = "/video_feed?retry=" + Date.now();
      }, 2000);
    });
  }


  function setSnapshotResult(message, ok) {
    if (!els.snapshotResult) {
      return;
    }
    els.snapshotResult.textContent = message || "";
    els.snapshotResult.className = message ? (ok ? "ok" : "bad") : "";
  }

  function takeSnapshot() {
    if (!els.snapshotButton) {
      return;
    }
    els.snapshotButton.disabled = true;
    setSnapshotResult("Saving snapshot…", true);
    fetch(SNAPSHOT_URL, {
      method: "POST",
      cache: "no-store",
      headers: { "Accept": "application/json" }
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { okHttp: response.ok, data: data || {} };
        });
      })
      .then(function (result) {
        var data = result.data;
        if (data.ok && data.filename) {
          setSnapshotResult("Saved snapshot: " + data.filename, true);
          if (els.snapshotPreview) {
            els.snapshotPreview.src = "/api/snapshot/latest?t=" + Date.now();
            els.snapshotPreview.classList.remove("hidden");
          }
        } else {
          setSnapshotResult(data.error || "Snapshot failed.", false);
        }
      })
      .catch(function (err) {
        setSnapshotResult("Snapshot failed. " + err.message, false);
      })
      .finally(function () {
        els.snapshotButton.disabled = false;
      });
  }

  if (els.snapshotButton) {
    els.snapshotButton.addEventListener("click", takeSnapshot);
  }

  if (els.motionEnabled) {
    els.motionEnabled.addEventListener("change", function () {
      var enabled = !!els.motionEnabled.checked;
      postMotionSettings(
        { enabled: enabled },
        enabled ? "Motion detection enabled." : "Motion detection disabled. New events will not be recorded."
      );
    });
  }

  if (els.motionSensitivity) {
    els.motionSensitivity.addEventListener("input", function () {
      setText(els.sensitivityValue, els.motionSensitivity.value);
    });
    els.motionSensitivity.addEventListener("change", function () {
      var value = parseInt(els.motionSensitivity.value, 10);
      postMotionSettings(
        { sensitivity: value },
        "Sensitivity set to " + value + " (higher = more sensitive)."
      );
    });
  }

  if (els.startRecording) {
    els.startRecording.addEventListener("click", function () {
      if (els.startRecording.disabled) {
        return;
      }
      setRecordingResult("Starting recording…", true);
      postRecording(RECORDING_START_URL, "Recording started.");
    });
  }

  if (els.stopRecording) {
    els.stopRecording.addEventListener("click", function () {
      if (els.stopRecording.disabled) {
        return;
      }
      setRecordingResult("Stopping recording…", true);
      postRecording(RECORDING_STOP_URL, "Recording stopped and the file was saved.");
    });
  }

  refreshStatus();
  window.setInterval(refreshStatus, POLL_MS);
})();
