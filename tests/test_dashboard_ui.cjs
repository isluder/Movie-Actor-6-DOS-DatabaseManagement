'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('src/static/dashboard.js', 'utf8');

class Element {
  constructor() { this.listeners = {}; this.children = {}; this.textContent = ''; this.value = ''; }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  fire(type) { for (const callback of this.listeners[type] || []) callback({preventDefault() {}}); }
  querySelector(selector) { return this.children[selector] ||= new Element(); }
  setAttribute(name, value) { this[name] = value; }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; this.fire('close'); }
}
const metric = (id, value) => ({id, display: String(value), label: id, tone: 'gold', scope: 'all matches', description: 'known source values', icon: '*'});
const base = {page: 'index', defaults: ['movies', 'actors'], metrics: [metric('movies', 4), metric('actors', 3), metric('matches', 2)]};
function boot(data = base, storage = new Map(), unavailable = false) {
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  get('dashboard-data').textContent = JSON.stringify(data);
  const cards = data.defaults.map(() => new Element());
  const localStorage = {
    getItem: key => { if (unavailable) throw Error('blocked'); return storage.get(key) ?? null; },
    setItem: (key, value) => { if (unavailable) throw Error('blocked'); storage.set(key, value); }
  };
  vm.runInNewContext(code, {document: {getElementById: get, querySelectorAll: () => cards}, localStorage});
  return {get, cards, storage};
}
const app = boot();
assert.equal(app.cards[0].querySelector('.stat-value').textContent, '4');
app.cards[0].fire('click');
assert.equal(app.get('stat-dialog').open, true);
app.get('stat-metric').value = 'matches'; app.get('stat-metric').fire('change');
assert.equal(app.get('stat-preview-value').textContent, '2');
app.get('stat-dialog-form').fire('submit');
assert.equal(app.cards[0].querySelector('.stat-label').textContent, 'matches');
assert.equal(app.get('stat-dialog').open, false);
assert.equal(app.cards[0].focused, true);
const changed = boot({...base, metrics: [metric('movies', 4), metric('actors', 3), metric('matches', 9)]}, app.storage);
assert.equal(changed.cards[0].querySelector('.stat-value').textContent, '9');
assert.equal(boot({...base, page: 'bombs'}, app.storage).cards[0].querySelector('.stat-label').textContent, 'movies');
changed.cards[0].fire('click');changed.get('stat-dialog-reset').fire('click');
assert.equal(changed.get('stat-metric').value, 'movies');
changed.get('stat-dialog-form').fire('submit');
assert.equal(changed.cards[0].querySelector('.stat-label').textContent, 'movies');
app.get('dashboard-reset').fire('click');
assert.equal(app.cards[0].querySelector('.stat-label').textContent, 'movies');
assert.equal(boot(base, new Map([['film-dashboard-v1:index', '["removed-feature",42]']])).cards[0].querySelector('.stat-value').textContent, '4');
assert.equal(boot(base, new Map([['film-dashboard-v1:index', '{invalid']])).cards[0].querySelector('.stat-value').textContent, '4');
const blocked = boot(base, new Map(), true);
blocked.cards[1].fire('click');blocked.get('stat-metric').value = 'matches';blocked.get('stat-dialog-form').fire('submit');
assert.equal(blocked.cards[1].querySelector('.stat-label').textContent, 'matches');
assert.match(blocked.get('dashboard-message').textContent, /storage is unavailable/);
console.log('Dashboard UI: customization, previews, persistence, live values, per-page isolation, resets, stale settings, and blocked storage passed.');
// Asynchronous Six Degrees statistics refresh values without losing card choices.
app.cards[0].fire('click');app.get('stat-metric').value='matches';app.get('stat-dialog-form').fire('submit');
for (const listener of app.get('dashboard-data').listeners['statistics-update']) listener({detail:{...base,metrics:[metric('movies',40),metric('actors',30),metric('matches',20)]}});
assert.equal(app.cards[0].querySelector('.stat-value').textContent,'20');
assert.equal(app.cards[0].querySelector('.stat-label').textContent,'matches');
