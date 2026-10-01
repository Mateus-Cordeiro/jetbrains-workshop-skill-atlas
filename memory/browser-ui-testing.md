# Browser UI testing

Last verified: 2026-10-01.

## Scans that refresh an open workspace

The `scan_from_home` fixture in
[browser conftest](../tests/browser/conftest.py) submits through the real homepage
scan dialog, then returns to the original workspace URL before allowing the scan to
finish. It holds `web_environment.scan_gate` during navigation so the destination
page receives a running job and exercises polling plus automatic workspace
refresh. Use it for scan-driven selection, filtering, and description tests;
repository detail pages have no scan control. Accepted submissions close the
modal, so open it again before each subsequent submission. Use `#scan-github`
for the toolbar opener: the empty catalog also has a **Scan GitHub…** button.
Role locators exclude controls in a closed dialog; reopen it when checking
retained input, as in [the layout tests](../tests/browser/test_catalog_layout.py).

The helper reloads the destination page. For a race involving an in-memory
interaction, perform that interaction after the helper returns and hold the
relevant fragment response, as in
[the filter tests](../tests/browser/test_filters.py). Keep GitHub transport and
credential substitution in [the shared fixtures](../tests/conftest.py).

## Held responses

When holding one catalog request while a later refresh must proceed, register
the Playwright route with `times=1`. Removing the handler with `unroute` while
the request is pending can let it continue, so a later
`route.fulfill()` fails with “Route is already handled”. The
[repository-control regression](../tests/browser/test_repository_controls_ui.py)
retains the response from before removal and fulfills it after the refreshed
list arrives; it also asserts that exactly one request was held.

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

## Shared page geometry

The [catalog layout regression](../tests/browser/test_catalog_layout.py) compares
navigation and link rectangles across Repositories and Explore at 390, 1360, and
1920 pixels, including generated groups. A page-specific `main` width of 1600
versus the shared 1440 passed the 1360-pixel screenshots and color assertions but
moved navigation 80 pixels at 1920. Include a viewport above the shared maximum
width when checking page consistency; same colors do not establish same layout.
The [shared catalog template](../src/skill_atlas/web/templates/catalog.html) owns
navigation; graph CSS no longer changes the outer page container.

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

## Installation previews and Back navigation

Chromium can restore edited GET-form values when navigating Back, leaving an
agent dropdown inconsistent with the URL and server-rendered destination preview.
Restoring controls in a delayed `pageshow` callback caused another race: it could
reset a user's newly chosen agent before preview submission. The installation
selection form disables autocomplete so the server-rendered URL selection remains
authoritative, without deferred JavaScript resetting live edits. The document-to-Claude
flow in [installation browser tests](../tests/browser/test_installations.py) checks
agent selection, preview, installation and Back navigation.

An element's presence does not mean a deferred script has attached submit handlers.
The original mutation forms could submit a native GET when Enter arrived early;
the failure reproduced in Linux CI after a successful macOS suite. The delayed-script
regression holds `installations.js` with a one-shot route and reloads only to
`commit`, then verifies all mutation buttons stay disabled and implicit Enter
does not navigate. Release the script before teardown and check that conflict
buttons remain disabled. Keyboard tests must wait for the action to become enabled
before focusing it. This verifies the UI safeguard rather than hiding the race
with sleeps or a test-only readiness marker.

When injecting a local edit after a successful installation/no-op, wait for its
page refresh to finish first. The success notice can briefly appear in the old
document before reload. Injecting during that interval makes the new page correctly
disable Uninstall, instead of exercising a conflict that appeared after rendering.
The lifecycle regression wraps the no-op click in `expect_navigation` before
writing the local file.
