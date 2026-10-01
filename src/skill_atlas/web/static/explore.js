/* G6 owns rendering/gestures. This module owns graph view state and navigation. */
(() => {
  const count = (n, noun) => `${n} ${noun}${n === 1 ? '' : 's'}`;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let dispose = () => {};
  let currentRoot;

  function initialize() {
    const root = document.querySelector('#workspace[data-mode="groups"]');
    if (root === currentRoot) return;
    dispose();
    currentRoot = root;
    if (!root) return;
    const theme = getComputedStyle(root);
    const color = name => theme.getPropertyValue(name).trim();
    const palette = Array.from({length: 5}, (_, index) => color(`--graph-color-${index + 1}`));
    const payload = JSON.parse(root.querySelector('#explore-data').dataset.graph);
    const host = root.querySelector('#skill-graph');
    // An anonymous renderer container keeps G6's runtime styles out of HTMX's
    // attribute settling, which would reapply inline styles under our strict CSP.
    const renderer = document.createElement('div');
    renderer.className = 'graph-renderer';
    host.append(renderer);
    const directory = root.querySelector('#group-directory');
    const tooltip = root.querySelector('#graph-tooltip');
    const storageKey = 'skill-atlas.graph-view';
    let saved = {};
    try { saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}') || {}; } catch { /* Optional view state. */ }
    let perspective = root.dataset.perspective;
    let graph;
    let destroyed = false;
    let visible = {nodes: [], edges: []};
    let drawing = Promise.resolve();
    let revision = 0;
    let busy = false;
    let dragged = false;
    const state = {};
    for (const [mode, data] of Object.entries(payload.perspectives)) {
      const prior = saved[mode] || {};
      const valid = new Set([...data.groups, ...data.skills].map(n => n.id));
      state[mode] = {
        expanded: new Set(Array.isArray(prior.expanded) ? prior.expanded.filter(id => data.groups.some(g => g.id === id)) : []),
        positions: Object.fromEntries(Object.entries(prior.positions || {}).filter(([id, p]) =>
          valid.has(id) && Array.isArray(p) && p.length === 2 && p.every(v => Number.isFinite(v) && Math.abs(v) < 1e6))),
      };
    }
    const data = () => payload.perspectives[perspective];
    const view = () => state[perspective];
    function persist() {
      const serial = Object.fromEntries(Object.entries(state).map(([key, value]) =>
        [key, {expanded: [...value.expanded], positions: value.positions}]));
      try { sessionStorage.setItem(storageKey, JSON.stringify(serial)); } catch { /* Browsing works without storage. */ }
    }
    function capture() {
      if (!graph || destroyed || busy) return;
      for (const node of graph.getNodeData()) {
        const position = graph.getElementPosition(node.id);
        if (position) view().positions[node.id] = position.slice(0, 2);
      }
      persist();
    }
    function element(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }
    function renderDirectory() {
      const fragment = document.createDocumentFragment();
      const lookup = new Map(data().skills.map(skill => [skill.id, skill]));
      for (const group of data().groups) {
        const section = element('section', 'graph-group');
        const button = element('button');
        button.type = 'button';
        button.dataset.group = group.id;
        button.setAttribute('aria-expanded', String(view().expanded.has(group.id)));
        button.setAttribute('aria-controls', 'members-' + group.id);
        button.setAttribute('aria-label', group.title + ', ' + count(group.members.length, 'skill'));
        const marker = element('span', 'group-marker');
        marker.setAttribute('aria-hidden', 'true');
        button.append(marker, element('span', 'group-label', group.title),
          element('span', 'group-total', group.members.length), element('span', 'group-chevron', '›'));
        const list = element('ul', 'graph-members');
        list.id = 'members-' + group.id;
        list.hidden = !view().expanded.has(group.id);
        for (const id of group.members) {
          const skill = lookup.get(id);
          const item = element('li');
          const link = element('a', '', skill.title);
          link.href = skill.href;
          link.dataset.skill = id;
          link.append(element('small', '', skill.repository));
          item.append(link);
          list.append(item);
        }
        section.append(button, list);
        fragment.append(section);
      }
      const focused = document.activeElement?.dataset.group;
      directory.replaceChildren(fragment);
      if (focused) directory.querySelector(`[data-group="${focused}"]`)?.focus({preventScroll: true});
    }
    function build() {
      const groups = data().groups;
      const positions = view().positions;
      const width = host.clientWidth, height = host.clientHeight;
      const radius = Math.max(150, groups.length * 38);
      groups.forEach((group, i) => {
        if (positions[group.id]) return;
        const angle = -Math.PI / 2 + i * Math.PI * 2 / groups.length;
        positions[group.id] = groups.length === 1 ? [width / 2, height / 2 - 20]
          : groups.length === 2 ? [width * (i ? .72 : .28), height / 2 - 20]
          : [width / 2 + radius * Math.cos(angle), height / 2 + radius * .85 * Math.sin(angle)];
      });
      const membership = new Map();
      const edges = [];
      groups.forEach((group, index) => {
        if (!view().expanded.has(group.id)) return;
        group.members.forEach(id => {
          if (!membership.has(id)) membership.set(id, []);
          membership.get(id).push(group);
          edges.push({id: `${group.id}-${id}`, source: group.id, target: id,
            states: [], style: {opacity: 1, stroke: palette[index % palette.length], strokeOpacity: .45, lineWidth: 1.2}});
        });
      });
      const nodes = groups.map((group, index) => ({
        id: group.id, type: 'circle', states: [], data: {kind: 'group'},
        style: {opacity: 1, x: positions[group.id][0], y: positions[group.id][1], size: 94,
          fill: color('--graph-surface'), stroke: palette[index % palette.length], lineWidth: 1.6,
          shadowColor: palette[index % palette.length] + '22', shadowBlur: 24,
          halo: true, haloStroke: palette[index % palette.length], haloLineWidth: 10, haloStrokeOpacity: .06,
          iconText: String(group.members.length), iconFill: color('--ink'), iconFontSize: 27,
          labelText: group.title, labelFill: color('--ink'), labelFontSize: 13, labelFontWeight: 500,
          labelPlacement: 'bottom', labelOffsetY: 14, labelWordWrap: true, labelMaxWidth: 180, labelMaxLines: 2,
          cursor: 'pointer'},
      }));
      let index = 0;
      for (const skill of data().skills) {
        const parents = membership.get(skill.id);
        if (!parents) continue;
        if (!positions[skill.id]) {
          const center = parents.reduce((p, g) => [p[0] + positions[g.id][0] / parents.length,
            p[1] + positions[g.id][1] / parents.length], [0, 0]);
          // Place only newly revealed nodes; dragged and existing nodes stay put.
          const free = point => !nodes.some(n => Math.abs(n.style.x - point[0]) < 185 && Math.abs(n.style.y - point[1]) < 90);
          const candidates = [];
          for (let y = 100; y <= height - 90; y += 95) {
            for (let x = 105; x <= width - 100; x += 190) if (free([x, y])) candidates.push([x, y]);
          }
          candidates.sort((a, b) => Math.hypot(a[0] - center[0], a[1] - center[1]) - Math.hypot(b[0] - center[0], b[1] - center[1]));
          let candidate = candidates[0];
          for (let attempt = 0; !candidate && attempt < 150; attempt++) {
            const angle = (index * 2.4 + attempt * .85);
            const distance = 155 + Math.floor(attempt / 8) * 45;
            const point = [center[0] + Math.cos(angle) * distance, center[1] + Math.sin(angle) * distance];
            if (free(point) || attempt === 149) candidate = point;
          }
          positions[skill.id] = candidate;
        }
        index++;
        nodes.push({id: skill.id, type: 'rect', states: [], data: {kind: 'skill'},
          style: {opacity: 1, x: positions[skill.id][0], y: positions[skill.id][1], size: [174, 46], radius: 9,
            fill: color('--tint'), stroke: color('--graph-skill-stroke'), lineWidth: 1, cursor: 'pointer',
            labelText: skill.title, labelFill: color('--ink'), labelFontSize: 14,
            labelPlacement: 'center', labelWordWrap: true, labelMaxWidth: 150, labelMaxLines: 2}});
      }
      root.querySelector('#graph-count').textContent = `${count(groups.length, 'group')} · ${membership.size} visible skills`;
      root.querySelector('#graph-announcement').textContent = `${groups.length} ${perspective} groups, ${membership.size} skills visible.`;
      return {nodes, edges};
    }
    function failure() {
      if (destroyed) return;
      busy = false;
      const empty = root.querySelector('#graph-empty');
      empty.hidden = false;
      empty.querySelector('h2').textContent = 'Graph unavailable';
      empty.querySelector('p').textContent = 'You can still explore every group and skill in the list.';
    }
    function redraw(fit = false) {
      const next = build();
      const requested = ++revision;
      busy = true;
      host.dataset.ready = 'false';
      renderDirectory();
      persist();
      if (!graph) { failure(); return; }
      drawing = drawing.then(async () => {
        if (destroyed || !graph || requested !== revision) return;
        graph.setData(next);
        await graph.render();
        visible = next;
        renderer.querySelectorAll('canvas').forEach(canvas => { canvas.tabIndex = -1; });
        if (fit && next.nodes.length) {
          await graph.fitView({}, reduced.matches ? false : {duration: 300});
          if (graph.getZoom() > 1) await graph.zoomTo(1, false);
        }
        if (requested === revision) { busy = false; host.dataset.ready = 'true'; }
      }).catch(failure);
    }
    function toggle(id) {
      capture();
      view().expanded.has(id) ? view().expanded.delete(id) : view().expanded.add(id);
      tooltip.hidden = true;
      redraw(true);
    }
    function highlight(id) {
      if (!graph || destroyed || busy) return;
      const connected = new Set([id]);
      for (const edge of visible.edges) {
        if (edge.source === id || edge.target === id) {
          connected.add(edge.id); connected.add(edge.source); connected.add(edge.target);
        }
      }
      const states = Object.fromEntries([...visible.nodes, ...visible.edges].map(n =>
        [n.id, !id ? [] : connected.has(n.id) ? ['lit'] : ['dim']]));
      graph.setElementState(states, false).catch(failure);
    }
    function tip(id, event) {
      if (!graph || destroyed || busy || !graph.hasNode(id)) return;
      const group = data().groups.find(g => g.id === id);
      const skill = data().skills.find(s => s.id === id);
      if (!group && !skill) return;
      tooltip.replaceChildren(element('strong', '', (group || skill).title));
      if (group) tooltip.append(element('p', '', `${count(group.members.length, 'skill')} · Click to ${view().expanded.has(id) ? 'collapse' : 'expand'}`));
      else tooltip.append(element('p', '', skill.repository), element('p', '', skill.description));
      const rect = host.getBoundingClientRect();
      const point = graph.getViewportByCanvas(graph.getElementPosition(id));
      const x = event?.client?.x ? event.client.x - rect.left : point[0];
      const y = event?.client?.y ? event.client.y - rect.top : point[1];
      tooltip.hidden = false;
      tooltip.style.left = Math.max(8, Math.min(x + 18, rect.width - tooltip.offsetWidth - 10)) + 'px';
      tooltip.style.top = Math.max(50, Math.min(y + 18, rect.height - tooltip.offsetHeight - 65)) + 'px';
      highlight(id);
    }
    function switchPerspective(mode, push = true) {
      capture();
      perspective = mode;
      root.dataset.perspective = mode;
      root.querySelectorAll('[data-perspective]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.perspective === mode)));
      root.querySelector('#graph-mode').textContent = mode.toUpperCase();
      root.querySelector('#directory-title').textContent = mode[0].toUpperCase() + mode.slice(1);
      root.querySelector('#graph-stale').hidden = !data().stale;
      const empty = root.querySelector('#graph-empty');
      empty.hidden = !!data().groups.length;
      if (!data().groups.length && data().generated) empty.querySelector('h2').textContent = 'No saved skills';
      else if (!data().groups.length) empty.querySelector('h2').textContent = 'Discover the connections';
      tooltip.hidden = true;
      if (push) history.pushState(history.state, '', '/explore?perspective=' + mode);
      redraw(true);
    }
    function click(event) {
      const mode = event.target.closest('button[data-perspective]');
      if (mode) switchPerspective(mode.dataset.perspective);
      const group = event.target.closest('[data-group]');
      if (group) toggle(group.dataset.group);
      if (event.target.closest('[data-skill]')) capture();
      const action = event.target.closest('[data-graph-action]')?.dataset.graphAction;
      if (!graph || !action) return;
      if (action === 'reset') { view().positions = {}; redraw(true); }
      else if (action === 'fit') graph.fitView({}, reduced.matches ? false : {duration: 250}).catch(failure);
      else graph.zoomTo(Math.min(2.5, Math.max(.15, graph.getZoom() * (action === 'in' ? 1.25 : .8))), false).catch(failure);
    }
    function focus(event) {
      const id = event.target.closest('[data-group], [data-skill]');
      if (id) tip(id.dataset.group || id.dataset.skill);
    }
    root.addEventListener('click', click);
    directory.addEventListener('focusin', focus);
    directory.addEventListener('focusout', () => { tooltip.hidden = true; highlight(); });
    const onPageHide = () => capture();
    window.addEventListener('pagehide', onPageHide);
    const observer = new ResizeObserver(() => { if (graph && !destroyed) graph.resize(); });
    try {
      graph = new G6.Graph({container: renderer, width: host.clientWidth, height: host.clientHeight,
        autoResize: false, animation: !reduced.matches, zoomRange: [.15, 2.5], padding: host.clientWidth < 600 ? [70, 35, 90, 35] : [80, 65, 100, 65],
        behaviors: ['drag-canvas', 'zoom-canvas', {type: 'drag-element', animation: false, onFinish: () => { capture(); }}],
        node: {state: {dim: {opacity: .2}, lit: {lineWidth: 2.5, shadowBlur: 30}}},
        edge: {type: 'line', state: {dim: {opacity: .1}, lit: {strokeOpacity: 1, lineWidth: 2}}},
      });
      graph.on('node:click', event => {
        if (dragged) return;
        const id = event.target.id;
        if (data().groups.some(group => group.id === id)) toggle(id);
        else { const skill = data().skills.find(s => s.id === id); if (skill) { capture(); location.assign(skill.href); } }
      });
      graph.on('node:pointerenter', event => tip(event.target.id, event));
      graph.on('node:pointerleave', () => { tooltip.hidden = true; highlight(); });
      graph.on('node:pointerdown', () => { dragged = false; });
      graph.on('node:dragstart', () => { dragged = true; tooltip.hidden = true; });
      observer.observe(host);
      redraw(true);
    } catch { renderDirectory(); failure(); }
    dispose = () => {
      capture();
      destroyed = true;
      observer.disconnect();
      window.removeEventListener('pagehide', onPageHide);
      // Finish outstanding render work before destroying its canvas.
      drawing.finally(() => graph?.destroy());
    };
  }
  document.addEventListener('DOMContentLoaded', initialize);
  document.addEventListener('htmx:afterSettle', initialize);
})();
