// Local star toggles; list filtering stays in filters.js and documents in app.js.
(() => {
  const pending = new Set();
  const identity = button => JSON.stringify([button.dataset.starRepository, button.dataset.starPath]);
  // A skill can appear in a list and in the open document's header at the same time.
  const matching = key => [...document.querySelectorAll('.star-toggle')].filter(item => identity(item) === key);

  function feedback(content) {
    const panel = document.querySelector('#scan-feedback');
    if (panel) panel.innerHTML = content;
  }

  async function toggle(button) {
    const key = identity(button);
    if (pending.has(key)) return;
    pending.add(key);
    try {
      const response = await fetch('/stars', {
        method: 'POST',
        headers: {'X-Atlas-Request': '1', 'HX-Request': 'true'},
        body: new URLSearchParams({
          repository_url: button.dataset.starRepository,
          skill_path: button.dataset.starPath,
          // The requested state, not a flip, so repeated submissions are idempotent.
          starred: button.getAttribute('aria-pressed') === 'true' ? '0' : '1',
        }),
      });
      const content = await response.text();
      if (!response.ok) {
        feedback(content);
        return;
      }
      const result = new DOMParser().parseFromString(content, 'text/html').querySelector('.star-toggle');
      matching(key).forEach(item => item.setAttribute('aria-pressed', result.getAttribute('aria-pressed')));
      document.querySelector('#scan-feedback')?.replaceChildren();
      if (atlasFilters.starred()) {
        await atlasFilters.refresh();
        if (!button.isConnected) document.querySelector('#starred-filter').focus();
      }
    } catch {
      feedback('<div class="error" role="alert"><p>Could not update the star. Check that the server is running, then retry.</p></div>');
    } finally {
      pending.delete(key);
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('.star-toggle');
    if (button) toggle(button);
  });
})();
