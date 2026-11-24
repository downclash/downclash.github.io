document.addEventListener('DOMContentLoaded', function () {
  // Theme toggle
  initTheme();
  initTutorialCatalogs();

  // Mobile menu toggle
  const mobileMenuBtn = document.getElementById('mobileMenuBtn');
  const mobileMenu = document.getElementById('mobileMenu');

  if (mobileMenuBtn && mobileMenu) {
    function closeMenu() {
      mobileMenu.classList.add('hidden');
      mobileMenuBtn.setAttribute('aria-expanded', 'false');
      mobileMenuBtn.setAttribute('aria-label', '展开导航菜单');
    }
    mobileMenuBtn.addEventListener('click', function () {
      const expanded = mobileMenuBtn.getAttribute('aria-expanded') !== 'true';
      mobileMenu.classList.toggle('hidden', !expanded);
      mobileMenuBtn.setAttribute('aria-expanded', String(expanded));
      mobileMenuBtn.setAttribute('aria-label', expanded ? '收起导航菜单' : '展开导航菜单');
    });

    mobileMenu.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () {
        closeMenu();
      });
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && mobileMenuBtn.getAttribute('aria-expanded') === 'true') {
        closeMenu();
        mobileMenuBtn.focus();
      }
    });
  }

  // Keep header colors in the shared theme stylesheet.
  const header = document.querySelector('header');
  if (header) {
    function updateHeader() {
      header.classList.toggle('is-scrolled', window.scrollY > 24);
    }
    updateHeader();
    window.addEventListener('scroll', updateHeader, { passive: true });
  }

  // Intersection Observer for fade-in animations
  const fadeElements = document.querySelectorAll('.fade-in');
  if (fadeElements.length > 0 && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('visible');
          }
        });
      },
      { threshold: 0.1 }
    );

    fadeElements.forEach(function (el) {
      observer.observe(el);
    });
  }
});

// Articles stay in static HTML; filtering only changes their visibility.
function initTutorialCatalogs() {
  document.querySelectorAll('[data-tutorial-catalog]').forEach(function (catalog) {
    const input = catalog.querySelector('[data-tutorial-search]');
    const controls = catalog.querySelector('[data-catalog-controls]');
    const status = catalog.querySelector('[data-catalog-status]');
    const empty = catalog.querySelector('[data-catalog-empty]');
    const clear = catalog.querySelector('[data-catalog-clear]');
    const buttons = Array.from(catalog.querySelectorAll('[data-tutorial-filter]'));
    const cards = Array.from(catalog.querySelectorAll('[data-tutorial-card]'));
    const groups = Array.from(catalog.querySelectorAll('[data-tutorial-group]'));
    if (!input || !controls || !status || cards.length === 0) return;
    let category = 'all';
    const query = new URLSearchParams(window.location.search).get('q');
    if (query) input.value = query;

    function update() {
      const words = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      let visible = 0;
      cards.forEach(function (card) {
        const text = (card.dataset.search || card.textContent).toLowerCase();
        const matches = (category === 'all' || card.dataset.category === category)
          && words.every(function (word) { return text.includes(word); });
        card.hidden = !matches;
        if (matches) visible += 1;
      });
      groups.forEach(function (group) {
        group.hidden = !Array.from(group.querySelectorAll('[data-tutorial-card]')).some(function (card) { return !card.hidden; });
      });
      buttons.forEach(function (button) {
        button.setAttribute('aria-pressed', String(button.dataset.tutorialFilter === category));
      });
      status.textContent = '显示 ' + visible + ' / ' + cards.length + ' 篇教程';
      if (empty) empty.hidden = visible !== 0;
    }
    input.addEventListener('input', update);
    buttons.forEach(function (button) {
      button.addEventListener('click', function () {
        category = button.dataset.tutorialFilter;
        update();
      });
    });
    if (clear) clear.addEventListener('click', function () {
      category = 'all';
      input.value = '';
      update();
      input.focus();
    });
    controls.hidden = false;
    update();
  });
}

// Theme management
function initTheme() {
  let saved;
  try { saved = localStorage.getItem('v2ray-theme'); } catch (error) { /* Browser storage may be unavailable. */ }
  // Default to light mode; only use dark if explicitly saved
  if (saved === 'dark') {
    document.documentElement.classList.remove('light-mode');
  } else {
    document.documentElement.classList.add('light-mode');
  }

  const toggleBtn = document.getElementById('themeToggle');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', toggleTheme);
    toggleBtn.setAttribute('aria-label', saved === 'dark' ? '切换浅色主题' : '切换深色主题');
  }
}

function toggleTheme() {
  const html = document.documentElement;
  const isLight = html.classList.toggle('light-mode');
  try { localStorage.setItem('v2ray-theme', isLight ? 'light' : 'dark'); } catch (error) { /* Keep the current theme for this page. */ }
  const toggleBtn = document.getElementById('themeToggle');
  if (toggleBtn) toggleBtn.setAttribute('aria-label', isLight ? '切换深色主题' : '切换浅色主题');

}
