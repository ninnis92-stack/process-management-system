function initThemeEngine() {
  if (window.__themeModuleLoaded) return;
  window.__themeModuleLoaded = true;

  const vibeButtons = Array.from(
    document.querySelectorAll('#vibeBtn, #vibeBtnDept, #vibeBtnAdmin, [data-vibe-trigger]')
  );
  const vibeShells = Array.from(document.querySelectorAll('[data-vibe-shell]'));
  const vibeControlPanels = Array.from(document.querySelectorAll('[data-vibe-control-panel]'));
  const quotePanels = Array.from(document.querySelectorAll('[data-vibe-quote-panel]'));
  const themeBanners = Array.from(document.querySelectorAll('[data-theme-banner]'));
  const themeManagedProps = [
    '--accent', '--accent-rgb', '--accent-2', '--nav-bg', '--nav-text', '--body-text',
    '--surface', '--surface-2', '--surface-3', '--border', '--focus', '--banner-bg',
    '--banner-border', '--banner-shadow', '--page-bg'
  ];

  const palettes = [
    { name: 'Soft Coral', theme: 'Cozy Coral', accent: '#E47D6A', accent2: '#F5E9E6' },
    { name: 'Warm Sand', theme: 'Warm Morning', accent: '#DDB892', accent2: '#FAF5EE' },
    { name: 'Moss', theme: 'Quiet Grove', accent: '#A7C28C', accent2: '#F0F7ED' },
    { name: 'Sage', theme: 'Sage Retreat', accent: '#8FA98A', accent2: '#EFF6EE' },
    { name: 'Muted Teal', theme: 'Calm Teal', accent: '#6FB1B1', accent2: '#EDF7F7' },
    { name: 'Sky', theme: 'Clear Sky', accent: '#7FB3D5', accent2: '#EFF8FC' },
    { name: 'Powder Blue', theme: 'Soft Powder', accent: '#9FC6E7', accent2: '#F6FBFF' },
    { name: 'Lavender', theme: 'Lavender Dream', accent: '#B9A7E0', accent2: '#F6F3FB' },
    { name: 'Lilac', theme: 'Lilac Haze', accent: '#C7B3D6', accent2: '#FBF8FD' },
    { name: 'Muted Pink', theme: 'Blush', accent: '#E8B7C8', accent2: '#FFF5F8' },
    { name: 'Peach', theme: 'Peach Sunrise', accent: '#F2B091', accent2: '#FFF6F2' },
    { name: 'Butter', theme: 'Buttercream', accent: '#F4D58D', accent2: '#FFFDF2' },
    { name: 'Pistachio', theme: 'Pistachio Grove', accent: '#D6E8C3', accent2: '#FBFDF4' },
    { name: 'Mint', theme: 'Fresh Mint', accent: '#BFEAD6', accent2: '#F9FFFB' },
    { name: 'Seafoam', theme: 'Seafoam Breeze', accent: '#9EE3C5', accent2: '#F7FFF6' },
    { name: 'Aqua', theme: 'Aqua Calm', accent: '#8ED6D1', accent2: '#F4FFFE' },
    { name: 'Robin Egg', theme: "Robin's Dawn", accent: '#8EC7E6', accent2: '#F5FDFF' },
    { name: 'Periwinkle', theme: 'Periwinkle Morning', accent: '#B2C8F9', accent2: '#F8FBFF' },
    { name: 'Dusty Blue', theme: 'Dusty Blue', accent: '#9BB1C8', accent2: '#F6F9FB' },
    { name: 'Slate Rose', theme: 'Slate Rose', accent: '#C9A6A6', accent2: '#FBF6F6' },
    { name: 'Tea', theme: 'Tea Garden', accent: '#C9D6B3', accent2: '#FBFDF4' },
    { name: 'Stone', theme: 'Stone Whisper', accent: '#BFC8C6', accent2: '#F7F9F9' },
    { name: 'Soft Gray', theme: 'Soft Gray', accent: '#BDC3C7', accent2: '#FAFBFC' },
    { name: 'Charcoal Mist', theme: 'Charcoal Mist', accent: '#93A0A8', accent2: '#F1F5F6' },
    { name: 'Aurora', theme: 'Aurora', accent: '#0F766E', accent2: '#E6FAF8' }
  ];

  window.VIBE_PALETTES = palettes;

  function hexToRgb(hex) {
    const normalized = hex.replace('#', '');
    const bigint = parseInt(
      normalized.length === 3
        ? normalized.split('').map((char) => char + char).join('')
        : normalized,
      16
    );
    return {
      r: (bigint >> 16) & 255,
      g: (bigint >> 8) & 255,
      b: bigint & 255,
    };
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

  function isExternalThemeEnabled() {
    return document.body.classList.contains('external-theme');
  }

  function isVibeFeatureEnabled() {
    return !document.body.classList.contains('no-vibe') && !isExternalThemeEnabled();
  }

  function clearThemeOverrides() {
    themeManagedProps.forEach((prop) => {
      try {
        document.documentElement.style.removeProperty(prop);
      } catch (error) {}
    });
  }

  function syncThemeBannerLayout(options = {}) {
    const quotesEnabled = options.quotesEnabled !== false;
    const hasVisibleVibeControl = vibeControlPanels.some((panel) => !panel.hidden);
    const shouldShowBanner = quotesEnabled || hasVisibleVibeControl;

    try {
      document.body.classList.toggle('no-brand-banner', !shouldShowBanner);
    } catch (error) {}

    quotePanels.forEach((panel) => {
      try {
        panel.hidden = !quotesEnabled;
        panel.setAttribute('aria-hidden', !quotesEnabled ? 'true' : 'false');
      } catch (error) {}
    });

    themeBanners.forEach((banner) => {
      try {
        banner.hidden = !shouldShowBanner;
        banner.setAttribute('aria-hidden', !shouldShowBanner ? 'true' : 'false');
        banner.classList.toggle('brand-banner-row--quotes-only', !hasVisibleVibeControl);
      } catch (error) {}
    });
  }

  function setVibeFeatureState(enabled) {
    const vibeEnabled = !!enabled;
    try {
      document.body.classList.toggle('no-vibe', !vibeEnabled);
    } catch (error) {}

    vibeControlPanels.forEach((panel) => {
      try {
        panel.hidden = !vibeEnabled;
        panel.setAttribute('aria-hidden', !vibeEnabled ? 'true' : 'false');
      } catch (error) {}
    });

    vibeShells.forEach((shell) => {
      try {
        shell.hidden = !vibeEnabled;
        shell.setAttribute('aria-hidden', !vibeEnabled ? 'true' : 'false');
      } catch (error) {}
    });

    vibeButtons.forEach((button) => {
      try {
        button.hidden = !vibeEnabled;
        button.setAttribute('aria-hidden', !vibeEnabled ? 'true' : 'false');
      } catch (error) {}
    });

    if (!vibeEnabled) {
      clearThemeOverrides();
    }

    syncThemeBannerLayout();
  }

  function syncVibeControlAvailability() {
    const darkMode = isDarkModeEnabled();
    const vibeFeatureEnabled = isVibeFeatureEnabled();

    vibeButtons.forEach((button) => {
      try {
        button.disabled = darkMode;
        const unavailable = darkMode || !vibeFeatureEnabled;
        button.hidden = !vibeFeatureEnabled;
        button.disabled = unavailable;
        if (unavailable) {
          button.classList.add('disabled');
          button.setAttribute('aria-disabled', 'true');
        } else {
          button.classList.remove('disabled');
          button.setAttribute('aria-disabled', 'false');
        }
      } catch (error) {}
    });

    vibeControlPanels.forEach((panel) => {
      try {
        panel.hidden = !vibeFeatureEnabled;
        panel.setAttribute('aria-hidden', !vibeFeatureEnabled ? 'true' : 'false');
      } catch (error) {}
    });

    vibeShells.forEach((shell) => {
      try {
        shell.hidden = !vibeFeatureEnabled;
        shell.setAttribute('aria-hidden', !vibeFeatureEnabled ? 'true' : 'false');
      } catch (error) {}
    });

    syncThemeBannerLayout();

    const vibeSelect = document.getElementById('vibe_index');
    if (vibeSelect) {
      vibeSelect.disabled = darkMode;
      Array.from(vibeSelect.options).forEach((option) => {
        option.disabled = false;
      });
    }

    const vibeDarkModeNote = document.getElementById('vibeDarkModeNote');
    if (vibeDarkModeNote) {
      vibeDarkModeNote.hidden = !darkMode;
    }
  }

  let vibeFeedbackTimer = null;

  function clearVibeFeedback() {
    const feedback = document.getElementById('globalVibeFeedback');
    if (feedback) {
      feedback.classList.add('d-none');
      feedback.textContent = '';
    }
    if (vibeFeedbackTimer) {
      clearTimeout(vibeFeedbackTimer);
      vibeFeedbackTimer = null;
    }
  }

  function showVibeFeedback(message, variant = 'warning') {
    const feedback = document.getElementById('globalVibeFeedback');
    const settingsStatus = document.getElementById('settingsAutoSaveStatus');

    if (settingsStatus) {
      settingsStatus.textContent = message;
    }

    if (!feedback) return;
    feedback.textContent = message;
    feedback.className = `alert alert-${variant} vibe-feedback`;
    feedback.classList.remove('d-none');

    if (vibeFeedbackTimer) {
      clearTimeout(vibeFeedbackTimer);
    }
    vibeFeedbackTimer = setTimeout(() => {
      clearVibeFeedback();
      if (settingsStatus) {
        settingsStatus.textContent = 'Changes save automatically.';
      }
    }, 5000);
  }

  function isUserLoggedIn() {
    if (typeof window.USER_LOGGED_IN !== 'undefined') return !!window.USER_LOGGED_IN;
    return document.body.dataset.userLoggedIn === '1';
  }

  function getUserVibeIndex() {
    if (typeof window.USER_VIBE_INDEX !== 'undefined' && window.USER_VIBE_INDEX !== null) return Number(window.USER_VIBE_INDEX);
    if (typeof document.body.dataset.userVibe !== 'undefined' && document.body.dataset.userVibe !== '') return Number(document.body.dataset.userVibe);
    return null;
  }

  function applyTheme(idx) {
    const darkMode = isDarkModeEnabled();
    if (!isVibeFeatureEnabled()) {
      clearThemeOverrides();
      syncVibeControlAvailability();
      return;
    }
    if (darkMode) {
      // when dark mode is active we ignore vibes entirely and clear any
      // previously-applied palette overrides so the default dark CSS applies.
      clearThemeOverrides();
      return;
    }

    const requestedIdx = Number(idx);
    const effectiveIdx = Number.isFinite(requestedIdx) ? requestedIdx : 0;
    const palette = palettes[effectiveIdx] || palettes[0];
    const root = document.documentElement;
    const rgb = hexToRgb(palette.accent);

    root.style.setProperty('--accent', palette.accent);
    root.style.setProperty('--accent-rgb', `${rgb.r}, ${rgb.g}, ${rgb.b}`);
    root.style.setProperty('--accent-2', palette.accent2 || palette.accent);
    root.style.setProperty("--nav-bg", mixHex(palette.accent, "#162033", 0.20));
    root.style.setProperty("--nav-text", mixHex("#f8fbff", palette.accent, 0.06));
    root.style.setProperty("--body-text", mixHex("#132033", palette.accent, 0.04));
    root.style.setProperty("--surface", mixHex("#ffffff", palette.accent2 || palette.accent, 0.96));
    root.style.setProperty("--surface-2", mixHex("#f4f7fb", palette.accent, 0.08));
    root.style.setProperty("--surface-3", mixHex("#eef4fb", palette.accent, 0.12));
    root.style.setProperty("--border", "rgba(15, 23, 42, 0.10)");
    root.style.setProperty("--focus", `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.16)`);
    root.style.setProperty("--banner-bg", `linear-gradient(135deg, rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.22), rgba(255, 255, 255, 0.96))`);
    root.style.setProperty("--banner-border", `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.30)`);
    root.style.setProperty("--banner-shadow", `0 12px 26px rgba(15, 23, 42, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.72)`);
    root.style.setProperty("--page-bg", `radial-gradient(circle at 18% 18%, rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.10), transparent 28%), radial-gradient(circle at 82% 0%, rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.08), transparent 26%), linear-gradient(180deg, #f8fbff 0%, #eef4fb 100%)`);

    document.querySelectorAll('.vibeLabel, #vibeLabel').forEach((element) => {
      try { element.textContent = palette.theme || palette.name; } catch (error) {}
    });

    const vibeSelect = document.getElementById('vibe_index');
    if (vibeSelect && String(vibeSelect.value) !== String(effectiveIdx)) {
      vibeSelect.value = String(effectiveIdx);
    }

    document.querySelectorAll('[data-vibe-preview-name]').forEach((element) => {
      try { element.textContent = palette.theme || palette.name; } catch (error) {}
    });
    document.querySelectorAll('[data-vibe-preview-accent]').forEach((element) => {
      try { element.style.background = palette.accent; } catch (error) {}
    });
    document.querySelectorAll('[data-vibe-preview-accent2]').forEach((element) => {
      try { element.style.background = palette.accent2 || palette.accent; } catch (error) {}
    });

    localStorage.setItem('vibeTheme', String(effectiveIdx));
    syncVibeControlAvailability();

    try {
      if (isUserLoggedIn()) {
        fetch('/auth/vibe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ vibe_index: effectiveIdx }),
        })
          .then(async (response) => {
            let payload = null;
            try {
              payload = await response.json();
            } catch (error) {}

            if (!response.ok) {
              if (payload && (payload.error === 'dark_mode_vibe_disabled' || payload.error === 'vibe_disabled')) {
                return;
              }
              showVibeFeedback("Couldn't save your theme change. Please try again.", 'warning');
              return;
            }

            if (payload && Number.isFinite(Number(payload.vibe_index)) && Number(payload.vibe_index) !== effectiveIdx) {
              applyTheme(Number(payload.vibe_index));
              return;
            }

            clearVibeFeedback();
            const settingsStatus = document.getElementById('settingsAutoSaveStatus');
            if (settingsStatus) {
              settingsStatus.textContent = 'Changes save automatically.';
            }
          })
          .catch(() => {
            showVibeFeedback("Couldn't save your theme change. Please try again.", 'warning');
          });
      }
    } catch (error) {}
  }

  window.addEventListener('form:autosaved', (event) => {
    const detail = event && event.detail ? event.detail : {};
    const endpoint = String(detail.endpoint || '');

    if (endpoint.endsWith('/admin/feature_flags')) {
      const flags = detail.payload && detail.payload.flags ? detail.payload.flags : null;
      if (!flags || typeof flags.vibe_enabled === 'undefined') return;

      const vibeEnabled = !!flags.vibe_enabled;
      const quotesEnabled = typeof flags.rolling_quotes_enabled === 'undefined' ? true : !!flags.rolling_quotes_enabled;
      setVibeFeatureState(vibeEnabled);
      syncThemeBannerLayout({ quotesEnabled });
      syncVibeControlAvailability();

      const statusEl = document.getElementById('featureFlagsAutoSaveStatus');
      if (statusEl) {
        statusEl.textContent = 'Changes saved.';
        setTimeout(() => { statusEl.textContent = ''; }, 3000);
      }

      setTimeout(() => { window.location.reload(); }, 500);
      try {
        localStorage.setItem('featureFlagsLastUpdate', Date.now());
      } catch (error) {}

      if (vibeEnabled && !isDarkModeEnabled()) {
        const saved = Number(localStorage.getItem('vibeTheme'));
        const userVibe = getUserVibeIndex();
        const nextIdx = Number.isFinite(userVibe) && !Number.isNaN(userVibe)
          ? userVibe
          : (Number.isFinite(saved) && !Number.isNaN(saved) ? saved : 0);
        applyTheme(nextIdx);
      }
      return;
    }

    if (endpoint.endsWith('/auth/preferences') || endpoint.endsWith('/auth/preferences/dark-mode')) {
      const prefs = detail.payload && detail.payload.preferences ? detail.payload.preferences : {};
      let didUpdate = false;

      if (typeof prefs.vibe_button_enabled !== 'undefined') {
        const enabled = !!prefs.vibe_button_enabled;
        vibeButtons.forEach((button) => {
          try {
            button.hidden = !enabled;
            button.setAttribute('aria-hidden', !enabled ? 'true' : 'false');
          } catch (error) {}
        });
        syncThemeBannerLayout();
        didUpdate = true;
      }

      if (typeof prefs.quotes_enabled !== 'undefined') {
        syncThemeBannerLayout({ quotesEnabled: !!prefs.quotes_enabled });
        didUpdate = true;
      }

      if (typeof prefs.dark_mode !== 'undefined') {
        try {
          document.body.classList.toggle('dark-mode', !!prefs.dark_mode);
        } catch (error) {}
        didUpdate = true;
      }

      if (typeof prefs.onboarding_guidance_enabled !== 'undefined') {
        const guidanceOn = !!prefs.onboarding_guidance_enabled;
        if (!guidanceOn) {
          document.querySelectorAll('.hero-callouts, .admin-orientation-panel').forEach((element) => {
            try { element.remove(); } catch (error) {}
          });
        }
        didUpdate = true;
      }

      if (didUpdate) {
        try {
          localStorage.setItem('userPrefsLastUpdate', Date.now());
        } catch (error) {}
        if (!window.location.pathname.startsWith('/auth/settings')) {
          setTimeout(() => { window.location.reload(); }, 200);
        }
      }
    }
  });

  document.addEventListener('DOMContentLoaded', () => {
    const vibeToggle = document.querySelector('input[name="vibe_button_enabled"]');
    if (vibeToggle) {
      vibeToggle.addEventListener('change', () => {
        const preview = document.getElementById('settingsVibePreview');
        if (preview) preview.hidden = !vibeToggle.checked;
      });
    }
  });

  const userVibe = getUserVibeIndex();
  const stored = (userVibe !== null && !Number.isNaN(userVibe)) ? userVibe : Number(localStorage.getItem('vibeTheme'));
  const dailySeed = new Date().getUTCDate() + new Date().getUTCMonth() * 31;
  const startIdx = Number.isFinite(stored) ? stored % palettes.length : (dailySeed % palettes.length);
  window.applyVibeTheme = applyTheme;
  window.syncVibeThemeState = syncVibeControlAvailability;
  if (!isVibeFeatureEnabled()) {
    syncVibeControlAvailability();
    clearThemeOverrides();
    return;
  }

  applyTheme(startIdx);

  function advanceVibe() {
    if (isDarkModeEnabled()) {
      return;
    }
    const current = Number(localStorage.getItem('vibeTheme')) || 0;
    const next = (current + 1) % palettes.length;
    applyTheme(next);
  }

  vibeButtons.forEach((button) => {
    button.addEventListener('click', (event) => {
      if (button.tagName === 'A') {
        event.preventDefault();
      }
      advanceVibe();
    });
  });
}

window.initThemeEngine = initThemeEngine;
initThemeEngine();