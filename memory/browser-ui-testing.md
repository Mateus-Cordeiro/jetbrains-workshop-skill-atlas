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
