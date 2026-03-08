(function initMotivation() {
  const slot = document.getElementById("motivation");
  if (!slot) return;

  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // Read server-provided rolling quotes from the JSON script tag if present.
  try {
    const el = document.getElementById('rolling-quotes-data');
    if (el && el.textContent) {
      try {
        const parsed = JSON.parse(el.textContent || '[]');
        if (Array.isArray(parsed) && parsed.length) window.ROLLING_QUOTES = parsed;
      } catch (e) { /* ignore parse errors */ }
    }
  } catch (e) {}
  // Prefer server-injected rolling quotes; fall back to built-in lines.
  let lines = (window && window.ROLLING_QUOTES && Array.isArray(window.ROLLING_QUOTES)) ? window.ROLLING_QUOTES.slice() : [
    "Sort today: socks first, worries later.",
    "A folded stack is a small victory.",
    "One load at a time, one win at a time.",
    "Tackle the smallest basket first.",
    "Fresh socks, fresh perspective.",
    "Turn laundry into a tiny ritual of calm.",
    "Don't wait for motivation—start the wash.",
    "Clean clothes, clearer head.",
    "Fold with intention; carry less chaos.",
    "A warm dryer is a hug for your clothes.",
    "Separate colors, not your priorities.",
    "Make today productive—finish one load.",
    "Every matched pair is progress.",
    "Treat stains as experiments, not failures.",
    "Declutter your closet, declutter your day.",
    "A neat drawer frees mental space.",
    "Air-dry patience; speed comes after practice.",
    "Small care preserves the longest wear.",
    "Refresh your routine with a fresh load.",
    "Laundry fi is peace earned.",
    "Celebrate a completed basket.",
    "Put it away; let it be finished.",
    "Socks find their way home eventually.",
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
      ], { duration: 200, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards' });
      out.onfinish = () => {
        idx = nextIdx;
        slot.textContent = order[idx];
        // animate in
        const _in = slot.animate([
          { opacity: 0, transform: 'translateY(8px)' },
          { opacity: 1, transform: 'translateY(0)' }
        ], { duration: 260, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards' });
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

/* Safe modal wrapper: prevents busted modals from leaving a blocking backdrop.
   - Appends modal elements to document.body before showing (avoids z-index/sandbox issues)
   - Wraps show/hide in try/catch and removes stray backdrops on failure
   - Adds a global `safeShowModal(id, opts)` helper for templates/scripts to call
*/
(function installSafeModalWrapper(){
  function localCleanup(){
    try{
      document.querySelectorAll('.modal-backdrop').forEach(b=>b.remove());
      document.querySelectorAll('.modal').forEach(m=>{ m.classList.remove('show'); m.style.display='none'; m.setAttribute('aria-hidden','true'); });
      document.body.classList.remove('modal-open');
      document.body.style.paddingRight = '';
    }catch(e){ console.warn('localCleanup error', e); }
  }

  if(window.bootstrap && bootstrap.Modal && bootstrap.Modal.prototype){
    try{
      const proto = bootstrap.Modal.prototype;
      const _show = proto.show;
      const _hide = proto.hide;

      proto.show = function(){
        try{
          if(this._element && this._element.parentNode !== document.body){
            document.body.appendChild(this._element);
          }
          return _show.apply(this, arguments);
        }catch(e){
          console.warn('bootstrap.Modal.show failed', e);
          localCleanup();
        }
      };

      proto.hide = function(){
        try{ return _hide.apply(this, arguments); }catch(e){ console.warn('bootstrap.Modal.hide failed', e); localCleanup(); }
      };
    }catch(e){ console.warn('installSafeModalWrapper error', e); }
  }

  // helper for code that wants to show a modal safely by id
  window.safeShowModal = function(id, opts){
    try{
      const el = document.getElementById(id);
      if(!el) return console.warn('safeShowModal: element not found', id);
      if(el.parentNode !== document.body) document.body.appendChild(el);
      if(window.bootstrap && bootstrap.Modal){
        const m = new bootstrap.Modal(el, opts || {});
        try{ m.show(); }catch(e){ console.warn('safeShowModal show failed', e); localCleanup(); }
        return m;
      } else {
        // fallback: reveal the element without backdrop
        el.style.display = 'block'; el.classList.add('show'); el.removeAttribute('aria-hidden');
        return null;
      }
    }catch(e){ console.warn('safeShowModal error', e); }
  };
})();

(function initHandoffHint(){
  document.addEventListener('DOMContentLoaded', function(){
    try{
      // Prefer explicit global injected variable, but fall back to reading
      // the hidden data container injected in templates (#handoffTargetsData)
      let handoffTargets = [];
      if (Array.isArray(window.HANDOFF_TARGETS)) {
        handoffTargets = window.HANDOFF_TARGETS;
      } else {
        const container = document.getElementById('handoffTargetsData');
        if (container && container.dataset && container.dataset.targets) {
          try { handoffTargets = JSON.parse(container.dataset.targets); } catch (e) { handoffTargets = []; }
        }
      }
      const hintEl = document.getElementById('handoffHint');
      if(!hintEl) return;
      const select = document.getElementById('toStatusSelect') || document.querySelector('select[name="to_status"]');
      if(!select) return;

      function updateHint(){
        const val = select.value;
        if(Array.isArray(handoffTargets) && handoffTargets.indexOf(val) !== -1){
          hintEl.classList.remove('d-none');
        } else {
          hintEl.classList.add('d-none');
        }
      }

      select.addEventListener('change', updateHint);
      // initial
      updateHint();
    }catch(e){ console.warn('initHandoffHint error', e); }
  });
})();

(function initDeptMiniWindow(){
  // Provides a small interactive iframe in admin monitor to load internal pages for debugging.
  const urlInput = document.getElementById('miniUrl');
  const loadBtn = document.getElementById('miniLoad');
  const refreshBtn = document.getElementById('miniRefresh');
  const openBtn = document.getElementById('miniOpen');
  const iframe = document.getElementById('deptMiniWin');
  if(!iframe || !urlInput) return;

  function normalizePath(v){
    v = (v||'').trim();
    if(!v) return '/dashboard';
    // If value looks like a path (starts with /) keep it; else, try to treat it as absolute URL
    return v.startsWith('/') ? v : v;
  }

  if(loadBtn){
    loadBtn.addEventListener('click', (e)=>{
      e.preventDefault();
      iframe.src = normalizePath(urlInput.value);
    });
  }

  if(refreshBtn){
    refreshBtn.addEventListener('click', (e)=>{ e.preventDefault(); iframe.contentWindow.location.reload(); });
  }

  if(openBtn){
    openBtn.addEventListener('click', (e)=>{ e.preventDefault(); const href = normalizePath(urlInput.value); window.open(href, '_blank'); });
  }

  const openDebug = document.getElementById('miniOpenDebug');
  if(openDebug){
    openDebug.addEventListener('click', (e)=>{
      e.preventDefault();
      const path = encodeURIComponent(normalizePath(urlInput.value));
      // Open the admin debug workspace which embeds the path and provides guidance for isolation
      window.open(`/admin/debug_workspace?path=${path}`, '_blank', 'noopener');
    });
  }

  // Protect the iframe by disabling state-changing actions inside it (fetch/XHR/form submissions).
  function attachIframeProtector(iframeEl){
    try{
      const doc = iframeEl.contentDocument || iframeEl.contentWindow.document;
      if(!doc) return;
      // Inject a small script into the iframe to override fetch/XHR and prevent non-GET form submits.
      const protector = doc.createElement('script');
      protector.type = 'text/javascript';
      protector.textContent = `
        (function(){
          try{
            // Override fetch: block non-GET/HEAD methods
            const _fetch = window.fetch;
            window.fetch = function(input, init){ init = init || {}; const method = (init.method || 'GET').toUpperCase(); if(method !== 'GET' && method !== 'HEAD'){ console.warn('Blocked fetch with method', method); return Promise.resolve(new Response(null,{status:405,statusText:'Method Not Allowed'})); } return _fetch.call(this, input, init); };

            // Override XMLHttpRequest to prevent non-GET sends
            const OrigXHR = window.XMLHttpRequest;
            function XHR(){
              const rx = new OrigXHR();
              const origOpen = rx.open;
              let _method = 'GET';
              rx.open = function(m, url, async){ _method = (m || 'GET').toUpperCase(); return origOpen.apply(this, arguments); };
              const origSend = rx.send;
              rx.send = function(body){ if(_method !== 'GET' && _method !== 'HEAD'){ try{ this.abort(); }catch(e){} console.warn('Blocked XHR with method', _method); return; } return origSend.apply(this, arguments); };
              return rx;
            }
            window.XMLHttpRequest = XHR;

            // Prevent form submissions that would change state
            document.addEventListener('submit', function(ev){ try{ const f = ev.target; const m = (f.method || 'GET').toUpperCase(); if(m !== 'GET' && m !== 'HEAD'){ ev.preventDefault(); ev.stopImmediatePropagation(); alert('Form submissions are disabled in the debug mini-window to prevent data changes. Use the Debug Workspace in an isolated session for live edits.'); } }catch(e){} }, true);

            // Prevent link clicks that use data-method or are intended as actions (common patterns)
            document.addEventListener('click', function(ev){ try{ const a = ev.target.closest && ev.target.closest('a'); if(a){ const method = a.getAttribute('data-method') || a.getAttribute('data-action'); if(method){ ev.preventDefault(); alert('Action links are disabled in the debug mini-window to prevent data changes.'); } } }catch(e){} }, true);
          }catch(e){}
        })();
      `;
      doc.documentElement.appendChild(protector);
    }catch(e){
      // Could not inject (maybe cross-origin); in that case fall back to sandbox restrictions
      console.warn('Could not attach iframe protector:', e);
      try{ iframeEl.sandbox = iframeEl.sandbox.replace('allow-forms','').replace('allow-scripts',''); }catch(err){}
    }
  }

  // Attach protector on initial load and whenever the iframe navigates
  iframe.addEventListener('load', ()=>{ try{ attachIframeProtector(iframe); }catch(e){} });

  // If admin monitor dept quick links are clicked, update the mini window
  document.querySelectorAll('a[href^="?dept="]').forEach(a=>{
    a.addEventListener('click', (ev)=>{
      try{ const q = new URL(a.href, window.location.href); const dept = q.searchParams.get('dept'); if(dept){ const src = `/dashboard?dept=${dept}`; iframe.src = src; if(urlInput) urlInput.value = src; } }catch(e){}
    });
  });
})();

(function initTemplateVerificationPrefill(){
  document.addEventListener('DOMContentLoaded', function(){
    const form = document.querySelector('form[data-template-prefill-endpoint]');
    if(!form) return;

    const endpoint = form.dataset.templatePrefillEndpoint;
    if(!endpoint) return;

    const specEl = document.getElementById('template-spec-data');
    if(!specEl || !specEl.textContent) return;

    let fields = [];
    try {
      fields = JSON.parse(specEl.textContent || '[]');
    } catch (e) {
      console.warn('Could not parse template spec for prefill', e);
      return;
    }
    if(!Array.isArray(fields) || !fields.length) return;

    const setStatus = (fieldName, message, tone) => {
      const slot = form.querySelector(`[data-field-status-for="${fieldName}"]`);
      if(!slot) return;
      slot.textContent = message || '';
      slot.classList.remove('is-success', 'is-warning', 'is-loading');
      if(tone === 'success') slot.classList.add('is-success');
      if(tone === 'warning') slot.classList.add('is-warning');
      if(tone === 'loading') slot.classList.add('is-loading');
    };

    const collectValues = () => {
      const formData = new FormData(form);
      const values = {};
      formData.forEach((value, key) => {
        if(typeof value === 'string') values[key] = value;
      });
      return values;
    };

    const applyPrefills = (meta, prefills) => {
      Object.entries(prefills || {}).forEach(([targetField, value]) => {
        const input = form.querySelector(`[name="${targetField}"]`);
        if(!input) return;
        const targetMeta = (meta || {})[targetField] || {};
        if(input.value && !targetMeta.overwrite) return;
        input.value = value == null ? '' : String(value);
        input.dispatchEvent(new Event('change', { bubbles: true }));
      });
    };

    const wireField = (field) => {
      const verification = field && field.verification;
      if(!verification || !verification.prefill_enabled) return;

      const input = form.querySelector(`[name="${field.name}"]`);
      if(!input) return;

      const eventName = verification.prefill_trigger === 'change' || input.tagName === 'SELECT'
        ? 'change'
        : 'blur';

      let inFlight = false;
      input.addEventListener(eventName, async () => {
        const value = (input.value || '').trim();
        if(!value || inFlight) {
          if(!value) setStatus(field.name, '', null);
          return;
        }

        inFlight = true;
        setStatus(field.name, 'Verifying and checking linked fields…', 'loading');

        try {
          const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json'
            },
            body: JSON.stringify({
              field_name: field.name,
              value,
              values: collectValues()
            })
          });

          let payload = {};
          try {
            payload = await response.json();
          } catch (e) {
            payload = {};
          }

          if(!response.ok || payload.ok === false) {
            setStatus(field.name, 'Linked auto-fill is unavailable for this field right now.', 'warning');
            return;
          }

          const result = payload.result || {};
          const prefills = payload.prefills || {};
          const appliedCount = Object.keys(prefills).length;

          if(result.ok === true && appliedCount > 0) {
            applyPrefills(payload.meta, prefills);
            setStatus(
              field.name,
              `Verified successfully and updated ${appliedCount} linked field${appliedCount === 1 ? '' : 's'}.`,
              'success'
            );
            return;
          }

          if(result.ok === true) {
            setStatus(field.name, 'Verified successfully. No linked fields needed updates.', 'success');
            return;
          }

          if(result.ok === false) {
            setStatus(field.name, 'Verification did not return a valid match, so linked fields were not updated.', 'warning');
            return;
          }

          setStatus(field.name, '', null);
        } catch (e) {
          console.warn('Template verification prefill failed', e);
          setStatus(field.name, 'Linked auto-fill could not complete.', 'warning');
        } finally {
          inFlight = false;
        }
      });
    };

    fields.forEach(wireField);
  });
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
  const deptVibeBtn = document.getElementById('vibeBtnDept');

  // 24 pastel / muted palettes that are easy on the eyes (accent = primary, accent2 = softer shade)
  const palettes = [
    { name: "Soft Coral", theme: "Cozy Coral", accent: "#E47D6A", accent2: "#F5E9E6" },
    { name: "Warm Sand", theme: "Warm Morning", accent: "#DDB892", accent2: "#FAF5EE" },
    { name: "Moss", theme: "Quiet Grove", accent: "#A7C28C", accent2: "#F0F7ED" },
    { name: "Sage", theme: "Sage Retreat", accent: "#8FA98A", accent2: "#EFF6EE" },
    { name: "Muted Teal", theme: "Calm Teal", accent: "#6FB1B1", accent2: "#EDF7F7" },
    { name: "Sky", theme: "Clear Sky", accent: "#7FB3D5", accent2: "#EFF8FC" },
    { name: "Powder Blue", theme: "Soft Powder", accent: "#9FC6E7", accent2: "#F6FBFF" },
    { name: "Lavender", theme: "Lavender Dream", accent: "#B9A7E0", accent2: "#F6F3FB" },
    { name: "Lilac", theme: "Lilac Haze", accent: "#C7B3D6", accent2: "#FBF8FD" },
    { name: "Muted Pink", theme: "Blush", accent: "#E8B7C8", accent2: "#FFF5F8" },
    { name: "Peach", theme: "Peach Sunrise", accent: "#F2B091", accent2: "#FFF6F2" },
    { name: "Butter", theme: "Buttercream", accent: "#F4D58D", accent2: "#FFFDF2" },
    { name: "Pistachio", theme: "Pistachio Grove", accent: "#D6E8C3", accent2: "#FBFDF4" },
    { name: "Mint", theme: "Fresh Mint", accent: "#BFEAD6", accent2: "#F9FFFB" },
    { name: "Seafoam", theme: "Seafoam Breeze", accent: "#9EE3C5", accent2: "#F7FFF6" },
    { name: "Aqua", theme: "Aqua Calm", accent: "#8ED6D1", accent2: "#F4FFFE" },
    { name: "Robin Egg", theme: "Robin's Dawn", accent: "#8EC7E6", accent2: "#F5FDFF" },
    { name: "Periwinkle", theme: "Periwinkle Morning", accent: "#B2C8F9", accent2: "#F8FBFF" },
    { name: "Dusty Blue", theme: "Dusty Blue", accent: "#9BB1C8", accent2: "#F6F9FB" },
    { name: "Slate Rose", theme: "Slate Rose", accent: "#C9A6A6", accent2: "#FBF6F6" },
    { name: "Tea", theme: "Tea Garden", accent: "#C9D6B3", accent2: "#FBFDF4" },
    { name: "Stone", theme: "Stone Whisper", accent: "#BFC8C6", accent2: "#F7F9F9" },
    { name: "Soft Gray", theme: "Soft Gray", accent: "#BDC3C7", accent2: "#FAFBFC" },
    { name: "Charcoal Mist", theme: "Charcoal Mist", accent: "#93A0A8", accent2: "#F1F5F6" },
    { name: "Aurora", theme: "Aurora", accent: "#0F766E", accent2: "#E6FAF8" }
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

  function mixHex(hexA, hexB, weightA) {
    const a = hexToRgb(hexA);
    const b = hexToRgb(hexB);
    const wa = Math.max(0, Math.min(1, weightA));
    const wb = 1 - wa;
    return `rgb(${Math.round(a.r * wa + b.r * wb)}, ${Math.round(a.g * wa + b.g * wb)}, ${Math.round(a.b * wa + b.b * wb)})`;
  }

  function isDarkModeEnabled() {
    return document.body.classList.contains('dark-mode');
  }

  function applyTheme(idx) {
    const p = palettes[idx] || palettes[0];
    const root = document.documentElement;
    const rgb = hexToRgb(p.accent);
    const darkMode = isDarkModeEnabled();

    root.style.setProperty("--accent", p.accent);
    root.style.setProperty(
      "--accent-2",
      darkMode ? mixHex(p.accent, "#ffffff", 0.35) : (p.accent2 || p.accent)
    );

    if (darkMode) {
      root.style.setProperty("--nav-bg", mixHex(p.accent, "#202124", 0.18));
      root.style.setProperty("--surface", mixHex(p.accent, "#1e1e1e", 0.10));
      root.style.setProperty("--border", `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.22)`);
      root.style.setProperty("--focus", `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.28)`);
      root.style.setProperty(
        "--page-bg",
        `radial-gradient(circle at 20% 20%, rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.18), transparent 30%), radial-gradient(circle at 80% 0%, rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.12), transparent 28%), #121212`
      );
    } else {
      root.style.setProperty("--nav-bg", darkenHex(p.accent, 0.56));
      root.style.setProperty("--surface", "#ffffff");
      root.style.setProperty("--border", "#e6e9ee");
      root.style.setProperty("--focus", `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.16)`);
      root.style.setProperty(
        "--page-bg",
        `radial-gradient(circle at 20% 20%, rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.10), transparent 30%), radial-gradient(circle at 80% 0%, rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.06), transparent 28%), #fbfcfe`
      );
    }

    // Update any visible vibe labels (global and department-facing)
    const vibeLabels = document.querySelectorAll('.vibeLabel, #vibeLabel');
    vibeLabels.forEach(el => { try { el.textContent = (p.theme || p.name); } catch(e){} });
    localStorage.setItem("vibeTheme", String(idx));
    // If user is logged in, persist preference server-side
    try{
      if(isUserLoggedIn()){
        fetch('/auth/vibe', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ vibe_index: idx }) }).catch(()=>{});
      }
    }catch(e){}
  }
  // If page opts out of vibe (no-vibe class), skip theme application
  if(document.body.classList.contains('no-vibe')) return;

  function isUserLoggedIn() {
    if (typeof window.USER_LOGGED_IN !== 'undefined') return !!window.USER_LOGGED_IN;
    return document.body.dataset.userLoggedIn === '1';
  }

  function getUserVibeIndex() {
    if (typeof window.USER_VIBE_INDEX !== 'undefined' && window.USER_VIBE_INDEX !== null) return Number(window.USER_VIBE_INDEX);
    if (typeof document.body.dataset.userVibe !== 'undefined' && document.body.dataset.userVibe !== '') return Number(document.body.dataset.userVibe);
    return null;
  }

  const userVibe = getUserVibeIndex();
  const stored = (userVibe !== null && !Number.isNaN(userVibe)) ? userVibe : Number(localStorage.getItem("vibeTheme"));
  const dailySeed = (new Date()).getUTCDate() + (new Date()).getUTCMonth() * 31;
  const startIdx = Number.isFinite(stored) ? stored % palettes.length : (dailySeed % palettes.length);
  applyTheme(startIdx);

  // Attach click handlers to whichever vibe buttons are present (global navbar and/or department view)
  function advanceVibe() {
    const next = ((Number(localStorage.getItem("vibeTheme")) || 0) + 1) % palettes.length;
    applyTheme(next);
  }

  if (btn) btn.addEventListener("click", advanceVibe);
  if (deptVibeBtn) deptVibeBtn.addEventListener('click', (e) => { e.preventDefault(); advanceVibe(); });
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

(function initNotifications() {
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
      const r = await fetch("/notifications/unread_count");
      if (!r.ok) {
        badge.style.display = "none";
        if (momentum) momentum.textContent = "Unable to fetch notifications.";
        setActive(false);
        return;
      }
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
      list.innerHTML = "<div class='text-muted'>Unable to load notifications right now.</div>";
    }
  }

  async function loadLatest() {
    list.innerHTML = "<div class='text-muted'>Loading…</div>";
    try {
      const r = await fetch("/notifications/latest");
      if (!r.ok) {
        try {
          const txt = await r.text();
          console.warn('notifications/latest non-ok response', r.status, txt);
        } catch (e) { /* ignore */ }
        list.innerHTML = "<div class='text-muted'>Unable to load notifications right now.</div>";
        return;
      }
      const items = await r.json();
      list.innerHTML = items.map(n => `
        <div class="border rounded p-2 mb-2 notif-item ${n.is_read ? "opacity-75" : ""}" data-id="${n.id}" data-url="${n.url || ''}">
          <div><strong>${n.title}</strong></div>
          ${n.body ? `<div>${n.body}</div>` : ""}
          ${n.url ? `<div class="small text-primary">Open</div>` : ""}
        </div>
      `).join("") || "<div class='text-muted'>No notifications.</div>";
    } catch (e) {
      list.innerHTML = "<div class='text-muted'>Unable to load notifications right now.</div>";
    }
  }

  list.addEventListener("click", async (ev) => {
    const item = ev.target.closest(".notif-item");
    if (!item) return;
    const id = item.dataset.id;
    const url = item.dataset.url;
    try { await fetch(`/notifications/${id}/read`, { method: "POST" }); } catch (e) {}
    if (url) window.location.href = url;
  });

  btn.addEventListener("click", async () => {
    const willOpen = !dd.classList.contains("open");
    dd.classList.toggle("open", willOpen);
    btn.classList.toggle("open", willOpen);
    if (willOpen) {
      await loadLatest();
      // Mark all as read when the user clicks to check their notifications
      try{
        await fetch('/notifications/mark_all_read', { method: 'POST' });
        badge.style.display = 'none';
        setActive(false);
      }catch(e){ console.warn('mark_all_read failed', e); }
      // Refresh server count in background
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

// Attach handler for the 'Requires Executive Approval' button if present
document.addEventListener('DOMContentLoaded', function(){
  try{
    const btn = document.getElementById('execApprovalBtn');
    if(!btn) return;
    btn.addEventListener('click', function(){
      try{
        // Set the to_status select to EXEC_APPROVAL if present
        const select = document.getElementById('toStatusSelect') || document.querySelector('select[name="to_status"]');
        if(select){
          // Try to set to EXEC_APPROVAL if available, otherwise set to SENT_TO_A
          const execOption = Array.from(select.options).find(o => o.value === 'EXEC_APPROVAL');
          const sendOption = Array.from(select.options).find(o => o.value === 'SENT_TO_A');
          if(execOption) select.value = 'EXEC_APPROVAL';
          else if(sendOption) select.value = 'SENT_TO_A';
        }
        // set hidden field to indicate immediate send to A
        const hidden = document.getElementById('forceSendToA') || document.querySelector('input[name="force_send_to_a"]');
        if(hidden) hidden.value = '1';
        // submit the form
        const form = btn.closest('form');
        if(form) form.submit();
      }catch(e){ console.warn('execApprovalBtn click failed', e); }
    });
  }catch(e){ console.warn('execApprovalBtn init failed', e); }
});

(function initFilePreview() {
  const fileInput = document.getElementById("fileInput");
  const pasteZone = document.getElementById("pasteZone");
  const preview = document.getElementById("preview");
  if (!fileInput || !pasteZone || !preview) return;

  const dt = new DataTransfer();

  function refreshPreview() {
    preview.innerHTML = "";
    for (const file of dt.files) {
      const img = document.createElement("img");
      img.className = "preview-img";
      img.alt = file.name;
      img.src = URL.createObjectURL(file);
      preview.appendChild(img);
    }
    fileInput.files = dt.files;
  }

  function addFile(file) {
    if (!file.type.startsWith("image/")) return;
    dt.items.add(file);
    refreshPreview();
  }

  pasteZone.addEventListener("click", () => pasteZone.focus());
  pasteZone.setAttribute("tabindex", "0");

  pasteZone.addEventListener("paste", (e) => {
    const items = e.clipboardData?.items || [];
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) addFile(file);
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
    const files = e.dataTransfer?.files || [];
    for (const f of files) addFile(f);
  });

  fileInput.addEventListener("change", () => {
    dt.items.clear();
    for (const f of fileInput.files) addFile(f);
  });
})();

// Screenshot uploader (drag & drop + preview) for the request detail page
(function initScreenshotUploader(){
  document.addEventListener('DOMContentLoaded', function(){
    try{
      const fileInput = document.getElementById('screenshotFileInput');
      const dropZone = document.getElementById('screenshotDropZone');
      const preview = document.getElementById('screenshotPreview');
      if(!fileInput || !dropZone || !preview) return;

      const dt = new DataTransfer();

      function refreshPreview(){
        preview.innerHTML = '';
        for(const file of dt.files){
          const img = document.createElement('img');
          img.className = 'preview-img';
          img.alt = file.name;
          img.src = URL.createObjectURL(file);
          preview.appendChild(img);
        }
        fileInput.files = dt.files;
      }

      function addFile(file){
        if(!file.type.startsWith('image/')) return;
        dt.items.add(file);
        refreshPreview();
      }

      dropZone.addEventListener('click', ()=> fileInput.click());
      dropZone.addEventListener('dragover', (e)=>{ e.preventDefault(); dropZone.classList.add('paste-zone-hover'); });
      dropZone.addEventListener('dragleave', ()=> dropZone.classList.remove('paste-zone-hover'));
      dropZone.addEventListener('drop', (e)=>{
        e.preventDefault(); dropZone.classList.remove('paste-zone-hover');
        const files = e.dataTransfer?.files || [];
        for(const f of files) addFile(f);
        // show confirm modal with previews and submit on confirmation
        try{
          const confirmPreview = document.getElementById('screenshotConfirmPreview');
          if(confirmPreview){
            confirmPreview.innerHTML = '';
            for(const file of dt.files){
              const img = document.createElement('img');
              img.className = 'preview-img'; img.alt = file.name; img.src = URL.createObjectURL(file);
              confirmPreview.appendChild(img);
            }
          }
          if(typeof safeShowModal === 'function'){
            safeShowModal('screenshotConfirmModal');
          } else {
            var m = new bootstrap.Modal(document.getElementById('screenshotConfirmModal'));
            m.show();
          }
        }catch(e){ console.warn('show confirm modal failed', e); }
      });

      fileInput.addEventListener('change', ()=>{
        for(const f of fileInput.files) addFile(f);
      });

      // Wire confirm/cancel handlers for the confirm modal
      const confirmBtn = document.getElementById('confirmScreenshotUploadBtn');
      const cancelBtn = document.getElementById('cancelScreenshotUploadBtn');
      const confirmModalEl = document.getElementById('screenshotConfirmModal');
      function clearDt(){
        while(dt.items.length) dt.items.remove(0);
        refreshPreview();
      }
      if(confirmBtn){
        confirmBtn.addEventListener('click', function(){
          try{
            // submit the closest form
            const form = fileInput.closest('form');
            if(form) form.submit();
          }catch(e){ console.warn('confirm upload failed', e); }
        });
      }
      if(cancelBtn){
        cancelBtn.addEventListener('click', function(){
          try{ clearDt(); if(confirmModalEl){ /* ensure modal is hidden */ if(typeof bootstrap !== 'undefined' && bootstrap.Modal){ const inst = bootstrap.Modal.getInstance(confirmModalEl); if(inst) inst.hide(); } } }catch(e){}
        });
      }

    }catch(e){ console.warn('initScreenshotUploader error', e); }
  });
})();

// Monitor transition select and require screenshot when sending from A -> B
(function monitorTransitionScreenshotRequirement(){
  document.addEventListener('DOMContentLoaded', function(){
    try{
      const select = document.getElementById('toStatusSelect') || document.querySelector('select[name="to_status"]');
      if(!select) return;
      const form = select.closest('form');
      if(!form) return;
      const applyBtn = form.querySelector('button[type="submit"]') || form.querySelector('button');
      const hint = document.createElement('div');
      hint.id = 'screenshotRequiredHint';
      hint.className = 'text-danger small mt-2 d-none';
      hint.textContent = 'A screenshot is required to send this request back to Department B.';
      applyBtn.parentNode.insertBefore(hint, applyBtn.nextSibling);

      function hasScreenshotAvailable(){
        try{
          const meta = document.getElementById('screenshotMeta');
          const existing = meta ? Number(meta.dataset.count || 0) : 0;
          const input = document.getElementById('screenshotFileInput');
          const staged = input && input.files ? input.files.length : 0;
          return (existing + staged) > 0;
        }catch(e){ return false; }
      }

      function update(){
        try{
          // Determine whether the selected status requires a screenshot.
          const selected = String(select.value);
          const statusRequires = window.STATUS_OPTIONS && window.STATUS_OPTIONS[selected];
          // For backward-compat, only enforce when selecting the status that sends back to Dept B (legacy behavior)
          const sendingBackToB = selected === 'B_IN_PROGRESS';
          const requires = Boolean(statusRequires && sendingBackToB);
          if(requires && !hasScreenshotAvailable()){
            applyBtn.disabled = true;
            hint.classList.remove('d-none');
          } else {
            applyBtn.disabled = false;
            hint.classList.add('d-none');
          }
        }catch(e){ }
      }

      select.addEventListener('change', update);
      // Also watch screenshot file input changes to re-evaluate
      const screenshotInput = document.getElementById('screenshotFileInput');
      if(screenshotInput) screenshotInput.addEventListener('change', update);
      // Initial update
      update();
    }catch(e){ console.warn('monitorTransitionScreenshotRequirement error', e); }
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
