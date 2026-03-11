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
