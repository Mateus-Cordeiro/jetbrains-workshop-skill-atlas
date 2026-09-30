# skill-atlas

Discover AI skills in GitHub repositories and save their metadata to a local
SQLite catalog. Requires Python 3.11 or later.

From the local checkout directory, install the CLI as a user-level tool:

```sh
uv tool install --editable .
```

Then run it from any directory:

```sh
skill-atlas scan https://github.com/owner/repository
```

The editable installation picks up Python source changes in this checkout.
If your shell cannot find the installed command, run `uv tool update-shell` and
restart the shell to add uv's executable directory to `PATH`.

The results view shows numbered skills with links to their scanned definitions.
Click **Hide descriptions**, or press **d**, to toggle descriptions. Press **q**
to exit. Links open in your default browser.

For ordinary terminal output, use:

```sh
skill-atlas scan https://github.com/owner/repository --no-interactive
```

Redirected output automatically uses plain text, including literal URLs.

## Similar skills from the CLI

Find alternatives to a skill already in the catalog:

```sh
skill-atlas similar https://github.com/owner/repository \
  ".agents/skills/code-review/SKILL.md"
```

Supply the repository URL and exact repository-relative path to `SKILL.md`,
including case. Quote paths containing spaces or shell metacharacters. Names
alone cannot select a skill because multiple entries may have the same name.
Scan the repository first if the starting skill is not yet in the catalog.

The command prints ranked scores, skill names, every grouped repository/path,
and links to the scanned commits, then exits. It uses the same ranking as the
Web UI, searching all scanned repositories, including the starting repository.
Identical normalized names and descriptions share one result group. Results
contain at most ten groups scoring at least 10%.

For scripts, add `--json`:

```sh
skill-atlas similar https://github.com/owner/repository \
  ".agents/skills/code-review/SKILL.md" --json
```

JSON includes `source` and ordered `matches`. Each match contains the unrounded
0–100 `score`, rounded `display_score`, and all `locations`, with metadata,
repository/path identity, commit SHA, and URL for each location. Text output
omits descriptions; JSON preserves them. Successful output goes to stdout and
errors to stderr. Exit codes are `0` for success (including no matches), `1` for
a missing source or catalog failure, and `2` for invalid usage.

Search works locally from the configured catalog, including `SKILL_ATLAS_DB`,
without credentials, document fetching, rescanning, or a running Web server.
Scores measure names and descriptions, not quality or identical instructions,
and can change as the catalog grows. See [Similar skills](spec/features/similar-skills.md)
for the complete ranking and JSON contracts.

## Web UI

Start the local browser interface:

```sh
skill-atlas serve
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), or use
`skill-atlas serve --port 8123` to select another port. Press Ctrl+C to stop.
From a development checkout, use `uv run --locked skill-atlas serve`.

The page lists repositories in the same catalog used by CLI scans. Submit a
GitHub repository URL to scan it, open a repository, and select a skill in the
left pane to read its definition in the right pane. **Preview** renders Markdown;
**Source** shows the complete `SKILL.md`, including frontmatter. Scans run in the
background while you browse. **Rescan repository** refreshes an existing entry.

Skill descriptions on homepage, repository, and similarity lists show up to two
lines by default. Use **Show more** or **Show less** to expand or collapse an
individual description. The skill's path appears in the document pane when selected.

Expand a repository with its chevron to browse skills inline, or use **Filter
skills across repositories** to find matches throughout the catalog. Names and
descriptions match case-insensitively; every search word must appear in either
field. The repository view has its own filter above the skill list. Filters stay
in the URL through navigation and refresh, and filtering keeps the open document
visible. Clear the field or press Escape while focused to show all skills again.

Choose **Find similar** beneath a skill to discover alternatives across your
scanned catalog. Results show a colour-coded **0–100% similarity bar** and
expandable locations with matching metadata. Bars are red below 40%,
amber at 40–69%, and green at 70–100%, with a clear percentage above a slim,
rounded track. Results use the same skill cards and expandable descriptions as
the catalog. Select a result to read it while keeping the starting skill visible.
Search always includes all scanned repositories, even when opened from a filtered
list. **Starting skill** returns
to that repository with your filter preserved. Reload the page to include
changes made by CLI scans.

Scores compare descriptions (80%) and names (20%) using shared words and phrases;
they are not probabilities or quality ratings. Even 100% does not establish
identical instructions. Scores can change as the catalog grows. Search shows up
to ten groups scoring at least 10% and can miss synonyms or misinterpret
exclusions. It works locally from metadata without fetching documents or
rescanning. See [Similar skills](spec/features/similar-skills.md) for the rules.

Documents are fetched from GitHub at the recorded commit when selected, using
backend credentials for private repositories. They are not stored locally.
A scan with zero skills shows **No skills found** and removes that repository
from the saved list. Failed scans preserve the previous successful entries.
Queued jobs and scan activity exist only while the server is running.
Queued and running scans remain visible. Successful notices disappear after
five seconds; failed scans stay available for retry or dismissal. Both completed
states have a dismiss button, and dismissed notices stay hidden in the same tab.

The interface is local and binds only to loopback. Templates, CSS, JavaScript,
and HTMX are bundled with the Python package; no frontend build or CDN is needed.
See [the Web UI specification](spec/features/web-ui.md) for behavior and
architecture.

## Installation

For an installation that does not follow source edits, use `uv tool install .`
or `pipx install .` from the checkout. You do not need to clone scanned
repositories yourself.

Install Git 2.31 or later to scan large repositories. When GitHub truncates a
file listing, skill-atlas automatically fetches a shallow partial Git snapshot
of the exact scanned commit. It lists paths locally and downloads only the
discovered skill files, with no working checkout or full history.

The temporary Git repository is removed after the scan, including on errors,
timeouts, and Ctrl+C, before the results view opens. No Git cache is retained.

## Authentication and storage

Private repositories are supported. Credentials are resolved in this order:
`GH_TOKEN`, `GITHUB_TOKEN`, then an existing `gh auth login` session for
`github.com`. The token must have read access to the repository's contents.
Without a credential, public repositories are scanned anonymously, subject to
GitHub's lower rate limits. The Git fallback uses the same credential through
process-local configuration; it never writes the token into the repository's
remote URL or Git configuration file.

The catalog lives in the operating system's user data directory:

- macOS: `~/Library/Application Support/skill-atlas/catalog.sqlite3`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/skill-atlas/catalog.sqlite3`
- Windows: `%LOCALAPPDATA%\skill-atlas\catalog.sqlite3`

