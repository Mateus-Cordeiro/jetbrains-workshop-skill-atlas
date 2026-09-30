# Terminal UI testing

Last verified: 2026-09-30.

Textual can animate scrolling when a link receives focus. In headless tests,
`await pilot.pause()` alone can return while that animation is still running;
asserting that the focused link is inside the viewport can then fail
intermittently, especially at 40-column widths. After focusing a link, use
`await pilot.wait_for_scheduled_animations()` before checking its region.

The narrow-layout tests in
[test_cli_output.py](../tests/integration/test_cli_output.py) exercise this
with all three result views, grouped locations, and long metadata. Keep geometry
assertions: waiting for the animation fixes the race without loosening the
visibility requirement. The presentation contract belongs in
[the architecture](../spec/architecture.md#shared-cli-results-presentation).
