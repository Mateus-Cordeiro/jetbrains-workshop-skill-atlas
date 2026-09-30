// Catalog filtering owns list updates only; document requests remain in app.js.
(() => {
  let request;
  let revision = 0;
  let timer;
  const expanded = new Set(history.state?.catalogExpanded || []);
  const collapsedMatches = new Set(history.state?.catalogCollapsedMatches || []);
  const input = () => document.querySelector('#skill-filter');
  const query = () => input()?.value ?? new URLSearchParams(location.search).get('q') ?? '';
  const narrow = matchMedia('(max-width: 600px)');

  function searchVisibility() {
    const controls = document.querySelector('.filter-controls');
    if (!controls) return;
    if (query() || document.activeElement === input()) controls.classList.add('is-open');
    controls.querySelector('.search-toggle').setAttribute('aria-expanded',
      String(!narrow.matches || controls.classList.contains('is-open')));
  }

  narrow.addEventListener('change', searchVisibility);

  function saveState() {
    history.replaceState({...history.state, catalogExpanded: [...expanded],
      catalogCollapsedMatches: [...collapsedMatches]}, '', location.href);
  }

  function setQuery(url, value) {
    if (value) url.searchParams.set('q', value);
    else url.searchParams.delete('q');
    return url;
  }

  function selection() {
    const pane = document.querySelector('#workspace');
    document.querySelectorAll('.similar-link').forEach(link => {
      const url = setQuery(new URL(link.href), query());
      url.searchParams.set('return_to', location.pathname + location.search);
      link.href = url;
    });
    if (['similar', 'groups'].includes(pane?.dataset.mode)) return;
    if (!pane) return;
    let visible = false;
    document.querySelectorAll('.skill-link').forEach(link => {
      const selected = link.dataset.skillPath === pane.dataset.selectedPath;
      link.toggleAttribute('aria-current', selected);
      if (selected) {
        link.setAttribute('aria-current', 'true');
        visible = true;
      }
      link.href = setQuery(new URL(link.href), query());
    });
    const notice = document.querySelector('#selection-filter-notice');
    if (notice) notice.hidden = !pane.dataset.selectedPath || visible || !query().trim();
    const back = document.querySelector('.back-link');
    if (back) back.href = setQuery(new URL(back.href), query());
  }

  async function html(url, controller) {
    const timeout = setTimeout(() => controller.abort(), 35000);
    try {
      const response = await fetch(url, {headers: {'HX-Request': 'true'}, signal: controller.signal});
      if (!response.ok) throw new Error('Catalog request failed');
      return await response.text();
    } finally {
      clearTimeout(timeout);
    }
  }

  async function expand(group, open) {
    const button = group.querySelector('.repository-toggle');
    const panel = group.querySelector('.repository-skills');
    button.setAttribute('aria-expanded', String(open));
    panel.hidden = !open;
    if (!open || panel.dataset.loaded === 'true' || panel.getAttribute('aria-busy') === 'true') return;
    panel.setAttribute('aria-busy', 'true');
    panel.textContent = 'Loading skills…';
    const params = new URLSearchParams({repository_url: group.dataset.repository, q: query()});
    try {
      const content = await html('/fragments/repository-skills?' + params, new AbortController());
      if (!group.isConnected) return;
      panel.innerHTML = content;
      panel.dataset.loaded = 'true';
      document.dispatchEvent(new Event('atlas:skills-updated'));
    } catch {
      if (!group.isConnected) return;
      panel.innerHTML = '<p class="filter-empty" role="alert">Could not load skills. <button type="button" data-retry-expansion>Retry</button></p>';
    } finally {
      panel.removeAttribute('aria-busy');
    }
  }

  function restore() {
    searchVisibility();
    const results = document.querySelector('.repository-results');
    const count = document.querySelector('#repository-count');
    if (count && results) count.textContent = results.dataset.repositoryCount;
    const skillCount = document.querySelector('#skill-count');
    const skills = document.querySelector('#skill-results [data-skill-count]');
    if (skillCount && skills) skillCount.textContent = skills.dataset.skillCount;
    if (results?.dataset.catalogEmpty === 'true') {
      document.querySelector('#repository-form').hidden = false;
      document.querySelector('#add-repository').setAttribute('aria-expanded', 'true');
    }
    const filtering = Boolean(query().trim());
    document.querySelectorAll('.repository-group').forEach(group => {
      expand(group, filtering ? !collapsedMatches.has(group.dataset.repository) : expanded.has(group.dataset.repository));
    });
    const clear = document.querySelector('.filter-input [data-clear-filter]');
    if (clear) clear.hidden = !query();
    selection();
  }

  function cancel() {
    clearTimeout(timer);
    revision++;
    request?.abort();
    document.querySelector('#skill-results')?.removeAttribute('aria-busy');
  }

  async function refresh() {
    cancel();
    const current = revision;
    const pane = document.querySelector('#workspace');
    const target = document.querySelector(pane ? '#skill-results' : '#repositories');
    if (!target) return;
    const params = new URLSearchParams({q: query()});
    if (pane) {
      params.set('repository_url', pane.dataset.repository);
      params.set('skill_path', pane.dataset.selectedPath || '');
    }
    request = new AbortController();
    target.setAttribute('aria-busy', 'true');
    try {
      const content = await html((pane ? '/fragments/skills?' : '/fragments/repositories?') + params, request);
      if (current !== revision || !target.isConnected) return;
      target.innerHTML = content;
      htmx.process(target);
      document.querySelector('#filter-error')?.replaceChildren();
      restore();
      document.dispatchEvent(new Event('atlas:skills-updated'));
    } catch {
      if (current !== revision || !target.isConnected) return;
      document.querySelector('#filter-error').innerHTML = '<p>Could not update skills. Previous results are still shown. <button type="button" data-retry-filter>Retry</button></p>';
    } finally {
      if (current === revision) target.removeAttribute('aria-busy');
    }
  }

  function changed(immediate = false) {
    cancel();
    searchVisibility();
    if (!query().trim()) collapsedMatches.clear();
    history.replaceState(history.state, '', setQuery(new URL(location.href), query()));
    saveState();
    const clear = document.querySelector('.filter-input [data-clear-filter]');
    if (clear) clear.hidden = !query();
    selection();
    if (immediate) refresh();
    else timer = setTimeout(refresh, 150);
  }

  document.addEventListener('input', event => {
    if (event.target.id === 'skill-filter' && !event.isComposing) changed();
  });
  document.addEventListener('compositionend', event => {
    if (event.target.id === 'skill-filter') changed();
  });
  document.addEventListener('submit', event => {
    if (!event.target.matches('.skill-filter')) return;
    event.preventDefault();
    changed(true);
  });
  document.addEventListener('keydown', event => {
    if (event.target.id === 'skill-filter' && event.key === 'Escape') {
      event.preventDefault();
      input().value = '';
      changed(true);
    }
  });
  document.addEventListener('click', event => {
    const search = event.target.closest('.search-toggle');
    if (search) {
      const controls = search.closest('.filter-controls');
      if (!query()) controls.classList.toggle('is-open');
      if (controls.classList.contains('is-open')) input().focus();
      searchVisibility();
    }
    if (event.target.closest('[data-clear-filter]')) {
      input().value = '';
      input().focus();
      changed(true);
    }
    if (event.target.closest('[data-retry-filter]')) refresh();
    const toggle = event.target.closest('.repository-toggle');
    if (toggle) {
      const group = toggle.closest('.repository-group');
      const open = toggle.getAttribute('aria-expanded') !== 'true';
      const state = query().trim() ? collapsedMatches : expanded;
      const remember = query().trim() ? !open : open;
      if (remember) state.add(group.dataset.repository);
      else state.delete(group.dataset.repository);
      saveState();
      expand(group, open);
    }
    const retry = event.target.closest('[data-retry-expansion]');
    if (retry) expand(retry.closest('.repository-group'), true);
  });
  document.addEventListener('DOMContentLoaded', restore);
  document.addEventListener('atlas:skills-updated', selection);
  window.atlasFilters = {query, refresh, restore, selection, cancel};
})();
