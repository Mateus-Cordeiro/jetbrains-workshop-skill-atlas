# Terminal UI testing

Last verified: 2026-09-30.

Textual defers focus scrolling until a refresh, then animates it. In headless
tests, `await pilot.pause()` alone can return while the animation is running,
and `await pilot.wait_for_scheduled_animations()` alone can check for completion
before deferred scrolling starts. After focusing a link, call
`await pilot.pause()` to drain pending focus events, then
`await pilot.wait_for_scheduled_animations()` before checking its region. Both
steps are needed to avoid intermittent viewport assertions, especially at
40-column widths.

The post-merge macOS/Python 3.13 failure in
[CI run 36733345241](https://github.com/Mateus-Cordeiro/jetbrains-workshop-skill-atlas/actions/runs/36733345241/job/109948479833)
exposed the incomplete animation-only wait. Temporary diagnostic logging
confirmed that it could return with scrolling still active. Extending scroll
duration to one second reproduced the assertion failure; draining focus events
before the animation wait passed the same experiment. Keep timing changes in
diagnostic experiments rather than weakening the visibility assertions.

The narrow-layout tests in
[test_cli_output.py](../tests/integration/test_cli_output.py) exercise this
with all three result views, grouped locations, and long metadata. Keep geometry
assertions: draining focus events and waiting for the animation avoids the race
without loosening the visibility requirement. The presentation contract belongs in
[the architecture](../spec/architecture.md#shared-cli-results-presentation).
