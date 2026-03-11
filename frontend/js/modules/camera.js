function normalizeCameraSeparator(rawValue) {
  const raw = String(rawValue || "").trim();
  if (!raw) return ",";
  const aliases = {
    comma: ",",
    semicolon: ";",
    pipe: "|",
    newline: "\n",
    "\\n": "\n",
    tab: "\t",
    "\\t": "\t",
  };
  return aliases[raw.toLowerCase()] || raw;
}

function getCameraStatusSlot(target) {
  if (!target || !target.form) return null;
  const fieldName = target.getAttribute("name");
  if (!fieldName) return null;
  return target.form.querySelector(`[data-field-status-for="${fieldName}"]`);
}

function setCameraStatus(target, message, tone) {
  const slot = getCameraStatusSlot(target);
  if (!slot) return;
  slot.textContent = message || "";
  slot.classList.remove("is-success", "is-warning", "is-loading");
  if (tone === "success") slot.classList.add("is-success");
  if (tone === "warning") slot.classList.add("is-warning");
  if (tone === "loading") slot.classList.add("is-loading");
}

function splitCameraValues(rawValue, separator) {
  const value = String(rawValue || "");
  if (!value.trim()) return [];
  if (separator === "\n") {
    return value.split(/\r?\n/).map((part) => part.trim()).filter(Boolean);
  }
  return value.split(separator).map((part) => part.trim()).filter(Boolean);
}

function appendCameraValue(existingValue, nextValue, separator, dedupe) {
  const existingItems = splitCameraValues(existingValue, separator);
  const normalizedNext = String(nextValue || "").trim();
  if (!normalizedNext) {
    return {
      value: existingValue || "",
      added: false,
      duplicate: false,
      count: existingItems.length,
    };
  }

  if (dedupe) {
    const seen = new Set(existingItems.map((item) => item.toLowerCase()));
    if (seen.has(normalizedNext.toLowerCase())) {
      return {
        value: existingValue || "",
        added: false,
        duplicate: true,
        count: existingItems.length,
      };
    }
  }

  const joiner = separator === "\n" ? "\n" : `${separator} `;
  const merged = existingItems.length
    ? `${existingValue}${joiner}${normalizedNext}`
    : normalizedNext;

  return {
    value: merged,
    added: true,
    duplicate: false,
    count: existingItems.length + 1,
  };
}

function sendCameraImage(blob, fieldName) {
  const data = new FormData();
  data.append("image", blob, "capture.jpg");
  if (fieldName) data.append("field", fieldName);
  return fetch("/verify/camera", { method: "POST", body: data }).then((response) =>
    response.json()
  );
}

function attachCameraTrigger(button, targetSelector) {
  if (!button) return;
  const target = document.querySelector(targetSelector);
  if (!target) return;
  button.addEventListener("click", async () => {
    const mode = button.dataset.cameraMode === "append" ? "append" : "replace";
    const separator = normalizeCameraSeparator(button.dataset.cameraSeparator);
    const dedupe = button.dataset.cameraDedupe !== "false";
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setCameraStatus(
          target,
          "Camera capture is not available on this device. Please type the value manually.",
          "warning"
        );
        alert("Camera access failed, please use file picker");
        return;
      }

      setCameraStatus(
        target,
        mode === "append" ? "Opening camera to add another value…" : "Opening camera…",
        "loading"
      );
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      const video = document.createElement("video");
      video.srcObject = stream;
      await video.play();
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      stream.getTracks().forEach((track) => track.stop());
      canvas.toBlob(async (blob) => {
        const fieldName = target.getAttribute("name");
        const result = await sendCameraImage(blob, fieldName);
        if (result.ok && result.field && result.value) {
          const input = document.querySelector(`[name="${result.field}"]`);
          if (input) {
            if (mode === "append") {
              const merged = appendCameraValue(input.value, result.value, separator, dedupe);
              if (merged.duplicate) {
                setCameraStatus(
                  input,
                  "That scanned value is already in the list. Scan the next item or submit the form.",
                  "warning"
                );
                return;
              }
              if (!merged.added) {
                setCameraStatus(input, "No readable value was captured. Try scanning again.", "warning");
                return;
              }
              input.value = merged.value;
              setCameraStatus(
                input,
                `Added scan ${merged.count}. Capture again to keep building this list.`,
                "success"
              );
            } else {
              input.value = result.value;
              setCameraStatus(input, "Captured value from camera.", "success");
            }
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
            input.dispatchEvent(new Event("template-prefill-run", { bubbles: true }));
          }
        } else {
          setCameraStatus(
            target,
            "No readable value was captured. Try again or type the value manually.",
            "warning"
          );
        }
      }, "image/jpeg");
    } catch (error) {
      setCameraStatus(
        target,
        "Camera access failed. You can still type values manually.",
        "warning"
      );
      alert("Camera access failed, please use file picker");
    }
  });
}

function initCameraCapture() {
  if (window.__cameraModuleLoaded) return;
  window.__cameraModuleLoaded = true;
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("button[data-camera-target]").forEach((button) => {
      attachCameraTrigger(button, button.dataset.cameraTarget);
    });
  });
}

window.normalizeCameraSeparator = normalizeCameraSeparator;
window.appendCameraValue = appendCameraValue;
window.sendCameraImage = sendCameraImage;
window.attachCameraTrigger = attachCameraTrigger;
window.initCameraCapture = initCameraCapture;
initCameraCapture();
