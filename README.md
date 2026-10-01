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

The `scan`, `filter`, and `similar` commands share a results view with numbered
skills, descriptions, repository paths, and links to their scanned definitions.
Click **Hide descriptions**, or press **d**, to toggle descriptions. Press **q**
to exit. Links open in your default browser.

For ordinary terminal output, use:

```sh
skill-atlas scan https://github.com/owner/repository --no-interactive
```

All three commands accept `--no-interactive`. They open the interactive view
when both input and output are attached to a capable terminal; otherwise they
print and exit. Redirected output automatically uses plain text, including
literal URLs. Scroll or use Tab to focus links and Enter to open them.

## Scan an organization

Pass an organization URL, with no repository name, to scan every repository in
the organization:

```sh
skill-atlas scan https://github.com/acme
```

Organization scans require a GitHub credential (see
[Authentication and storage](#authentication-and-storage)). Forks and archived
repositories are skipped. Up to four repositories are scanned at a time, and each
is saved as soon as it completes. Instead of the skill list, the command prints
a summary line with the organization, repository count, and total skill count,
then one line per repository:

```text
acme — 4 repositories, 5 skills
acme/agents — 5 skills
acme/docs — no skills
acme/new-project — empty
acme/private-tools — failed: GitHub denied access. Check the credential's repository permissions.
```

Browse the results with `filter` or `serve`. The command exits with `1` if the
listing fails, any repository fails, or GitHub's rate limit stops the scan.
After a rate limit, no further repositories start; those not yet scanned are
reported as **not scanned**, and repositories already saved stay in the catalog.
Ctrl+C stops the scan the same way. User accounts are not supported; scan their
repositories individually. Repositories that leave the organization remain in
the catalog until you rescan them.

## Filter saved skills

Search the local catalog without rescanning or starting the Web server:

```sh
skill-atlas filter "code review"
skill-atlas filter "code review" --repository https://github.com/owner/repository
skill-atlas filter "code review" --no-interactive
skill-atlas filter "code review" --json
skill-atlas filter
```

Every whitespace-separated term must occur in the skill's name or description,
using Unicode case-insensitive matching. Quote multiword queries; punctuation
is literal, and paths and document bodies are not searched. Omit the query to
list all saved skills. `--repository` limits results to one repository.

Results show names, descriptions, repository paths, and commit-pinned links
in the shared interactive view, or print and exit with `--no-interactive`.
`--json` always prints and exits, emitting an object with `matching_count` and a `skills`
array containing each match's metadata, identity, full commit, and URL. Results
use the same catalog as the Web UI, including `SKILL_ATLAS_DB`, and reflect the
latest successful scans. Filtering works offline and does not require credentials.

No matches is a successful query (exit `0`). Catalog failures exit `1`; invalid
usage exits `2`. Errors go to stderr. See the [Filter specification](spec/features/filter.md)
for matching and output contracts.

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

Results show ranked scores, skill names, descriptions, every grouped
repository/path, and links to the scanned commits. Use the shared interactive
controls or add `--no-interactive` to print and exit. It uses the same ranking as the
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
repository/path identity, commit SHA, and URL for each location. JSON always
prints and exits, including on a terminal. Printed output goes to stdout and
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

The homepage opens directly onto repositories in the same catalog used by CLI
scans. Choose **+ Add repository** to reveal the URL field and **Scan repository**
button; the form starts open when the catalog is empty. Submit a GitHub repository
URL to scan it, or an organization URL to scan all of its repositories. Then open a repository, and select a skill in the left pane to read its definition in the right pane. **Preview** renders Markdown;
**Source** shows the complete `SKILL.md`, including frontmatter. Scans run in the
background while you browse. To update an existing entry, submit its URL again
through the homepage form or run the CLI `scan` command. Repository pages have
no scan/rescan control. Commit hashes are omitted from the lists and document
viewer; **View on GitHub** still opens the exact scanned version.

Skill descriptions on homepage, repository, and similarity lists show up to two
lines by default. Use **Show more** or **Show less** to expand or collapse an
individual description. The skill's path appears in the document pane when selected.

Expand a repository with its chevron to browse skills inline, or use **Search skills…**
in the toolbar to find matches throughout the catalog. Names and
descriptions match case-insensitively; every search word must appear in either
field. The repository view has its own search above the skill list. On narrow
screens, use the magnifying-glass button to reveal search; an active query stays
visible. Filters stay in the URL through navigation and refresh, and filtering
keeps the open document visible. Clear the field or press Escape while focused to show all skills again.
The same matching rules apply to the `filter` subcommand.

Choose **Similar skills** beside a skill name to discover alternatives across your
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
Organization scans show **Scanning 3 of 12 repositories** while running and list
any repositories that failed; repositories that succeeded appear in the catalog
even when others fail. Queued and running scans remain visible. Successful notices disappear after
five seconds; failed scans stay available for retry or dismissal. Both completed
states have a dismiss button, and dismissed notices stay hidden in the same tab.

The interface is local and binds only to loopback. Templates, CSS, JavaScript,
and HTMX/G6 are bundled with the Python package; no frontend build or CDN is needed.
See [the Web UI specification](spec/features/web-ui.md) for behavior and
architecture.

## AI topic and capability groups

Choose **Explore** in the Web catalog, then **Generate groups** to create both
perspectives. Switch instantly between **Capabilities** and **Topics** above the
graph. Click a group to reveal its skills, drag nodes, and pan or zoom the canvas.
Hover highlights connections and shows details. Generation creates **at most 12
groups for each perspective**, preferring broader, coherent groups. Every skill
is included and can connect to multiple groups; a distinct skill can have a group
of its own within the limit. Previously saved larger groupings remain available
until you regenerate them.

The directory beside the graph provides the same groups and skill links for
keyboard use, and moves below the graph on mobile. Clicking a skill opens the
existing Preview/Source viewer; **Back to Explore** restores your expanded groups
and node positions in the same browser tab. Use **Fit graph** to frame the nodes or
**Reset layout** to reposition them. Motion respects reduced-motion preferences.
Generation uses names and descriptions, not document bodies.

Install and start [Ollama](https://ollama.com/), and make the model available:

```sh
ollama pull qwen3.6:latest
# If the Ollama application is not already serving:
ollama serve
```

Run `skill-atlas serve` as usual. The default model is `qwen3.6:latest`; use an
already-installed local model if preferred. No model is downloaded automatically.
Only explicit generation calls Ollama. Saved groups work while Ollama is stopped,
and ordinary scanning, filtering, and similarity search do not require it.

Configure the backend before starting the server:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `SKILL_ATLAS_OLLAMA_MODEL` | `qwen3.6:latest` | Installed local model tag. |
| `SKILL_ATLAS_OLLAMA_URL` | `http://127.0.0.1:11434` | Loopback HTTP Ollama origin; remote endpoints and embedded credentials are rejected. |
| `SKILL_ATLAS_OLLAMA_TIMEOUT` | `600` | Inference request timeout in seconds. |
| `SKILL_ATLAS_OLLAMA_CONTEXT` | `32768` | Requested model context tokens. |
| `SKILL_ATLAS_OLLAMA_OUTPUT_TOKENS` | `8192` | Reserved maximum output tokens. |

Use positive numeric seconds for timeout and positive whole numbers for token
limits (for example, `600` and `32768`, rather than `10m` and `32k`). Context must
exceed the output limit. These settings are validated only when you generate
groups; a bad value appears in the job error and does not prevent scanning,
filtering, similarity search, or starting the Web UI.

Larger catalogs may require more context and output tokens, subject to the model
and available memory. A conservative UTF-8 byte budget rejects oversized input
before sending it; it can reject text that a tokenizer would fit. Skills are never
silently omitted. Incomplete, malformed, or failed responses preserve previous
groups and offer retry. Skill Atlas sends metadata only to the configured local
Ollama server; use a local model, not an Ollama cloud model. GitHub credentials
are never forwarded.

The response schema requires an assignment for every skill. Failures identify
Topics or Capabilities and explain the rejected rule, such as missing assignments
or invalid group references, without exposing raw model output.

**Regenerate groups** makes two sequential Ollama calls from one catalog snapshot
and replaces both saved views together only after both validate. It may reorganize
or rename groups. Catalog changes show a regeneration notice;
removed skills disappear, and new skills join groups after regeneration. If either request or save fails, both previous views remain available. Jobs survive browser
navigation, but do not resume after server restart. See the
[grouping specification](spec/features/skill-groups.md) for behavior and limits.

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
GitHub's lower rate limits. Organization scans list repositories through GitHub's
GraphQL API, which requires a credential that can see the organization. The Git fallback uses the same credential through
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

### Working with coding agents

Codex and Claude use the same [shared project memory](memory/index.md) and
[memory skill](.agents/skills/shared-memory/SKILL.md). Both follow
[AGENTS.md](AGENTS.md) directly, read relevant memory before a task, and
reconcile durable findings before finishing. The skill can be read directly;
no personal skill installation, hook, or memory service is required.

For Claude Code, use v2.1.281 or later with
[AGENTS.md support](https://code.claude.com/docs/en/memory#agents-md) enabled.
If local or ancestor `CLAUDE.md` or `CLAUDE.local.md` files take precedence,
set **Project instructions** to `claude-md-and-agents-md` in `/config`.
Use `/memory` to confirm that this repository's `AGENTS.md` loaded.

Memory is curated Markdown tracked with the project. Agents in the same
checkout see the same files; separate branches, worktrees, and machines share
updates through normal Git integration. It does not automatically synchronize
active sessions. The [repository instructions](AGENTS.md#shared-project-memory)
define the policy; the skill defines the maintenance procedure.

### Local development

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
scan, filtering, Web UI, AI grouping, and similarity-search behavior and their acceptance
criteria. The [Filter specification](spec/features/filter.md) owns matching rules
shared by the CLI and Web UI.

The source package groups workflows in `application/`, concrete integrations
in `adapters/`, terminal commands and output in `cli/`, and the browser interface
in `web/`. Shared models and ports remain at the package root; `runtime.py`
connects implementations and manages their resources. The architecture includes
a [component map](spec/architecture.md#components-and-dependency-boundaries) and
walkthroughs for [scanning](spec/architecture.md#following-a-scan),
[catalog filtering](spec/architecture.md#following-a-catalog-filter),
[document viewing](spec/architecture.md#following-a-document-selection), and
[similarity search](spec/architecture.md#following-a-similarity-search).

### Desktop visual tests

The desktop pilot uses Playwright Test with Chromium for catalog filtering,
description expansion and document preview/source, scan progress with
failure and retry, and graph exploration. Each scenario uses a real local app and temporary catalog,
with synthetic GitHub responses. Existing Python browser tests, including mobile
coverage, remain in place.

With Docker running, run the canonical Linux amd64 environment:

```sh
bash tests/browser/visual/run-container.sh
```

This builds the pinned browser image and installs locked Python and JavaScript
dependencies, then runs the tests without external networking. Docker emulates
amd64 on Apple Silicon so local comparisons use CI's architecture and fonts.
Node is only development tooling; the installed application still needs no Node
runtime. If Node is installed locally, `npm ci` and `npm run check:visual` provide
the TypeScript check; `npm run test:visual:container` wraps the command above.

Named checkpoints capture the browser at stable states and compare it with PNGs
in `tests/browser/visual/snapshots/`. Review
`test-results/visual/report/index.html` for each run's checkpoint attachments.
Failures also include expected/actual/diff images, traces, and videos. With local
dependencies installed, `npx playwright show-report test-results/visual/report`
opens the report. CI uploads the full directory as `desktop-visual-reports`.

For an intentional visual change, update only the affected scenario's baselines:

```sh
bash tests/browser/visual/run-container.sh --update-snapshots --grep 'catalog filtering'
bash tests/browser/visual/run-container.sh
```

Review changed baseline images against the intended design before committing
them with the implementation. Missing baselines fail normal runs. CI forbids
updates. Browser/image upgrades also require reviewed baseline regeneration;
keep the Playwright package pin, Docker image, and environment guard aligned.
Do not generate these baselines with a host browser or relax tolerances to hide
unexplained differences.

Generate review videos from the same scenarios with optional pacing:

```sh
ATLAS_DEMO=1 bash tests/browser/visual/run-container.sh
# Or, with Node installed:
npm run demo:visual
```

Recording mode still checks all screenshot baselines. Videos are finalized when
the browser context closes and appear with the scenario's checkpoint images in
the HTML report. Each run replaces `test-results/visual/`; copy any recording
you need to keep into `test-results/pr-demo/` before the next run. Review the
videos before attaching them to a PR, following the
[demo skill](.agents/skills/pr-demo/SKILL.md). Scan delays and failures are
controlled fixture responses. Screenshots are captured directly from the
browser; recordings themselves are not compared frame by frame.

## Continuous integration

GitHub Actions runs lint, formatting, type checks, an installed-package smoke
test, and both test suites on every push and pull request. Tests run on Linux
(Python 3.11 and 3.13) and macOS (Python 3.13), with a combined 90% coverage floor
and branch measurement enabled. JUnit and coverage reports are available as
workflow artifacts. The stable aggregate status check is **CI required**; select
it in GitHub branch protection or a ruleset to require passing CI before merging.

The existing browser job runs Python Playwright tests. A separate required
desktop visual job runs the four pilot scenarios in the pinned Docker image,
compares screenshot baselines, and uploads the HTML/JUnit reports, checkpoint
images, and failure diagnostics. Both feed into **CI required**.

Push, pull-request, and manual runs use separate concurrency groups. Newer runs
cancel older runs for the same event type and branch or PR; a PR run cannot
cancel the checks for a merge pushed to the default branch.

Integration tests exercise both the API and partial Git paths against local
fixtures, including copies of skills under `.claude` and `.agents`, rescans,
removals, failures, and cleanup. Copies at different paths remain distinct
catalog entries. Organization scans run against a mocked GraphQL listing of local
fixture repositories, covering request counts, pagination, parallel workers,
rate limits, and Ctrl+C cleanup. Tests require no GitHub credentials or live
network access.

See [AGENTS.md](AGENTS.md) for the testing rules, required checks, and criteria
for adding integration coverage when changing the implementation. Delivery
includes pushing a task branch and reporting CI status for the latest commit.
Tasks may finish while CI is queued or running, without waiting for **CI required**
to turn green, unless the user explicitly requests waiting. Local checks remain
required, and observed failures caused by the change must be fixed.
Default-branch merges remain a separate action.

### Browser and installed-package checks

Install Chromium once and run the browser suite:

```sh
uv run --locked playwright install chromium
uv run --locked pytest tests/browser
```

Browser tests permit loopback connections only and mock GitHub and Ollama. They cover
selection, preview/source switching, navigation, narrow layouts, scan states,
retry, stale selections, and delayed responses. CI runs them in Chromium on Linux.
Screenshots are written to the ignored `test-results/` directory.

After `uv build`, install the wheel into a temporary virtual environment and
run `tests/smoke_installed.py` with that environment's Python from outside the
checkout. It verifies the installed `filter` and `similar` commands, including
help and catalog queries, plus AI grouping generation/persistence with mocked Ollama and packaged templates
and static assets. CI also checks
`skill-atlas serve --help` in that installed environment.

### Updating the bundled graph library

G6 is pinned in `package.json` and `package-lock.json`. After an intentional version
update, run `npm ci` and `npm run vendor:g6`. Commit the regenerated
`src/skill_atlas/web/static/g6.min.js` and `g6-LICENSE.txt` with the lockfile changes.
The script copies the published distribution and includes dependency license
notices. `npm run check:vendor` checks reproducibility without writing; the desktop
visual job runs it before its TypeScript and browser checks. Run the Web, installed-wheel, and visual checks in
[AGENTS.md](AGENTS.md#required-local-checks). End users do not need Node or npm;
the Python wheel contains the graph library and all assets.
