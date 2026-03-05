(function initMotivation() {
  const slot = document.getElementById("motivation");
  if (!slot) return;

  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const lines = [
    "Sort today: socks ***REMOVED***rst, worries later.",
    "A folded stack is a small victory.",
    "One load at a time, one win at a time.",
    "Tackle the smallest basket ***REMOVED***rst.",
    "Fresh socks, fresh perspective.",
    "Turn laundry into a tiny ritual of calm.",
    "Don't wait for motivation—start the wash.",
    "Clean clothes, clearer head.",
    "Fold with intention; carry less chaos.",
    "A warm dryer is a hug for your clothes.",
    "Separate colors, not your priorities.",
    "Make today productive—***REMOVED***nish one load.",
    "Every matched pair is progress.",
    "Treat stains as experiments, not failures.",
    "Declutter your closet, declutter your day.",
    "A neat drawer frees mental space.",
    "Air-dry patience; speed comes after practice.",
    "Small care preserves the longest wear.",
    "Refresh your routine with a fresh load.",
    "Laundry ***REMOVED*** is peace earned.",
    "Celebrate a completed basket.",
    "Put it away; let it be ***REMOVED***nished.",
    "Socks ***REMOVED***nd their way home eventually.",
    "Folded clothes, elevated mood."
  ];

  // Stable per-day seed (days since epoch) so the order changes each day.
  const daySeed = Math.floor(Date.now() / 86400000);
  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  const rand = mulberry32(daySeed);
  const order = lines.map(v => ({ v, r: rand() })).sort((a, b) => a.r - b.r).map(o => o.v);
  let idx = 0;

  // show text with optional animation
  function showQuote(i, animate = true) {
    if (!slot) return;
    if (prefersReduced || !animate) {
      slot.textContent = order[i];
      slot.style.opacity = 1;
      slot.style.transform = 'translateY(0)';
      return;
    }
    slot.style.opacity = 0;
    slot.style.transform = 'translateY(-6px)';
    setTimeout(() => {
      slot.textContent = order[i];
      slot.style.transform = 'translateY(6px)';
      requestAnimationFrame(() => {
        slot.style.opacity = 1;
        slot.style.transform = 'translateY(0)';
      });
    }, 180);
  }

  showQuote(idx, false);

  // make clickable and keyboard-activatable
  slot.setAttribute('role', 'button');
  slot.setAttribute('tabindex', '0');
  slot.style.cursor = 'pointer';

  function advance() {
    const nextIdx = (idx + 1) % order.length;
    if (!prefersReduced && slot.animate) {
      // animate out
      const out = slot.animate([
        { opacity: 1, transform: 'translateY(0)' },
        { opacity: 0, transform: 'translateY(-8px)' }
      ], { duration: 200, easing: 'cubic-bezier(.2,.8,.2,1)', ***REMOVED***ll: 'forwards' });
      out.on***REMOVED***nish = () => {
        idx = nextIdx;
        slot.textContent = order[idx];
        // animate in
        const _in = slot.animate([
          { opacity: 0, transform: 'translateY(8px)' },
          { opacity: 1, transform: 'translateY(0)' }
        ], { duration: 260, easing: 'cubic-bezier(.2,.8,.2,1)', ***REMOVED***ll: 'forwards' });
      };
    } else {
      idx = nextIdx;
      showQuote(idx, !prefersReduced);
    }
  }

  slot.addEventListener('click', () => advance());
  slot.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      advance();
    }
  });

  if (!prefersReduced) {
    setInterval(() => advance(), 8000);
  }
})();

// Attach CSRF token from meta to fetch POST/PUT/DELETE requests automatically
(function attachCsrfToFetch(){
  const meta = document.querySelector('meta[name="csrf-token"]');
  if(!meta) return;
  const token = meta.getAttribute('content');
  if(!token) return;

  const _orig = window.fetch;
  window.fetch = function(input, init){
    init = init || {};
    const method = (init.method || 'GET').toUpperCase();
    if(method !== 'GET' && method !== 'HEAD'){
      init.headers = init.headers || {};
      // Do not overwrite if already provided
      if(!init.headers['X-CSRFToken'] && !init.headers['X-CSRF-Token']){
        init.headers['X-CSRFToken'] = token;
        init.headers['X-CSRF-Token'] = token;
      }
      // Also include common AJAX header
      if(!init.headers['X-Requested-With']) init.headers['X-Requested-With'] = 'XMLHttpRequest';
    }
    return _orig.call(this, input, init);
  };
})();

