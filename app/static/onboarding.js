document.addEventListener('DOMContentLoaded', function () {
  try {
    const shouldShow = true; // server controls whether markup is rendered
    if (!shouldShow) return;
    const modalEl = document.getElementById('onboardingModal');
    if (!modalEl) return;
    const modal = new bootstrap.Modal(modalEl, { backdrop: true });
    // show after a short delay so page chrome settles
    setTimeout(() => modal.show(), 350);

    const dismissBtn = document.getElementById('onboardingDismissBtn');
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content;

    function persistDismissal() {
      try {
        fetch('/admin/onboarding/dismiss', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': csrf || ''
          },
          body: JSON.stringify({ dismissed: true }),
        }).catch((_) => {});
      } catch (e) {}
    }

    if (dismissBtn) {
      dismissBtn.addEventListener('click', function () {
        try {
          modal.hide();
        } catch (e) {}
        persistDismissal();
      });
    }

    // also persist if user closes via the close button or backdrop
    modalEl.addEventListener('hidden.bs.modal', function () {
      persistDismissal();
    });
  } catch (e) {
    console.warn('Onboarding script error', e);
  }
});
