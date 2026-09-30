---
name: pr-demo
description: Create and verify short videos or screenshots demonstrating visible skill-atlas changes for a pull request, including browser and terminal interactions. Use when preparing a PR demo; omit recordings for changes without a useful visual demonstration.
---

# PR demo

Produce reviewable evidence of the behavior changed by a PR. Follow
[AGENTS.md](../../../AGENTS.md#pull-request-descriptions) for when a demo is
expected and use the [PR template](../../../.github/pull_request_template.md)
for placement. Respect a user's requested format or scope.

## Choose the scenario

- Read the final diff and relevant tests. Identify the action and visible result
  a reviewer needs to see; draft a short sequence before recording.
- Prefer one focused clip per meaningful scenario, typically 15–45 seconds.
  Use multiple clips for distinct flows and screenshots for static changes.
  Add before/after only when it clarifies the difference; label both versions.
- Record the actual application from the code being reviewed. If changes affect
  the demonstrated behavior after capture, record it again. Keep any base-version
  comparison isolated from ongoing work and use comparable fixture data.

## Prepare a reproducible environment

- Use the checkout's locked environment and the existing setup instructions in
  [README.md](../../../README.md#local-development). Use synthetic, predictable
  data in a temporary catalog; set `SKILL_ATLAS_DB` explicitly for CLI launches.
  Do not use the developer's normal catalog or private repository content.
- For browser demos, adapt the real application and catalog setup in
  [tests/conftest.py](../../../tests/conftest.py) and the loopback server/browser
  lifecycle in [tests/browser/conftest.py](../../../tests/browser/conftest.py).
  Seed only the data the scenario needs. Substitute GitHub transport and
  credential lookup as those fixtures do; clearing token environment variables
  alone still permits the application's GitHub CLI credential fallback.
- Keep the real UI and application services. Mock external responses, not the
  behavior under review, and disclose simulated delays or failures in captions.
  Preserve the fixtures' external-network blocking when adapting their setup.
- Store captures and temporary helpers outside version control, such as under
  the ignored `test-results/pr-demo/` directory. Keep deliverable media available
  until it is attached or handed off. Stop demo servers and release temporary
  resources after capture.

## Capture the interaction

### Browser

For a scenario covered by the desktop visual pilot, generate its demo from the
committed Playwright Test scenario rather than maintaining a separate recording
script. Run `ATLAS_DEMO=1 bash tests/browser/visual/run-container.sh`, optionally
with `--grep` to select a scenario. This compares all named screenshots and
records the same interactions with review pacing. See the
[README](../../../README.md#desktop-visual-tests) for the pinned environment,
baseline review, report, and artifact commands. Preserve videos needed for
delivery under `test-results/pr-demo/` before another run replaces the report.
Disclose the fixture-controlled scan delays and failures in captions. The pilot
covers desktop filtering, descriptions/document views, and scan failure/retry;
do not imply it covers every browser flow or mobile visuals.

For other browser scenarios, prefer the project's existing Playwright
installation. Use a dedicated browser context with a readable viewport and matching
`record_video_size`; set `record_video_dir` before creating the page. Retain the
page's video handle and close the context before saving or inspecting the file,
because Playwright finalizes the recording on context close. The Python browser
fixture captures screenshots only; the Playwright Test pilot records successful
runs only when demo mode is enabled, otherwise retaining failure videos.

Use stable accessible locators and wait for visible states. Pace actions so a
reviewer can follow them and leave the final result visible briefly. Demonstrate
loading, keyboard navigation, or narrow layouts when they are part of the change.
Keep unrelated tabs, developer tools, and setup output outside the capture.

### Terminal

Use an available terminal or window recorder with readable text and consistent
dimensions. Interactive CLI results require both stdin and stdout to be terminals;
record a real terminal session rather than piped output. Show the command, the
relevant interaction, and its result. A raw terminal transcript is not an inline
video; render it with available tooling or provide a screenshot when suitable.

If recording tooling is unavailable, use an adequate screenshot or report the
missing capability. Do not claim that a screenshot demonstrates timing or an
interaction it cannot show.

## Review and deliver

1. Play every clip from start to finish using an available viewer. Verify readable
   text, the intended interaction and final state, and absence of unrelated or
   sensitive content. If playback is unavailable, inspect frames and metadata as
   a partial check and explicitly report that playback remains unverified.
2. Trim irrelevant setup and idle time without hiding the behavior being reviewed.
   Preserve meaningful timing for loading or race-condition demonstrations. Check
   playback again after editing or conversion.
3. Deliver a GitHub-compatible video, preferably MP4 with H.264 for broad playback
   compatibility; keep Playwright's WebM when it works for the target. If conversion
   is needed, use available tooling and convert the media rather than renaming its
   extension. Use descriptive filenames and a caption for each clip or screenshot
   explaining the action and expected result, including any simulated conditions.
4. When PR editing and media upload are authorized, use the
   [github-pr-media skill](../github-pr-media/SKILL.md) to attach the reviewed files
   in the Demo section and verify the saved attachments. Read that skill directly
   if it is not discovered automatically; it owns browser upload methods, native
   picker fallback, and upload verification. If upload is deferred or blocked,
   hand off the media paths and captions with the precise limitation and any
   remaining verification steps. State capture or playback limitations as well.

Do not substitute a demo for the validation required by AGENTS.md. Add reusable
helpers only when repeated setup or capture work justifies maintaining them.
