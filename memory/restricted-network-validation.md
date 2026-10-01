# Validation with restricted package downloads

Last verified: 2026-10-01.

Some sandboxes reach `pypi.org` and npm but block wheel downloads from
`files.pythonhosted.org`, the Playwright browser CDN, and Microsoft Container
Registry blobs. The required checks can still run locally without editing the
lockfile or manifests; report anything that could not run, as
[AGENTS.md](../AGENTS.md#required-local-checks) requires.

## Python environment

`uv sync --locked` only audits an environment that already matches
[uv.lock](../uv.lock). Download the exact wheels named in the lockfile through
an available mirror into a local directory, install the
`uv export --locked --all-groups --no-emit-project` pins with
`uv pip install --no-index --find-links`, and set `UV_NO_INDEX=1` with
`UV_FIND_LINKS` pointing at that directory. Use a fresh `UV_CACHE_DIR`: cached
index pages still name the blocked host.

Build isolation resolves `hatchling` from the index, so editable installs and
`uv build` need `--no-build-isolation` with `hatchling` and `editables` in the
build environment. After one such sync, plain `uv sync --locked` reports the
environment as checked without downloads.

## Python browser tests

When `playwright install chromium` is blocked, the matching Chrome Headless
Shell build is published by Chrome for Testing. The version is in Playwright's
`driver/package/browsers.json`. Extract it to
`ms-playwright/chromium_headless_shell-<revision>/chrome-headless-shell-linux64/`
and create an empty `INSTALLATION_COMPLETE` marker in the revision directory.
Without root, extract the missing shared libraries from the distribution's
packages with `dpkg-deb -x` and set `LD_LIBRARY_PATH`. Chromium aborts in
`SkFontMgr_FontConfigInterface` without a font configuration, so provide fonts
and a minimal `FONTCONFIG_FILE` too. These fonts differ from the pinned visual
image, so use this setup only for the Python browser suite.

## Desktop visual pilot

The pilot's base image comes from MCR. If its blobs are blocked, baselines
cannot be compared or regenerated locally. A host run of
`npx playwright test --ignore-snapshots` can check scenario interactions only.
It needs `ATLAS_VISUAL_ENV` set and video turned off when ffmpeg is unavailable.
It is not visual verification. Never commit baselines from it; regenerate them
with [the container commands](../README.md#desktop-visual-tests).
