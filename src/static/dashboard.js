'use strict';
(() => {
  const dataElement = document.getElementById('dashboard-data');
  if (!dataElement) return;
  let data = JSON.parse(dataElement.textContent);
  let metrics = new Map(data.metrics.map(metric => [metric.id, metric]));
  const cards = [...document.querySelectorAll('[data-stat-slot]')];
  const dialog = document.getElementById('stat-dialog');
  const select = document.getElementById('stat-metric');
  const message = document.getElementById('dashboard-message');
  const storageKey = `film-dashboard-v1:${data.page}`;
  let choices = [...data.defaults], activeSlot = 0;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey));
    if (Array.isArray(saved)) choices = data.defaults.map((fallback, slot) => metrics.has(saved[slot]) ? saved[slot] : fallback);
  } catch (_) { /* Browser storage is optional; the dashboard still works. */ }

  function render() {
    cards.forEach((card, slot) => {
      const metric = metrics.get(choices[slot]);
      card.className = `stat-card stat-card-editable tone-${metric.tone}`;
      card.querySelector('.stat-label').textContent = metric.label;
      card.querySelector('.stat-value').textContent = metric.display;
      card.querySelector('.stat-scope').textContent = metric.scope;
      card.querySelector('.stat-symbol').textContent = metric.icon;
      card.setAttribute('aria-label', `Customize ${metric.label} statistic`);
      card.title = metric.description;
    });
  }
  function persist(announcement) {
    try { localStorage.setItem(storageKey, JSON.stringify(choices)); }
    catch (_) { announcement += ' Browser storage is unavailable; this choice lasts until the page reloads.'; }
    message.textContent = announcement;
  }
  function preview() {
    const metric = metrics.get(select.value);
    document.getElementById('stat-preview-value').textContent = metric.display;
    document.getElementById('stat-preview-scope').textContent = metric.scope;
    document.getElementById('stat-preview-description').textContent = metric.description;
  }
  cards.forEach((card, slot) => card.addEventListener('click', () => {
    activeSlot = slot;
    select.value = choices[slot];
    preview();
    dialog.showModal();
    select.focus();
  }));
  select.addEventListener('change', preview);
  document.getElementById('stat-dialog-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!metrics.has(select.value)) return;
    choices[activeSlot] = select.value;
    render();persist(`Card updated to ${metrics.get(select.value).label}.`);
    dialog.close();
  });
  document.getElementById('stat-dialog-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => cards[activeSlot].focus());
  document.getElementById('stat-dialog-reset').addEventListener('click', () => {
    select.value = data.defaults[activeSlot];preview();
  });
  document.getElementById('dashboard-reset').addEventListener('click', () => {
    choices = [...data.defaults];render();persist('Default statistics restored.');
  });
  dataElement.addEventListener('statistics-update', event => {
    if (event.detail.page !== data.page) return;
    data = event.detail;
    metrics = new Map(data.metrics.map(metric => [metric.id, metric]));
    choices = choices.map((key, slot) => metrics.has(key) ? key : data.defaults[slot]);
    if (!metrics.has(select.value)) select.value = choices[activeSlot];
    render();preview();
  });
  render();
})();
