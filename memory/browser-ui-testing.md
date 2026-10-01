# Browser UI testing

Last verified: 2026-10-01.

## Scans that refresh an open workspace

The `scan_from_home` fixture in
[browser conftest](../tests/browser/conftest.py) submits through the real homepage
form, then returns to the original workspace URL before allowing the scan to
finish. It holds `web_environment.scan_gate` during navigation so the destination
page receives a running job and exercises polling plus automatic workspace
refresh. Use it for scan-driven selection, filtering, and description tests;
repository detail pages have no scan control.

The helper reloads the destination page. For a race involving an in-memory
interaction, perform that interaction after the helper returns and hold the
relevant fragment response, as in
[the filter tests](../tests/browser/test_filters.py). Keep GitHub transport and
credential substitution in [the shared fixtures](../tests/conftest.py).

## Group generation fixtures

The shared [Web environment](../tests/web_environment.py) substitutes both GitHub
and Ollama transports. Ollama requests are handled before the GitHub authorization
assertion and explicitly require no Authorization header. Use `grouping_gate`,
`grouping_status`, and `grouping_content` to control inference without replacing
the real generation service, validation, jobs, or storage. `grouping_requests`
records model calls separately from GitHub `requests`. Browser teardown must
release the grouping gate before stopping the server, which waits for active jobs.

Graph fixtures can supply distinct responses with `grouping_content_by_perspective`;
one explicit generation makes two calls from the same metadata snapshot. An
invalid second response must preserve both saved views. The
[group browser tests](../tests/browser/test_skill_groups.py) cover shared graph
nodes, separately usable directory links, and pointer/keyboard interactions.
Keep pytest module basenames distinct across directories; duplicate
`test_grouping.py` files caused combined unit/integration collection to fail.

After full-page navigation, wait for the destination URL with
`wait_until="domcontentloaded"` before focusing and sending keyboard input. A
Linux trace showed Enter reaching the Generate button before HTMX initialized:
the native click fired but no request followed. Element presence and focus alone
do not establish script readiness; retain keyboard coverage instead of fixed sleeps.

## G6 and HTMX lifecycle

Initialize the graph after HTMX settles and give G6 an anonymous renderer container
inside the stable host. HTMX copies attributes between matching IDs during swaps;
copying G6's runtime styles via `setAttribute` triggered CSP rejection and stacked
its four canvas layers vertically. The private container plus external grid CSS
fixes the layer positioning without relaxing CSP. G6 uses multiple canvases by
design; tests should not assume there is only one.

Serialize graph renders and avoid querying removed node IDs during animations.
Rapid switching and directory focus reproduced G6 “Unknown element type” errors.
The graph host's `data-ready` marks completion for browser and screenshot checks.
The desktop graph scenario uses reduced motion, real G6, deterministic placements,
and the shared mock transport. Mouse tests interact with the rendered canvas rather
than substituting a graph implementation. Session storage holds only opaque IDs
and coordinates; storage and renderer-failure cases retain usable directory links.

## Standalone browser demos

When adapting the fixtures for a standalone [PR demo](../.agents/skills/pr-demo/SKILL.md),
use `pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)`
alongside the browser's loopback-only route guard. Calling `disable_socket()`
first blocks the server's socket creation even after allowing hosts. The browser
tests avoid that combination through their `allow_hosts` marker. Continue to
substitute both GitHub transport and credential lookup with the shared fixtures.

## Desktop visual checkpoints

The [Playwright Test pilot](../tests/browser/visual/desktop.spec.ts) and Python
browser suite share [the Web environment](../tests/web_environment.py). Use the
[documented container commands](../README.md#desktop-visual-tests) for baseline
comparisons and recordings; host macOS fonts are not the Linux baseline fonts.

The [Docker image](../tests/browser/visual/Dockerfile) copies source and tests at
build time. Rebuild it with the documented runner before using it for additional
Python browser checks; a pre-existing `skill-atlas-visual:local` tag may contain
older code. Mounting only a changed test does not update the application snapshot.

When pausing Playwright's clock for scan screenshots, advance it until HTMX's
settling/request classes disappear before interacting with replaced controls.
Visible failure text can arrive before HTMX initializes the new retry form.
A repeat run caught a native GET navigation on Retry instead of the intended
HTMX POST because its settling timer was still paused. The scan scenario's
`settle` helper drives the clock while checking readiness; three consecutive
runs passed without changing screenshots or tolerances after that fix.
