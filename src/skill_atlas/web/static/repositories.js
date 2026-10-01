// Explicit local catalog removal; list ordering and refreshes belong to filters.js.
(() => {
  const pending = new Set();

  async function remove(button) {
    const repository = button.closest('.repository-group').dataset.repository;
    if (pending.has(repository)) return;
    const name = button.dataset.repositoryName;
    if (!confirm(`Remove ${name} from your local catalog? Its stored skills and local stars will be deleted. GitHub is unaffected. A later scan can add it again.`)) return;
    pending.add(repository);
    button.disabled = true;
    const feedback = document.querySelector('#scan-feedback');
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
        feedback.innerHTML = await response.text();
        return;
      }
      atlasFilters.forgetRepository(repository);
      feedback.replaceChildren();
      if (!await atlasFilters.refresh()) {
        feedback.textContent = `${name} was removed. Refresh the list to see the updated catalog.`;
      }
      // The removed control no longer owns focus after the refreshed list arrives.
      document.querySelector('#repository-sort').focus();
    } catch {
      feedback.textContent = 'Could not confirm removal. Check that the server is running, then retry or refresh the list.';
    } finally {
      clearTimeout(timeout);
      pending.delete(repository);
      button.disabled = false;
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('.repository-remove');
    if (button) remove(button);
  });
})();
