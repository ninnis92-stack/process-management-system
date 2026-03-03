(function initMotivation() {
  const slot = document.getElementById("motivation");
  if (!slot) return;

  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const lines = [
    "Ship, then shine.",
    "Small wins stack.",
    "Ask early, move fast.",
    "Simplify to speed up.",
    "Close loops daily.",
    "Progress beats perfect.",
    "Start narrow, ***REMOVED***nish strong.",
    "Done is feedback-ready.",
    "Fewer steps, faster flow.",
    "Clarity cuts rework.",
    "Draft fast, re***REMOVED***ne once.",
    "Make blockers visible.",
    "One owner, clear path.",
    "Tiny tasks, quick momentum.",
    "Decide, then iterate.",
    "Questions save sprints.",
    "Line up decisions early.",
    "Name the next step.",
    "Timebox and move.",
    "Share early, shift left.",
    "Less noise, more signal.",
    "Unblock, then optimize.",
    "Focus beats frenzy.",
    "Steady pace wins.",
  ];

  // Deterministic daily shuffle so the order changes each day but stays stable within the day
  const today = new Date();
  const daySeed = Number(`${today.getUTCFullYear()}${today.getUTCMonth() + 1}${today.getUTCDate()}`);
  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  const rand = mulberry32(daySeed);
  const order = lines
    .map(v => ({ v, r: rand() }))
    .sort((a, b) => a.r - b.r)
    .map(o => o.v);

  let idx = 0;
  slot.textContent = order[idx];
  slot.style.opacity = 1;

  if (!prefersReduced) {
    setInterval(() => {
      slot.style.opacity = 0;
      slot.style.transform = "translateY(-6px)";
      setTimeout(() => {
        idx = (idx + 1) % order.length;
        slot.textContent = order[idx];
        slot.style.transform = "translateY(6px)";
        requestAnimationFrame(() => {
          slot.style.opacity = 1;
          slot.style.transform = "translateY(0)";
        });
      }, 180);
    }, 8000);
  }
})();

(function initDashboardStyles() {
  // Apply delay and pct values emitted as data attributes in templates
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-delay]').forEach(el => {
      const d = el.getAttribute('data-delay');
      if (d != null && d !== '') el.style.animationDelay = String(d) + 's';
    });
    document.querySelectorAll('[data-pct]').forEach(span => {
      const pct = span.getAttribute('data-pct');
      if (pct != null && pct !== '') span.style.width = String(pct) + '%';
    });
  });
})();

