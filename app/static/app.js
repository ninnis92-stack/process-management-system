(function () {
  const ***REMOVED***leInput = document.getElementById("***REMOVED***leInput");
  const pasteZone = document.getElementById("pasteZone");
  const preview = document.getElementById("preview");
  const ***REMOVED***leUiAvailable = Boolean(***REMOVED***leInput && pasteZone && preview);

  const motivationLines = [
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

  function dailySeed() {
    const d = new Date();
    return (d.getUTCFullYear() * 10000) + ((d.getUTCMonth() + 1) * 100) + d.getUTCDate();
  }

  function shuffleWithSeed(list, seed) {
    const arr = [...list];
    let s = seed >>> 0; // force uint32
    for (let i = arr.length - 1; i > 0; i--) {
      s = (s * 1664525 + 1013904223) >>> 0;
      const j = s % (i + 1);
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  // Theme cycling ("Vibe" button)
  const palettes = [
    { name: "Midnight", nav: "#0b1726", accent: "#79c0ff", accent2: "#a78bfa", page: "radial-gradient(circle at 20% 20%, rgba(121,192,255,0.12), transparent 30%), radial-gradient(circle at 80% 0%, rgba(167,139,250,0.12), transparent 28%), #f6f7fb" },
    { name: "Sunrise", nav: "#2b1b2f", accent: "#ffb86c", accent2: "#ff6f91", page: "radial-gradient(circle at 10% 20%, rgba(255,184,108,0.14), transparent 32%), radial-gradient(circle at 90% 10%, rgba(255,111,145,0.12), transparent 30%), #fdf4ff" },
    { name: "Lagoon", nav: "#0f2d2f", accent: "#5ad1c7", accent2: "#4bb4ff", page: "radial-gradient(circle at 15% 15%, rgba(90,209,199,0.14), transparent 32%), radial-gradient(circle at 80% 0%, rgba(75,180,255,0.12), transparent 30%), #f0fbff" },
    { name: "Aurora", nav: "#111826", accent: "#7ef29d", accent2: "#7ad7f0", page: "radial-gradient(circle at 18% 15%, rgba(126,242,157,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(122,215,240,0.12), transparent 28%), #f4f8ff" },
    { name: "Citrus", nav: "#1d2a10", accent: "#c2ff61", accent2: "#ffcf56", page: "radial-gradient(circle at 20% 20%, rgba(194,255,97,0.12), transparent 32%), radial-gradient(circle at 85% 10%, rgba(255,207,86,0.14), transparent 30%), #fbfff2" },
    { name: "Slate", nav: "#11141a", accent: "#9ad0ec", accent2: "#b8c1ff", page: "radial-gradient(circle at 12% 18%, rgba(154,208,236,0.12), transparent 32%), radial-gradient(circle at 88% 12%, rgba(184,193,255,0.12), transparent 30%), #f4f6fb" },
    { name: "Coral", nav: "#2c1a1a", accent: "#ff8a8a", accent2: "#ffc0a8", page: "radial-gradient(circle at 18% 18%, rgba(255,138,138,0.12), transparent 30%), radial-gradient(circle at 80% 10%, rgba(255,192,168,0.12), transparent 28%), #fff6f3" },
    { name: "Mist", nav: "#18212b", accent: "#9fc3e0", accent2: "#b7d5ed", page: "radial-gradient(circle at 16% 18%, rgba(159,195,224,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(183,213,237,0.12), transparent 28%), #f3f6fb" },
    { name: "Sage", nav: "#1c2520", accent: "#b6e3c2", accent2: "#9fd3b4", page: "radial-gradient(circle at 20% 18%, rgba(182,227,194,0.12), transparent 32%), radial-gradient(circle at 78% 6%, rgba(159,211,180,0.12), transparent 28%), #f4fbf4" },
    { name: "Denim", nav: "#112030", accent: "#7fb3ff", accent2: "#a3c7ff", page: "radial-gradient(circle at 18% 20%, rgba(127,179,255,0.12), transparent 30%), radial-gradient(circle at 82% 10%, rgba(163,199,255,0.12), transparent 28%), #f3f7ff" },
    { name: "Blush", nav: "#2a1c24", accent: "#f2b8c6", accent2: "#f8d4d4", page: "radial-gradient(circle at 18% 16%, rgba(242,184,198,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(248,212,212,0.12), transparent 28%), #fff6f8" },
    { name: "Sand", nav: "#222018", accent: "#e7d3a8", accent2: "#d9b97c", page: "radial-gradient(circle at 18% 20%, rgba(231,211,168,0.12), transparent 32%), radial-gradient(circle at 82% 10%, rgba(217,185,124,0.12), transparent 28%), #f9f6ec" },
    { name: "Moss", nav: "#182116", accent: "#a7d477", accent2: "#c7e7a4", page: "radial-gradient(circle at 20% 18%, rgba(167,212,119,0.12), transparent 30%), radial-gradient(circle at 80% 8%, rgba(199,231,164,0.12), transparent 28%), #f3f8ef" },
    { name: "Sky", nav: "#0f1c2a", accent: "#7cc7ff", accent2: "#b3e1ff", page: "radial-gradient(circle at 18% 18%, rgba(124,199,255,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(179,225,255,0.12), transparent 28%), #f2f8ff" },
    { name: "Lilac", nav: "#1c1a2a", accent: "#c5b7ff", accent2: "#e1d7ff", page: "radial-gradient(circle at 18% 16%, rgba(197,183,255,0.12), transparent 30%), radial-gradient(circle at 80% 8%, rgba(225,215,255,0.12), transparent 28%), #f7f5ff" },
    { name: "Teal", nav: "#102124", accent: "#6fd2c1", accent2: "#8ae3d8", page: "radial-gradient(circle at 18% 18%, rgba(111,210,193,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(138,227,216,0.12), transparent 28%), #f1fbf8" },
    { name: "Meadow", nav: "#1a2418", accent: "#b2e39c", accent2: "#d0f5c1", page: "radial-gradient(circle at 18% 18%, rgba(178,227,156,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(208,245,193,0.12), transparent 28%), #f4fbf1" },
    { name: "Dusk", nav: "#1a1f2a", accent: "#a5b8e3", accent2: "#c3d4f5", page: "radial-gradient(circle at 18% 18%, rgba(165,184,227,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(195,212,245,0.12), transparent 28%), #f4f6fb" },
    { name: "Amber", nav: "#2a2116", accent: "#ffc773", accent2: "#ffdba8", page: "radial-gradient(circle at 18% 18%, rgba(255,199,115,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(255,219,168,0.12), transparent 28%), #fdf6eb" },
    { name: "Mint", nav: "#12201c", accent: "#9ff0d0", accent2: "#c5f7e2", page: "radial-gradient(circle at 18% 18%, rgba(159,240,208,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(197,247,226,0.12), transparent 28%), #f1fbf6" },
    { name: "Pewter", nav: "#1a1f24", accent: "#b3c2d6", accent2: "#d6e0ed", page: "radial-gradient(circle at 18% 18%, rgba(179,194,214,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(214,224,237,0.12), transparent 28%), #f5f7fb" },
    { name: "Rosewood", nav: "#2a161a", accent: "#e7a1b0", accent2: "#f3c3cf", page: "radial-gradient(circle at 18% 18%, rgba(231,161,176,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(243,195,207,0.12), transparent 28%), #fff5f7" },
    { name: "Glacier", nav: "#0f1b23", accent: "#9ad7f2", accent2: "#c0e8ff", page: "radial-gradient(circle at 18% 18%, rgba(154,215,242,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(192,232,255,0.12), transparent 28%), #f2f8fc" },
    { name: "Seaside", nav: "#13212c", accent: "#7bd1f1", accent2: "#9fe0ff", page: "radial-gradient(circle at 18% 18%, rgba(123,209,241,0.12), transparent 30%), radial-gradient(circle at 82% 8%, rgba(159,224,255,0.12), transparent 28%), #f1f8fc" },
  ];

  function applyTheme(idx){
    const p = palettes[idx] || palettes[0];
    const root = document.documentElement;
    root.style.setProperty('--nav-bg', p.nav);
    root.style.setProperty('--nav-text', '#eef2f7');
    root.style.setProperty('--accent', p.accent);
    root.style.setProperty('--accent-2', p.accent2);
    root.style.setProperty('--page-bg', p.page);
    const btn = document.getElementById('vibeBtn');
    if(btn) btn.textContent = `Vibe · ${p.name}`;
    localStorage.setItem('vibeTheme', String(idx));
  }

  function initTheme(){
    const stored = Number(localStorage.getItem('vibeTheme'));
    const idx = Number.isFinite(stored) ? stored % palettes.length : 0;
    applyTheme(idx);
    const btn = document.getElementById('vibeBtn');
    if(btn){
      btn.addEventListener('click', () => {
        const next = (Number(localStorage.getItem('vibeTheme')) + 1) % palettes.length;
        applyTheme(next);
      });
    }
  }

  function initMotivation(){
    const slot = document.getElementById('motivation');
    if(!slot || !motivationLines.length) return;

    const todayLines = shuffleWithSeed(motivationLines, dailySeed());
    let idx = Math.floor(Math.random() * todayLines.length);
    slot.textContent = todayLines[idx];
    slot.style.opacity = 1;
    slot.style.transform = "translateY(0)";

    setInterval(() => {
      slot.style.opacity = 0;
      slot.style.transform = "translateY(-6px)";
      setTimeout(() => {
        idx = (idx + 1) % todayLines.length;
        slot.textContent = todayLines[idx];
        slot.style.transform = "translateY(6px)";
        // allow browser to apply new transform before fading in
        requestAnimationFrame(() => {
          slot.style.opacity = 1;
          slot.style.transform = "translateY(0)";
        });
      }, 180);
    }, 8000);
  }

  function initPresence(){
    const el = document.getElementById('presenceList');
    if(!el) return;
    const rid = el.dataset.requestId;
    if(!rid) return;

    async function heartbeat(){
      try { await fetch(`/requests/${rid}/presence`, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } }); } catch(e){ /* ignore */ }
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
      } catch(e){ /* ignore */ }
    }

    heartbeat();
    refresh();
    setInterval(heartbeat, 20000);
    setInterval(refresh, 10000);
  }

  if (***REMOVED***leUiAvailable) {
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
  }

    async function refreshNoti***REMOVED***cations(){
    const r = await fetch("/noti***REMOVED***cations/unread_count");
    if(!r.ok) return;
    const data = await r.json();
    const badge = document.getElementById("notifBadge");
    if(data.count > 0){
        badge.style.display = "inline-block";
        badge.textContent = data.count;
    } else {
        badge.style.display = "none";
    }
    }

    async function loadLatest(){
    const r = await fetch("/noti***REMOVED***cations/latest");
    if(!r.ok) return;
    const items = await r.json();
    const list = document.getElementById("notifList");
    // render each item as a clickable block with data attributes
    list.innerHTML = items.map(n => `
      <div class="border rounded p-2 mb-2 notif-item ${n.is_read ? "opacity-75" : ""}" data-id="${n.id}" data-url="${n.url || ''}">
        <div><strong>${n.title}</strong></div>
        ${n.body ? `<div>${n.body}</div>` : ""}
        ${n.url ? `<div class="small text-primary">Open</div>` : ""}
      </div>
    `).join("") || "<div class='text-muted'>No noti***REMOVED***cations.</div>";
    }

    document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("notifBtn");
    const dd = document.getElementById("notifDropdown");
    if(btn && dd){
      btn.addEventListener("click", async () => {
      dd.classList.toggle('open');
      btn.classList.toggle('open', dd.classList.contains('open'));
      await loadLatest();
      });
      // close when clicking outside
      document.addEventListener('click', (ev) => {
        if(!dd.contains(ev.target) && !btn.contains(ev.target)){
          dd.classList.remove('open');
          btn.classList.remove('open');
        }
      });
    }
    // handle clicks on noti***REMOVED***cation items (mark read then navigate)
    const notifList = document.getElementById('notifList');
    if(notifList){
      notifList.addEventListener('click', async (ev) => {
        const item = ev.target.closest('.notif-item');
        if(!item) return;
        const nid = item.dataset.id;
        const dest = item.dataset.url;
        if(nid){
          try{
            await fetch(`/noti***REMOVED***cations/${nid}/read`, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
          }catch(e){ /* ignore */ }
        }
        if(dest){
          // allow normal navigation
          window.location.href = dest;
        }
      });
    }
    refreshNoti***REMOVED***cations();
    setInterval(refreshNoti***REMOVED***cations, 15000);
      initTheme();
      initMotivation();
      initPresence();
    });
})();