Set `SKILL_ATLAS_DB` to override the database file location. Credentials are not
stored in the database. A completed scan replaces that repository's previous
entries, including removing entries for skills that disappeared. There is no
scan history. Malformed skill definitions are silently skipped.

## Development

Run these commands from the project checkout:

```sh
uv sync --locked
uv run skill-atlas scan https://github.com/owner/repository
uv run pytest tests/unit
uv run pytest tests/integration
uv run pytest --cov=skill_atlas --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

`uv run` uses the current project's environment; it does not install the command
globally. From another directory, use the installed `skill-atlas` command above,
or specify the checkout with `uv run --project /path/to/checkout skill-atlas ...`.

Start with the [specification index](spec/README.md). The
[shared architecture](spec/architecture.md) records the adopted stack, component
boundaries, catalog contracts, and extension patterns. Feature specs describe
scan, Web UI, and similarity-search behavior and their acceptance criteria.

The source package groups workflows in `application/`, concrete integrations
in `adapters/`, terminal commands and output in `cli/`, and the browser interface
in `web/`. Shared models and ports remain at the package root; `runtime.py`
connects implementations and manages their resources. The architecture includes
a [component map](spec/architecture.md#components-and-dependency-boundaries) and
walkthroughs for [scanning](spec/architecture.md#following-a-scan),
[catalog filtering](spec/architecture.md#following-a-catalog-filter),
[document viewing](spec/architecture.md#following-a-document-selection), and
[similarity search](spec/architecture.md#following-a-similarity-search).

## Continuous integration

GitHub Actions runs lint, formatting, type checks, an installed-package smoke
test, and both test suites on every push and pull request. Tests run on Linux
(Python 3.11 and 3.13) and macOS (Python 3.13), with a combined 90% coverage floor
and branch measurement enabled. JUnit and coverage reports are available as
workflow artifacts. The stable aggregate status check is **CI required**; select
it in GitHub branch protection or a ruleset to require passing CI before merging.

Push, pull-request, and manual runs use separate concurrency groups. Newer runs
cancel older runs for the same event type and branch or PR; a PR run cannot
cancel the checks for a merge pushed to the default branch.

Integration tests exercise both the API and partial Git paths against local
fixtures, including copies of skills under `.claude` and `.agents`, rescans,
removals, failures, and cleanup. Copies at different paths remain distinct
catalog entries. Tests require no GitHub credentials or live network access.

See [AGENTS.md](AGENTS.md) for the testing rules, required checks, and criteria
for adding integration coverage when changing the implementation. Delivery
includes pushing a task branch and checking CI for the latest commit, fixing
failures until the required checks are green. Default-branch merges remain a
separate action.

### Browser and installed-package checks

Install Chromium once and run the browser suite:

```sh
uv run --locked playwright install chromium
uv run --locked pytest tests/browser
```

Browser tests permit loopback connections only and mock GitHub. They cover
selection, preview/source switching, navigation, narrow layouts, scan states,
retry, stale selections, and delayed responses. CI runs them in Chromium on Linux.
Screenshots are written to the ignored `test-results/` directory.

After `uv build`, install the wheel into a temporary virtual environment and
run `tests/smoke_installed.py` with that environment's Python from outside the
checkout. It verifies the `similar` command's help, text and JSON results, and
the packaged templates and static assets. CI also checks
`skill-atlas serve --help` in that installed environment.
