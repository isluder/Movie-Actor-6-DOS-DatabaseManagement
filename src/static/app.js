'use strict';
for (const input of document.querySelectorAll('[data-actor-target]')) {
  const wrapper = input.closest('.actor-picker');
  const options = wrapper.querySelector('.actor-options');
  const target = document.getElementById(input.dataset.actorTarget);
  let timer, controller, sequence = 0;
  input.addEventListener('input', () => {
    clearTimeout(timer); controller?.abort(); target.value = ''; options.replaceChildren();
    target.dispatchEvent(new Event('change', {bubbles:true}));
    const seq = ++sequence;
    if (input.value.trim().length < 2) return;
    timer = setTimeout(async () => {
      controller = new AbortController();
      try {
        const response = await fetch('/api/actors?' + new URLSearchParams({q: input.value}), {signal: controller.signal});
        if (!response.ok) return;
        const data = await response.json();
        if (seq !== sequence) return;
        for (const actor of data.actors) {
          const button = document.createElement('button'); button.type = 'button';
          button.textContent = `${actor.name} · ID ${actor.id} · ${actor.movie_count} movies`;
          button.addEventListener('click', () => {
            target.value = actor.id; input.value = actor.name; options.replaceChildren();
            target.dispatchEvent(new Event('change', {bubbles:true}));
            const hint = wrapper.querySelector('.hint'); if (hint) hint.textContent = `Selected ID: ${actor.id}`;
          }); options.append(button);
        }
      } catch (error) { if (error.name !== 'AbortError') options.textContent = 'Actor lookup unavailable. Try again.'; }
    }, 200);
  });
}

const siteMenu = document.getElementById('site-menu');
if (siteMenu) {
  document.addEventListener('click', event => {
    if (!siteMenu.contains(event.target)) siteMenu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && siteMenu.open) {
      siteMenu.open = false;
      siteMenu.querySelector('summary').focus();
    }
  });
}
const castRows = document.getElementById('manual-cast-rows');
if (castRows) {
  document.getElementById('add-cast-row').addEventListener('click', () => {
    if (castRows.children.length >= 100) return;
    castRows.append(document.getElementById('manual-cast-template').content.cloneNode(true));
    castRows.lastElementChild.querySelector('input').focus();
  });
  castRows.addEventListener('click', event => {
    if (event.target.closest('[data-remove-cast]')) event.target.closest('.manual-cast-row').remove();
  });
}

const sqlExamples = document.getElementById('sql-examples');
if (sqlExamples) {
  const examples = JSON.parse(sqlExamples.textContent);
  const editor = document.getElementById('sql');
  for (const button of document.querySelectorAll('[data-sql-example]')) {
    button.addEventListener('click', () => {
      const example = examples[Number(button.dataset.sqlExample)];
      editor.value = example.sql;
      editor.focus();
      editor.setSelectionRange(0, 0);
      document.getElementById('sql-example-status').textContent = `Loaded ${example.label}. Edit the query, then choose Run query.`;
    });
  }
}