(function initSearchHelpers() {
  // Highlight search terms in titles and small text and add '/' shortcut to focus search
  function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  document.addEventListener('DOMContentLoaded', () => {
    const params = new URLSearchParams(window.location.search);
    const q = (params.get('q') || '').trim();
    const input = document.getElementById('searchInput');

    // Keyboard shortcut: focus search on '/'
    document.addEventListener('keydown', (e) => {
      const active = document.activeElement;
      const tag = active && active.tagName && active.tagName.toLowerCase();
      if (e.key === '/' && tag !== 'input' && tag !== 'textarea' && tag !== 'select') {
        e.preventDefault();
        if (input) input.focus();
      }
    });

    if (!q) return;
    const re = new RegExp(escapeRegExp(q), 'ig');
    const toHighlight = document.querySelectorAll('.title, .text-muted, .meta');
    toHighlight.forEach(el => {
      try {
        // Simple innerHTML replace — acceptable for small snippets in this prototype
        const original = el.innerHTML;
        const replaced = original.replace(re, match => `<mark class="search-hit">${match}</mark>`);
        if (replaced !== original) el.innerHTML = replaced;
      } catch (e) {
        // fallback: ignore highlighting errors
      }
    });

    // Optional: scroll to ***REMOVED***rst hit
    const ***REMOVED***rst = document.querySelector('mark.search-hit');
    if (***REMOVED***rst) ***REMOVED***rst.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
})();

/* Highlight style */
const style = document.createElement('style');
style.textContent = `mark.search-hit { background: rgba(255,230,140,0.95); padding: 0 2px; border-radius: 2px; }`;
document.head.appendChild(style);

(function initTheme() {
  const btn = document.getElementById("vibeBtn");
  if (!btn) return;

  const palettes = [
    { name: "Red", nav: "#0b1726", accent: "#D32F2F", accent2: "#D32F2F", page: null },
    { name: "Magenta", nav: "#0b1726", accent: "#AD1457", accent2: "#AD1457", page: null },
    { name: "Purple", nav: "#0b1726", accent: "#8E24AA", accent2: "#8E24AA", page: null },
    { name: "Deep Purple", nav: "#0b1726", accent: "#5E35B1", accent2: "#5E35B1", page: null },
    { name: "Indigo", nav: "#0b1726", accent: "#3949AB", accent2: "#3949AB", page: null },
    { name: "Navy", nav: "#0b1726", accent: "#0D47A1", accent2: "#0D47A1", page: null },
    { name: "Blue", nav: "#0b1726", accent: "#1E88E5", accent2: "#1E88E5", page: null },
    { name: "Light Blue", nav: "#0b1726", accent: "#039BE5", accent2: "#039BE5", page: null },
    { name: "Cyan", nav: "#0b1726", accent: "#00ACC1", accent2: "#00ACC1", page: null },
    { name: "Teal", nav: "#0b1726", accent: "#00897B", accent2: "#00897B", page: null },
    { name: "Green", nav: "#0b1726", accent: "#43A047", accent2: "#43A047", page: null },
    { name: "Light Green", nav: "#0b1726", accent: "#7CB342", accent2: "#7CB342", page: null },
    { name: "Lime", nav: "#0b1726", accent: "#C0CA33", accent2: "#C0CA33", page: null },
    { name: "Yellow", nav: "#0b1726", accent: "#FBC02D", accent2: "#FBC02D", page: null },
    { name: "Amber", nav: "#0b1726", accent: "#FFA000", accent2: "#FFA000", page: null },
    { name: "Orange", nav: "#0b1726", accent: "#FB8C00", accent2: "#FB8C00", page: null },
    { name: "Deep Orange", nav: "#0b1726", accent: "#F4511E", accent2: "#F4511E", page: null },
    { name: "Coral", nav: "#0b1726", accent: "#FF7043", accent2: "#FF7043", page: null },
    { name: "Olive", nav: "#0b1726", accent: "#827717", accent2: "#827717", page: null },
    { name: "Gold", nav: "#0b1726", accent: "#B8860B", accent2: "#B8860B", page: null },
    { name: "Brown", nav: "#0b1726", accent: "#6D4C41", accent2: "#6D4C41", page: null },
    { name: "Blue Gray", nav: "#0b1726", accent: "#546E7A", accent2: "#546E7A", page: null },
    { name: "Gray", nav: "#0b1726", accent: "#616161", accent2: "#616161", page: null },
    { name: "Slate", nav: "#0b1726", accent: "#37474F", accent2: "#37474F", page: null },
  ];

  function applyTheme(idx) {
    const p = palettes[idx] || palettes[0];
    const root = document.documentElement;
    root.style.setProperty("--nav-bg", p.nav);
    root.style.setProperty("--nav-text", "#eef2f7");
    root.style.setProperty("--accent", p.accent);
    root.style.setProperty("--accent-2", p.accent2);
    if (p.page) {
      document.body.style.background = p.page;
    }
    const vibeLabel = document.getElementById("vibeLabel");
    btn.textContent = `Vibe · ${p.name}`;
    if (vibeLabel) vibeLabel.textContent = p.name;
    localStorage.setItem("vibeTheme", String(idx));
  }

  const stored = Number(localStorage.getItem("vibeTheme"));
  const dailySeed = (new Date()).getUTCDate() + (new Date()).getUTCMonth() * 31;
  const seededStart = dailySeed % palettes.length;
  const startIdx = Number.isFinite(stored) ? stored % palettes.length : seededStart;
  applyTheme(startIdx);

  btn.addEventListener("click", () => {
    const next = ((Number(localStorage.getItem("vibeTheme")) || 0) + 1) % palettes.length;
    applyTheme(next);
  });
})();

(function initNoti***REMOVED***cations() {
  const btn = document.getElementById("notifBtn");
  const dd = document.getElementById("notifDropdown");
  const list = document.getElementById("notifList");
  const badge = document.getElementById("notifBadge");
  const momentum = document.getElementById("notifMomentum");
  if (!btn || !dd || !list || !badge) return;

  function setActive(hasUnread) {
    btn.classList.toggle("notif-active", !!hasUnread);
  }

  async function refreshCount() {
    try {
      const r = await fetch("/noti***REMOVED***cations/unread_count");
      if (!r.ok) return;
      const data = await r.json();
      if (data.count > 0) {
        badge.style.display = "inline-block";
        badge.textContent = data.count;
        if (momentum) momentum.textContent = `Momentum: ${data.count} to review`;
        setActive(true);
      } else {
        badge.style.display = "none";
        if (momentum) momentum.textContent = "Momentum: Clear for now";
        setActive(false);
      }
    } catch (e) {
      list.innerHTML = "<div class='text-muted'>Unable to load noti***REMOVED***cations right now.</div>";
    }
  }

  async function loadLatest() {
    list.innerHTML = "<div class='text-muted'>Loading…</div>";
    try {
      const r = await fetch("/noti***REMOVED***cations/latest");
      if (!r.ok) return;
      const items = await r.json();
      list.innerHTML = items.map(n => `
        <div class="border rounded p-2 mb-2 notif-item ${n.is_read ? "opacity-75" : ""}" data-id="${n.id}" data-url="${n.url || ''}">
          <div><strong>${n.title}</strong></div>
          ${n.body ? `<div>${n.body}</div>` : ""}
          ${n.url ? `<div class="small text-primary">Open</div>` : ""}
        </div>
      `).join("") || "<div class='text-muted'>No noti***REMOVED***cations.</div>";
    } catch (e) {
      list.innerHTML = "<div class='text-muted'>Unable to load noti***REMOVED***cations right now.</div>";
    }
  }

  list.addEventListener("click", async (ev) => {
    const item = ev.target.closest(".notif-item");
    if (!item) return;
    const id = item.dataset.id;
    const url = item.dataset.url;
    try {
      await fetch(`/noti***REMOVED***cations/${id}/read`, { method: "POST" });
    } catch (e) { /* ignore */ }
    if (url) {
      window.location.href = url;
    }
  });

  btn.addEventListener("click", async () => {
    const willOpen = !dd.classList.contains("open");
    dd.classList.toggle("open", willOpen);
    btn.classList.toggle("open", willOpen);
    if (willOpen) {
      await loadLatest();
      await refreshCount();
    }
  });

  document.addEventListener("click", (ev) => {
    if (!dd.contains(ev.target) && !btn.contains(ev.target)) {
      dd.classList.remove("open");
      btn.classList.remove("open");
    }
  });

  refreshCount();
  setInterval(refreshCount, 30000);
})();

(function initFocusPills() {
  const lines = [
    "Unblock one item",
    "Share a draft",
    "Close a loop",
    "Prep a handoff",
    "Trim one step",
    "Ask one question",
  ];
  document.querySelectorAll(".focus-pill").forEach((pill, i) => {
    const text = lines[i % lines.length];
    pill.textContent = `Focus: ${text}`;
  });
})();

(function initAlertEncouragements() {
  const lines = [
    "Small wins stack—keep going.",
    "Share early, shift left.",
    "Finish one thing today.",
  ];
  document.querySelectorAll(".alert").forEach((a, i) => {
    const line = document.createElement("div");
    line.className = "small text-muted mt-1";
    line.textContent = lines[i % lines.length];
    a.appendChild(line);
  });
})();

(function initFilePreview() {
  const ***REMOVED***leInput = document.getElementById("***REMOVED***leInput");
  const pasteZone = document.getElementById("pasteZone");
  const preview = document.getElementById("preview");
  if (!***REMOVED***leInput || !pasteZone || !preview) return;

  const dt = new DataTransfer();

  function refreshPreview() {
    preview.innerHTML = "";
    for (const ***REMOVED***le of dt.***REMOVED***les) {
      const img = document.createElement("img");
      img.className = "preview-img";
      img.alt = ***REMOVED***le.name;
      img.src = URL.createObjectURL(***REMOVED***le);
      preview.appendChild(img);
    }
    ***REMOVED***leInput.***REMOVED***les = dt.***REMOVED***les;
  }

  function addFile(***REMOVED***le) {
    if (!***REMOVED***le.type.startsWith("image/")) return;
    dt.items.add(***REMOVED***le);
    refreshPreview();
  }

  pasteZone.addEventListener("click", () => pasteZone.focus());
  pasteZone.setAttribute("tabindex", "0");

  pasteZone.addEventListener("paste", (e) => {
    const items = e.clipboardData?.items || [];
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        const ***REMOVED***le = item.getAsFile();
        if (***REMOVED***le) addFile(***REMOVED***le);
      }
    }
  });

  pasteZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    pasteZone.classList.add("paste-zone-hover");
  });
  pasteZone.addEventListener("dragleave", () => {
    pasteZone.classList.remove("paste-zone-hover");
  });
  pasteZone.addEventListener("drop", (e) => {
    e.preventDefault();
    pasteZone.classList.remove("paste-zone-hover");
    const ***REMOVED***les = e.dataTransfer?.***REMOVED***les || [];
    for (const f of ***REMOVED***les) addFile(f);
  });

  ***REMOVED***leInput.addEventListener("change", () => {
    dt.items.clear();
    for (const f of ***REMOVED***leInput.***REMOVED***les) addFile(f);
  });
})();
