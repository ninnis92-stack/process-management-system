document.addEventListener('DOMContentLoaded', function () {
  try {
    // Ensure admin tiles are keyboard-accessible and present role/labels
    document.querySelectorAll('.admin-tile').forEach(function (el) {
      try {
        if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
        if (!el.hasAttribute('role')) el.setAttribute('role', 'button');
        if (!el.getAttribute('aria-label')) {
          const title = el.querySelector('.tile-title');
          const txt = title ? title.textContent.trim() : (el.textContent || '').trim().slice(0, 60);
          if (txt) el.setAttribute('aria-label', txt);
        }
        el.addEventListener('keydown', function (ev) {
          if (ev.key === 'Enter' || ev.key === ' ') {
            ev.preventDefault();
            el.click();
          }
        });
      } catch (e) {}
    });

    // Keep offcanvas toggle button aria-expanded in sync
    const offToggle = document.querySelector('button[data-bs-target="#adminSidebar"]');
    const offEl = document.getElementById('adminSidebar');
    if (offToggle && offEl) {
      offEl.addEventListener('show.bs.offcanvas', function () { offToggle.setAttribute('aria-expanded', 'true'); });
      offEl.addEventListener('hide.bs.offcanvas', function () { offToggle.setAttribute('aria-expanded', 'false'); });
      // ensure toggle has aria-controls
      if (!offToggle.hasAttribute('aria-controls')) offToggle.setAttribute('aria-controls', 'adminSidebar');
    }

    // Improve focus outline for admin back button
    document.querySelectorAll('.admin-back-btn, .brand-admin-btn, #testIntegrationBtn').forEach(function (b) {
      if (b && !b.hasAttribute('tabindex')) b.setAttribute('tabindex', '0');
    });
  } catch (e) { console.warn('admin_accessibility init failed', e); }
});
