'use strict';
(() => {
  const root = document.documentElement;
  const storageKey = 'film-reel-theme';
  let theme = 'dark';
  try {
    if (localStorage.getItem(storageKey) === 'light') theme = 'light';
  } catch (_) { /* The toggle still works when browser storage is unavailable. */ }
  root.dataset.theme = theme;

  document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    function updateButton() {
      const light = root.dataset.theme === 'light';
      button.textContent = light ? '☾ Dark mode' : '☀ Light mode';
      button.setAttribute('aria-label', `Switch to ${light ? 'dark' : 'light'} mode`);
    }
    updateButton();
    button.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
      try { localStorage.setItem(storageKey, root.dataset.theme); } catch (_) {}
      updateButton();
      document.dispatchEvent(new Event('themechange'));
    });
  });
})();
