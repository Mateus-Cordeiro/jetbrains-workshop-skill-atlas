// Explicit local catalog removal; list ordering and refreshes belong to filters.js.
(() => {
  const dialog = document.querySelector('#repository-remove-dialog');
  if (!dialog) return;
  const form = dialog.querySelector('form');
  const submit = form.querySelector('[type=submit]');
  const dismiss = form.querySelector('[data-close-removal]');
  const feedback = dialog.querySelector('#repository-remove-feedback');
  let selected;
  let pending = false;

  function close(restoreFocus = true) {
    dialog.close();
    if (!restoreFocus) return;
    // A scan/filter refresh may have replaced the original row while the modal was open.
    const group = [...document.querySelectorAll('.repository-group')]
      .find(group => group.dataset.repository === selected?.repository);
    (group?.querySelector('.repository-remove') || document.querySelector('#repository-sort'))?.focus();
  }

  function show(button) {
    if (pending) return;
    selected = {
      repository: button.closest('.repository-group').dataset.repository,
      name: button.dataset.repositoryName,
    };
    dialog.querySelector('#repository-remove-name').textContent = selected.name;
    feedback.replaceChildren();
    dialog.showModal();
    dismiss.focus();
  }

  function report(message) {
    const target = dialog.open ? feedback : document.querySelector('#scan-feedback');
    target.textContent = message;
  }

  async function remove() {
    if (pending || !selected || !dialog.open) return;
    const {repository, name} = selected;
    pending = true;
    submit.disabled = true;
    submit.textContent = 'Removing…';
    dismiss.textContent = 'Close';
    dismiss.focus();
    form.setAttribute('aria-busy', 'true');
    feedback.replaceChildren();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 35000);
    try {
      const response = await fetch('/repositories/remove', {
        method: 'POST',
        headers: {'X-Atlas-Request': '1', 'HX-Request': 'true'},
        body: new URLSearchParams({repository_url: repository}),
        signal: controller.signal,
      });
      if (!response.ok) {
        const content = await response.text();
        const target = dialog.open ? feedback : document.querySelector('#scan-feedback');
        target.innerHTML = content;
        return;
      }
      atlasFilters.forgetRepository(repository);
      const pageFeedback = document.querySelector('#scan-feedback');
      pageFeedback.replaceChildren();
      if (!await atlasFilters.refresh()) {
        pageFeedback.textContent = `${name} was removed. Refresh the list to see the updated catalog.`;
      }
      if (dialog.open) {
        close(false);
        document.querySelector('#repository-sort')?.focus();
      }
    } catch {
      report('Could not confirm removal. Check that the server is running, then retry or refresh the list.');
    } finally {
      clearTimeout(timeout);
      pending = false;
      submit.disabled = false;
      submit.textContent = 'Remove repository';
      dismiss.textContent = 'Cancel';
      form.removeAttribute('aria-busy');
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    remove();
  });
  dialog.addEventListener('cancel', event => {
    event.preventDefault();
    close();
  });
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const controls = [...dialog.querySelectorAll('button:not(:disabled)')];
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  document.addEventListener('click', event => {
    const button = event.target.closest('.repository-remove');
    if (button) show(button);
    if (event.target.closest('[data-close-removal]')) close();
  });
})();