(function initTheme() {
  const btn = document.getElementById("vibeBtn");
  if (!btn) return;

  // 24 pastel / muted palettes that are easy on the eyes (accent = primary, accent2 = softer shade)
  const palettes = [
    { name: "Soft Coral", accent: "#E47D6A", accent2: "#F5E9E6" },
    { name: "Warm Sand", accent: "#DDB892", accent2: "#FAF5EE" },
    { name: "Moss", accent: "#A7C28C", accent2: "#F0F7ED" },
    { name: "Sage", accent: "#8FA98A", accent2: "#EFF6EE" },
    { name: "Muted Teal", accent: "#6FB1B1", accent2: "#EDF7F7" },
    { name: "Sky", accent: "#7FB3D5", accent2: "#EFF8FC" },
    { name: "Powder Blue", accent: "#9FC6E7", accent2: "#F6FBFF" },
    { name: "Lavender", accent: "#B9A7E0", accent2: "#F6F3FB" },
    { name: "Lilac", accent: "#C7B3D6", accent2: "#FBF8FD" },
    { name: "Muted Pink", accent: "#E8B7C8", accent2: "#FFF5F8" },
    { name: "Peach", accent: "#F2B091", accent2: "#FFF6F2" },
    { name: "Butter", accent: "#F4D58D", accent2: "#FFFDF2" },
    { name: "Pistachio", accent: "#D6E8C3", accent2: "#FBFDF4" },
    { name: "Mint", accent: "#BFEAD6", accent2: "#F9FFFB" },
    { name: "Seafoam", accent: "#9EE3C5", accent2: "#F7FFF6" },
    { name: "Aqua", accent: "#8ED6D1", accent2: "#F4FFFE" },
    { name: "Robin Egg", accent: "#8EC7E6", accent2: "#F5FDFF" },
    { name: "Periwinkle", accent: "#B2C8F9", accent2: "#F8FBFF" },
    { name: "Dusty Blue", accent: "#9BB1C8", accent2: "#F6F9FB" },
    { name: "Slate Rose", accent: "#C9A6A6", accent2: "#FBF6F6" },
    { name: "Tea", accent: "#C9D6B3", accent2: "#FBFDF4" },
    { name: "Stone", accent: "#BFC8C6", accent2: "#F7F9F9" },
    { name: "Soft Gray", accent: "#BDC3C7", accent2: "#FAFBFC" },
    { name: "Charcoal Mist", accent: "#93A0A8", accent2: "#F1F5F6" },
    { name: "Aurora", accent: "#0F766E", accent2: "#E6FAF8" }
  ];

  function hexToRgb(hex) {
    const normalized = hex.replace('#', '');
    const bigint = parseInt(normalized.length === 3
      ? normalized.split('').map(c => c + c).join('')
      : normalized, 16);
    return {
      r: (bigint >> 16) & 255,
      g: (bigint >> 8) & 255,
      b: bigint & 255,
    };
  }

  function darkenHex(hex, factor) {
    const { r, g, b } = hexToRgb(hex);
    const dr = Math.max(0, Math.floor(r * (1 - factor)));
    const dg = Math.max(0, Math.floor(g * (1 - factor)));
    const db = Math.max(0, Math.floor(b * (1 - factor)));
    return `rgb(${dr}, ${dg}, ${db})`;
  }

  function applyTheme(idx) {
    const p = palettes[idx] || palettes[0];
    const root = document.documentElement;
    root.style.setProperty("--accent", p.accent);
    root.style.setProperty("--accent-2", p.accent2 || p.accent);
    // gentle nav background derived from the accent (muted for pastel palettes)
    root.style.setProperty("--nav-bg", darkenHex(p.accent, 0.56));
    const rgb = hexToRgb(p.accent);
    root.style.setProperty("--focus", `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.16)`);
    root.style.setProperty(
      "--page-bg",
      `radial-gradient(circle at 20% 20%, rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.10), transparent 30%), radial-gradient(circle at 80% 0%, rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.06), transparent 28%), #fbfcfe`
    );
    const vibeLabel = document.getElementById("vibeLabel");
    if (vibeLabel) vibeLabel.textContent = p.name;
    localStorage.setItem("vibeTheme", String(idx));
  }

  const stored = Number(localStorage.getItem("vibeTheme"));
  const dailySeed = (new Date()).getUTCDate() + (new Date()).getUTCMonth() * 31;
  const startIdx = Number.isFinite(stored) ? stored % palettes.length : (dailySeed % palettes.length);
  applyTheme(startIdx);

  btn.addEventListener("click", () => {
    const next = ((Number(localStorage.getItem("vibeTheme")) || 0) + 1) % palettes.length;
    applyTheme(next);
  });
})();

(function initSearchHelpers() {
  function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  document.addEventListener('DOMContentLoaded', () => {
    const params = new URLSearchParams(window.location.search);
    const q = (params.get('q') || '').trim();
    const input = document.getElementById('searchInput');

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
    document.querySelectorAll('.title, .text-muted, .meta').forEach(el => {
      const original = el.innerHTML;
      const replaced = original.replace(re, m => `<mark class="search-hit">${m}</mark>`);
      if (replaced !== original) el.innerHTML = replaced;
    });
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
    try { await fetch(`/noti***REMOVED***cations/${id}/read`, { method: "POST" }); } catch (e) {}
    if (url) window.location.href = url;
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
  pasteZone.addEventListener("dragleave", () => pasteZone.classList.remove("paste-zone-hover"));
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

(function initPresence(){
  const el = document.getElementById('presenceList');
  if(!el) return;
  const rid = el.dataset.requestId;
  if(!rid) return;

  async function heartbeat(){
    try { await fetch(`/requests/${rid}/presence`, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } }); } catch(e) {}
  }

  async function refresh(){
    try {
      const r = await fetch(`/requests/${rid}/presence`);
      if(!r.ok) return;
      const data = await r.json();
      const viewers = data.viewers || [];
      if(!viewers.length){
        el.textContent = "No teammates viewing right now.";
        return;
      }
      el.innerHTML = viewers.map(v => `<span class="badge text-bg-light text-dark me-1">${v.email}</span>`).join(' ');
    } catch(e) {}
  }

  heartbeat();
  refresh();
  setInterval(heartbeat, 20000);
  setInterval(refresh, 10000);
})();
