(() => {
  let generation = 0;
  let documentRequest;
  const completed = new Set();
  const successTimers = new Map();
  const dismissedKey = 'skill-atlas.dismissed-jobs';
  const dismissed = new Set();
  try {
    const saved = JSON.parse(sessionStorage.getItem(dismissedKey) || '[]');
    if (Array.isArray(saved)) saved.filter(id => typeof id === 'string').forEach(id => dismissed.add(id));
  } catch { /* Dismissal still works in memory when browser storage is unavailable. */ }
  const workspace = () => document.querySelector('#workspace');
  function updateDescriptionToggle(button) {
    const description = document.getElementById(button.getAttribute('aria-controls'));
    button.hidden = button.getAttribute('aria-expanded') !== 'true'
      && description.scrollHeight <= description.clientHeight + 1;
  }

  const descriptionObserver = new ResizeObserver(entries => {
    entries.forEach(({target}) => {
      target.querySelectorAll('.description-toggle').forEach(updateDescriptionToggle);
    });
  });

  function observeDescriptions() {
    descriptionObserver.disconnect();
    document.querySelectorAll('.skills-list, .repository-skill-list').forEach(list => {
      descriptionObserver.observe(list);
    });
  }

  document.addEventListener('atlas:skills-updated', observeDescriptions);

  function updateActivityVisibility() {
    const panel = document.querySelector('#jobs');
    if (panel) panel.hidden = !panel.querySelector('.job');
  }

  function dismissJob(id) {
    const job = document.getElementById('job-' + id);
    if (job && ['queued', 'running'].includes(job.dataset.state)) return;
    dismissed.add(id);
    try {
      // Only opaque notification IDs, never repository metadata or document content.
      sessionStorage.setItem(dismissedKey, JSON.stringify([...dismissed].slice(-128)));
    } catch { /* Storage is optional for the current page. */ }
    clearTimeout(successTimers.get(id));
    successTimers.delete(id);
    job?.remove();
    updateActivityVisibility();
  }

  function updateJobNotices() {
    document.querySelectorAll('.job').forEach(job => {
      const {jobId, state} = job.dataset;
      if (['queued', 'running'].includes(state)) return;
      if (dismissed.has(jobId)) {
        job.remove();
      } else if (state === 'succeeded' && !successTimers.has(jobId)) {
        // Keep the same timer when another submission replaces the activity panel.
        successTimers.set(jobId, setTimeout(() => dismissJob(jobId), 5000));
      }
    });
    updateActivityVisibility();
  }

  function workspaceUrl(pane, fragment = false) {
    const params = new URLSearchParams({repository_url: pane.dataset.repository});
    if (atlasFilters.query()) params.set('q', atlasFilters.query());
    const similar = pane.dataset.mode === 'similar';
    if (similar) {
      params.set('skill_path', pane.dataset.sourcePath);
      params.set('return_to', pane.dataset.returnTo);
      if (pane.dataset.selectedPath) {
        params.set('selected_repository', pane.dataset.selectedRepository);
        params.set('selected_path', pane.dataset.selectedPath);
      }
    } else if (pane.dataset.selectedPath) params.set('skill_path', pane.dataset.selectedPath);
    return (fragment ? '/fragments' : '') + (similar ? '/similar?' : '/repository?') + params;
  }

  function refreshWorkspace() {
    const pane = workspace();
    if (!pane) return;
    generation++;
    documentRequest?.abort();
    htmx.ajax('GET', workspaceUrl(pane, true), {target: '#workspace', swap: 'outerHTML'});
  }

  document.addEventListener('DOMContentLoaded', () => {
    observeDescriptions();
    // A fresh page shows active work and unresolved errors, not past successes.
    document.querySelectorAll('.job[data-state="succeeded"]').forEach(job => {
      completed.add(job.dataset.jobId);
      dismissJob(job.dataset.jobId);
    });
    updateJobNotices();
  });
  document.addEventListener('htmx:beforeRequest', event => {
    const detail = event.detail;
    if (!['document', 'workspace'].includes(detail.target?.id)) return;
    detail.xhr.atlasGeneration = ++generation;
    if (detail.target.id === 'workspace') {
      detail.xhr.atlasQuery = atlasFilters.query();
      return;
    }
    documentRequest = detail.xhr;
    const link = detail.elt.closest('[data-skill-path]');
    if (link) {
      workspace().dataset.selectedPath = link.dataset.skillPath;
      workspace().dataset.selectedRepository = link.dataset.skillRepository || workspace().dataset.repository;
      document.querySelectorAll('.skill-link').forEach(item => {
        if (item === link) item.setAttribute('aria-current', 'true');
        else item.removeAttribute('aria-current');
      });
      if (location.href !== link.href) history.pushState(history.state, '', link.href);
      atlasFilters.selection();
    }
    detail.target.setAttribute('aria-busy', 'true');
    detail.target.innerHTML = '<div class="empty"><h2>Loading SKILL.md…</h2><p>Retrieving the scanned version from GitHub.</p></div>';
  });
  document.addEventListener('htmx:beforeSwap', event => {
    const detail = event.detail;
    if (detail.xhr.atlasGeneration !== undefined && detail.xhr.atlasGeneration !== generation) {
      detail.shouldSwap = false;
      return;
    }
    if (detail.target?.id === 'workspace' && detail.xhr.atlasQuery !== atlasFilters.query()) {
      detail.shouldSwap = false;
      refreshWorkspace();
      return;
    }
    if (detail.target?.id === 'workspace') atlasFilters.cancel();
    if ((detail.xhr.status === 409 || (detail.xhr.status === 404 && workspace()?.dataset.mode === 'similar')) && detail.target?.id === 'document') {
      detail.shouldSwap = false;
      refreshWorkspace();
      return;
    }
    if (detail.xhr.status >= 400) {
      detail.shouldSwap = true;
      detail.isError = false;
      if (['jobs', 'workspace'].includes(detail.target?.id)) {
        detail.target = document.querySelector('#scan-feedback');
        detail.swapOverride = 'innerHTML';
      }
    }
  });
  document.addEventListener('htmx:afterSwap', event => {
    document.querySelector('#document')?.removeAttribute('aria-busy');
    if (event.detail.target?.id === 'workspace') {
      observeDescriptions();
      const pane = workspace();
      if (pane) history.replaceState(history.state, '', workspaceUrl(pane));
      document.querySelector('#scan-feedback').replaceChildren();
      atlasFilters.restore();
    }
    if (event.detail.target?.id === 'jobs') document.querySelector('#scan-feedback').replaceChildren();
    document.querySelectorAll('.job[data-state="succeeded"]').forEach(job => {
      if (completed.has(job.dataset.jobId)) return;
      completed.add(job.dataset.jobId);
      if (document.querySelector('#repositories')) atlasFilters.refresh();
      if (workspace()?.dataset.mode === 'similar' || workspace()?.dataset.repository === job.dataset.repository) refreshWorkspace();
    });
    updateJobNotices();
  });
  for (const name of ['htmx:sendError', 'htmx:timeout']) {
    document.addEventListener(name, event => {
      const target = event.detail.target;
      if (target?.id === 'document' && event.detail.xhr.atlasGeneration !== generation) return;
      const panel = target?.id === 'document' ? target : document.querySelector('#scan-feedback');
      panel.innerHTML = '<div class="error" role="alert"><p>Could not reach the server. Check that it is running, then retry or refresh.</p></div>';
      panel.removeAttribute('aria-busy');
    });
  }
  document.addEventListener('click', event => {
    const addRepository = event.target.closest('#add-repository');
    if (addRepository) {
      const form = document.querySelector('#repository-form');
      form.hidden = !form.hidden;
      addRepository.setAttribute('aria-expanded', String(!form.hidden));
      if (!form.hidden) document.querySelector('#repository-url').focus();
    }
    const descriptionToggle = event.target.closest('.description-toggle');
    if (descriptionToggle) {
      const expanded = descriptionToggle.getAttribute('aria-expanded') !== 'true';
      const description = document.getElementById(descriptionToggle.getAttribute('aria-controls'));
      description.classList.toggle('expanded', expanded);
      descriptionToggle.setAttribute('aria-expanded', String(expanded));
      descriptionToggle.querySelector('span').textContent = expanded ? 'Show less' : 'Show more';
      updateDescriptionToggle(descriptionToggle);
    }
    const dismiss = event.target.closest('[data-dismiss-job]');
    if (dismiss) dismissJob(dismiss.closest('.job').dataset.jobId);
    const button = event.target.closest('[data-view]');
    if (button) {
      const source = button.dataset.view === 'source';
      document.querySelector('#document-preview').hidden = source;
      document.querySelector('#document-source').hidden = !source;
      document.querySelectorAll('[data-view]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    }
    if (event.target.closest('[data-refresh-workspace]')) refreshWorkspace();
  });
  window.addEventListener('popstate', () => location.reload());
})();
