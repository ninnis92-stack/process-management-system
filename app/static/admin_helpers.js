// Small admin helpers: table search/filter and mobile card transformation
(function(){
  document.addEventListener('DOMContentLoaded', function(){
    function initTableSearch(id){
      var input = document.getElementById(id);
      if(!input) return;
      var target = input.getAttribute('data-target');
      if(!target) return;
      var table = document.querySelector(target);
      if(!table) return;
      var tbody = table.querySelector('tbody');
      if(!tbody) return;
      var rows = Array.from(tbody.querySelectorAll('tr'));
      function apply(q){
        q = (q||'').trim().toLowerCase();
        rows.forEach(function(r){
          var text = (r.textContent||'').toLowerCase();
          r.style.display = text.indexOf(q) === -1 ? 'none' : '';
        });
      }
      input.addEventListener('input', function(){ apply(input.value); });
      // initial mobile conversion: on small screens, add mobile-cards class
      function adapt(){
        if(window.innerWidth <= 767) table.classList.add('mobile-cards'); else table.classList.remove('mobile-cards');
      }
      window.addEventListener('resize', adapt);
      adapt();
    }
    initTableSearch('integrationSearch');
  });
})();

// ---------------------------------------------------------------------------
// Extracted from base.html – admin-specific helpers
// ---------------------------------------------------------------------------

// Admin notif toggle: persists visibility preference of #notifBtn in
// localStorage under key admin_notif_visible.
(function(){
  var toggle = document.getElementById('toggleNotifBtn');
  var notif = document.getElementById('notifBtn');
  var key = 'admin_notif_visible';
  function applyPref() {
    try {
      var v = localStorage.getItem(key);
      if (v === 'false') {
        if (notif) notif.style.display = 'none';
      } else {
        if (notif) notif.style.display = '';
      }
    } catch (e){}
  }
  if (toggle) {
    toggle.addEventListener('click', function(){
      try {
        var curr = localStorage.getItem(key);
        var next = (curr === 'false') ? 'true' : 'false';
        localStorage.setItem(key, next);
      } catch(e){}
      applyPref();
    });
    applyPref();
  }
})();

// Admin quick-search: filters .admin-card elements and collapses
// [data-admin-section] groups when nothing matches.
(function(){
  var input = document.getElementById('adminQuickSearch');
  var cards = Array.from(document.querySelectorAll('.admin-card'));
  var sections = Array.from(document.querySelectorAll('[data-admin-section]'));
  var clearBtn = document.getElementById('adminQuickSearchClear');
  var status = document.getElementById('adminQuickSearchStatus');
  var emptyState = document.getElementById('adminSearchEmptyState');
  if (cards.length) {
    cards.forEach(function(card){
      card.style.cursor = 'pointer';
      var href = card.getAttribute('data-nav-url') || card.getAttribute('href');
      if (href && card.tagName === 'A' && card.getAttribute('href') !== href) {
        card.setAttribute('href', href);
      }
      if (card.tagName !== 'BUTTON' && !card.hasAttribute('tabindex')) {
        card.setAttribute('tabindex', '0');
      }
      card.addEventListener('click', function(ev){
        try {
          ev.preventDefault();
          if (href) window.location.assign(href);
        } catch (e) {}
      });
      card.addEventListener('keydown', function(ev){
        try {
          if (ev.key !== 'Enter' && ev.key !== ' ') return;
          if (!href) return;
          ev.preventDefault();
          window.location.assign(href);
        } catch (e) {}
      });
    });
  }
  function syncSections(){
    var visibleCards = 0;
    sections.forEach(function(section){
      var sectionCards = Array.from(section.querySelectorAll('.admin-card'));
      var visibleInSection = sectionCards.filter(function(card){ return !card.classList.contains('hidden-by-filter'); }).length;
      section.hidden = visibleInSection === 0;
      visibleCards += visibleInSection;
    });
    if (emptyState) emptyState.hidden = visibleCards !== 0;
    return visibleCards;
  }
  function resetFilterState(){
    cards.forEach(function(c){ c.classList.remove('hidden-by-filter'); });
    sections.forEach(function(section){ section.hidden = false; });
    if (clearBtn) clearBtn.hidden = true;
    if (status) status.textContent = 'Filters as you type. Sections collapse automatically when nothing matches.';
    if (emptyState) emptyState.hidden = true;
  }
  if (clearBtn && input) {
    clearBtn.addEventListener('click', function(){
      input.value = '';
      resetFilterState();
      input.focus();
    });
  }
  if (!input) return;
  input.addEventListener('input', function(){
    var q = (input.value || '').trim().toLowerCase();
    if (!q) {
      resetFilterState();
      return;
    }
    cards.forEach(function(c){
      var text = (c.textContent || '').toLowerCase();
      if (text.indexOf(q) === -1) c.classList.add('hidden-by-filter'); else c.classList.remove('hidden-by-filter');
    });
    var visibleCards = syncSections();
    if (clearBtn) clearBtn.hidden = false;
    if (status) {
      status.textContent = visibleCards
        ? 'Showing ' + visibleCards + ' matching command-center card' + (visibleCards === 1 ? '' : 's') + '.'
        : 'No command-center cards matched that search.';
    }
  });
  resetFilterState();
})();

// Dynamic toggle labels: updates form-check label text based on checkbox state
// using data-toggle-text-checked / data-toggle-text-unchecked attributes.
document.querySelectorAll('.form-check-input[data-toggle-text-checked]').forEach(function(cb){
  var form = cb.closest('.form-check');
  var card = cb.closest('.admin-toggle-card');
  var lbl = form && form.querySelector('.form-check-label');
  if (lbl == null) return;
  var checkedLabel = cb.dataset.toggleTextChecked;
  var uncheckedLabel = cb.dataset.toggleTextUnchecked;
  var upd = function(){
    lbl.textContent = cb.checked ? checkedLabel : uncheckedLabel;
    form.classList.toggle('active', cb.checked);
    if (card) card.classList.toggle('active', cb.checked);
  };
  cb.addEventListener('change', upd);
  upd();
});
