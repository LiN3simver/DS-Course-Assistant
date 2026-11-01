'use strict';
// Run before the stylesheet to apply the saved theme without a light flash.
(() => {
  const key = 'scu.theme.v1';
  const media = window.matchMedia?.('(prefers-color-scheme: dark)');
  let preference = null;
  try {
    const saved = localStorage.getItem(key);
    if (saved === 'light' || saved === 'dark') preference = saved;
  } catch { /* The switch still works when browser storage is unavailable. */ }
  function syncButton() {
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    const dark = document.documentElement.dataset.theme === 'dark';
    const label = dark ? 'Switch to light theme' : 'Switch to dark theme';
    button.setAttribute('aria-label', label);
    button.title = label;
  }
  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === 'dark' ? '#212121' : '#ffffff';
    syncButton();
  }
  function toggle() {
    preference = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(key, preference); } catch { /* Keep the current-tab preference. */ }
    apply(preference);
  }
  media?.addEventListener?.('change', (event) => {
    if (!preference) apply(event.matches ? 'dark' : 'light');
  });
  apply(preference || (media?.matches ? 'dark' : 'light'));
  window.SCUTheme = Object.freeze({ toggle, syncButton });
})();
