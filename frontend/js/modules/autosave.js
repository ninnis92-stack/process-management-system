function initAutosave() {
  if (window.__autosaveModuleLoaded) return;
  window.__autosaveModuleLoaded = true;

  const storageKey = "toggle_states";
  const path = window.location.pathname;
  const pending = new Map();

  function sessionPersistForms() {
    return Array.from(
      document.querySelectorAll('form[data-toggle-session-persist="session"]')
    );
  }

  function restore() {
    try {
      const all = JSON.parse(sessionStorage.getItem(storageKey) || "{}");
      const saved = all[path];
      const forms = sessionPersistForms();
      if (saved && Array.isArray(saved) && forms.length) {
        saved.forEach((state) => {
          const checkbox = forms
            .map((form) =>
              form.querySelector(`.form-check-input[name="${state.name}"]`)
            )
            .find(Boolean);
          if (checkbox) {
            checkbox.checked = state.checked;
            checkbox.dispatchEvent(new Event("change"));
          }
        });
      }
      delete all[path];
      sessionStorage.setItem(storageKey, JSON.stringify(all));
    } catch (error) {
      // ignore restore failures so page interactions still work
    }
  }

  function saveState() {
    try {
      const forms = sessionPersistForms();
      if (!forms.length) return;
      const all = JSON.parse(sessionStorage.getItem(storageKey) || "{}");
      const list = forms.flatMap((form) =>
        Array.from(
          form.querySelectorAll('.form-check-input[data-toggle-text-checked]')
        ).map((checkbox) => ({ name: checkbox.name, checked: checkbox.checked }))
      );
      all[path] = list;
      sessionStorage.setItem(storageKey, JSON.stringify(all));
    } catch (error) {
      // ignore save failures so toggles still change locally
    }
  }

  function buildPayloadFromForm(form) {
    const payload = {};
    Array.from(form.elements).forEach((element) => {
      if (!element.name || element.type === "file") return;
      if (element.type === "checkbox") {
        payload[`${element.name}_present`] = "1";
        payload[element.name] = element.checked ? element.value || "y" : "";
      } else if (
        element.tagName === "SELECT" ||
        element.tagName === "INPUT" ||
        element.tagName === "TEXTAREA"
      ) {
        payload[element.name] = element.value;
      }
    });
    return payload;
  }

  function sendForm(form, options = {}) {
    const endpoint = form.dataset.autosaveEndpoint;
    if (!endpoint) return;
    const payload = JSON.stringify(buildPayloadFromForm(form));
    try {
      if (window.fetch) {
        fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: payload,
          keepalive: !!options.keepalive,
        })
          .then(async (response) => {
            let responsePayload = null;
            try {
              responsePayload = await response.clone().json();
            } catch (error) {
              // ignore non-json autosave responses
            }
            try {
              window.dispatchEvent(
                new CustomEvent("form:autosaved", {
                  detail: {
                    endpoint,
                    ok: response.ok,
                    status: response.status,
                    payload: responsePayload,
                  },
                })
              );
            } catch (error) {
              // ignore dispatch failures
            }
          })
          .catch(() => {});
      } else if (navigator.sendBeacon) {
        navigator.sendBeacon(endpoint, payload);
      }
    } catch (error) {
      // ignore transport failures
    }
  }

  function scheduleSave(form) {
    if (pending.has(form)) clearTimeout(pending.get(form));
    const timeoutId = setTimeout(() => {
      pending.delete(form);
      sendForm(form);
    }, 160);
    pending.set(form, timeoutId);
  }

  document.addEventListener("DOMContentLoaded", restore);
  document.body.addEventListener("change", (event) => {
    const element = event.target;
    if (!(element instanceof Element)) return;
    const form = element.closest("form[data-autosave-endpoint]");
    if (form && element.matches("input, select, textarea")) {
      scheduleSave(form);
    }
    if (
      element.matches(".form-check-input") &&
      element.closest('form[data-toggle-session-persist="session"]')
    ) {
      saveState();
    }
  });

  window.addEventListener("beforeunload", () => {
    pending.forEach((timeoutId) => clearTimeout(timeoutId));
    pending.clear();
    document
      .querySelectorAll("form[data-autosave-endpoint]")
      .forEach((form) => sendForm(form, { keepalive: true }));
  });

  sessionPersistForms().forEach((form) => form.addEventListener("submit", saveState));
}

window.initAutosave = initAutosave;
initAutosave();
