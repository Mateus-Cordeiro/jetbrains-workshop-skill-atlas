// Scan dialog presentation only; the server owns URL validation and scan policy.
(() => {
  const dialog = document.querySelector('#scan-dialog');
  if (!dialog) return;
  const form = dialog.querySelector('form');
  const input = dialog.querySelector('input');
  const submit = form.querySelector('[type=submit]');
  const feedback = dialog.querySelector('#scan-dialog-feedback');
  const scope = dialog.querySelector('#scan-scope');

  function updateScope() {
    const value = input.value.trim();
    // These shape hints do not validate or normalize the submitted URL.
    const organization = /^https:\/\/github\.com(?::443)?\/[a-z0-9-]+\/?$/i.test(value);
    const repository = /^https:\/\/github\.com(?::443)?\/[a-z0-9-]+\/[a-z0-9_.-]+\/*$/i.test(value);
    submit.textContent = organization ? 'Scan organization' : repository ? 'Scan repository' : 'Start scan';
    scope.textContent = organization
      ? 'Scans repositories in this organization, excluding forks and archived repositories.' : '';
  }

  document.addEventListener('click', event => {
    if (event.target.closest('[data-open-scan]')) {
      updateScope();
      dialog.showModal();
      input.focus();
    }
    if (event.target.closest('[data-close-scan]')) dialog.close();
  });
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const controls = [...dialog.querySelectorAll('button:not(:disabled), input')];
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
  input.addEventListener('input', () => {
    feedback.replaceChildren();
    input.removeAttribute('aria-invalid');
    updateScope();
  });
  form.addEventListener('htmx:beforeRequest', () => {
    feedback.replaceChildren();
    input.removeAttribute('aria-invalid');
    form.setAttribute('aria-busy', 'true');
  });
  form.addEventListener('htmx:afterRequest', event => {
    form.removeAttribute('aria-busy');
    if (event.detail.xhr.status === 202) dialog.close();
    else if (event.detail.xhr.status === 400) input.setAttribute('aria-invalid', 'true');
  });
})();
