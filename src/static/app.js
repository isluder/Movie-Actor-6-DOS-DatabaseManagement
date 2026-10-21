'use strict';
document.addEventListener('submit', event => {
  const text = event.target.dataset.confirm;
  if (text && !window.confirm(text)) event.preventDefault();
});
document.addEventListener('click', event => {
  const button = event.target.closest('[data-confirm-button]');
  if (button && !window.confirm(button.dataset.confirmButton)) event.preventDefault();
});
for (const input of document.querySelectorAll('[data-actor-target]')) {
  const wrapper = input.closest('.actor-picker');
  const options = wrapper.querySelector('.actor-options');
  const target = document.getElementById(input.dataset.actorTarget);
  let timer, controller, sequence = 0;
  input.addEventListener('input', () => {
    clearTimeout(timer); controller?.abort(); target.value = ''; options.replaceChildren();
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
            const hint = wrapper.querySelector('.hint'); if (hint) hint.textContent = `Selected ID: ${actor.id}`;
          }); options.append(button);
        }
      } catch (error) { if (error.name !== 'AbortError') options.textContent = 'Actor lookup unavailable. Try again.'; }
    }, 200);
  });
}
for (const select of document.querySelectorAll('.saved-choice')) {
  const form = select.closest('form');
  function populate() {
    const option = select.selectedOptions[0];
    if (select.value) {form.elements.name.value = option.dataset.name;form.elements.note.value = option.dataset.note;}
  }
  select.addEventListener('change',populate);populate();
}
