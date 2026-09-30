# Browser UI testing

Last verified: 2026-09-30.

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

When pausing Playwright's clock for scan screenshots, advance it until HTMX's
settling/request classes disappear before interacting with replaced controls.
Visible failure text can arrive before HTMX initializes the new retry form.
A repeat run caught a native GET navigation on Retry instead of the intended
HTMX POST because its settling timer was still paused. The scan scenario's
`settle` helper drives the clock while checking readiness; three consecutive
runs passed without changing screenshots or tolerances after that fix.
