# skill-atlas CLI architecture

Status: accepted and implemented for the initial `scan` command. This document
defines behavior, component boundaries, and the patterns used to evolve the CLI.
The [Web UI specification](web-ui.md) defines the implemented `serve` command,
catalog reads, and on-demand document viewing over the same catalog.

## Purpose and scope

`skill-atlas` is a CLI tool for discovering AI skills in GitHub repositories and
storing their metadata in a local catalog on each user's machine.

The initial version provides one subcommand:

```sh
skill-atlas scan <github-repo-url>
```

`scan` is a subcommand, and `<github-repo-url>` is its required positional
argument. The initial command scans the repository's default branch.
Public and private GitHub repositories are supported, subject to the user's
access to the repository.

## Implementation

The application uses Python 3.11 or later, a `src/` package layout, and Hatchling
as its build backend. `pyproject.toml` defines dependencies and the `skill-atlas`
entry point; `uv.lock` pins the development environment. The package can also be
installed with pip or pipx.

### Libraries

| Library | Purpose |
| --- | --- |
| Typer | Subcommands, argument parsing, help text, and command options. |
| Textual | Interactive terminal results view, buttons, and keyboard shortcuts. |
| Rich | Formatted text and layout within Textual and in plain command output. |
| HTTPX | Requests to GitHub's HTTP API, with explicit timeouts and error handling. |
| PyYAML | Safe parsing of YAML frontmatter. |
| platformdirs | Platform-appropriate location for the local catalog. |
| `sqlite3` (Python standard library) | SQLite persistence and transactions. |

A GitHub-specific SDK and an ORM are unnecessary for the initial scope.

## Required behavior

For each discovered skill, store:

- Repository name.
- Skill name.
- Description.
- Commit SHA.

Also store the repository URL and skill path to identify the skill reliably.
The catalog represents each repository's latest successfully scanned state.
It does not retain scan history or update automatically.

## Components

These components are modules within one application, not separate services.

| Component | Responsibility |
| --- | --- |
| CLI | Parse the command and repository URL, invoke the scanner, and present the outcome. |
| Results view | Display the scanned repository's skills and handle interactive description toggling. |
| Scanner | Coordinate repository reading, skill parsing, and catalog updates. |
| GitHub reader | Resolve the default branch to a commit, discover `SKILL.md` paths, and retrieve their contents through GitHub's API. |
| Fallback reader | Select a Git snapshot reader when the API cannot enumerate the complete repository. |
| Git snapshot reader | Fetch an exact shallow partial snapshot, list paths locally, and lazily retrieve skill blobs. |
| Skill parser | Extract `name` and `description` from each skill definition's YAML frontmatter. |
| Local catalog | Persist skill metadata in SQLite and replace a repository's entries atomically. |

The CLI delegates scanning to the scanner. The scanner uses the GitHub reader,
skill parser, and local catalog. Parsing does not depend on network access or
database access.
The results view receives the completed scan results and does not perform
GitHub requests or catalog writes. Toggling descriptions only changes the view.

## Scan flow

1. Parse and normalize the GitHub repository URL.
2. Resolve the repository's default branch to a commit SHA.
3. List repository files at that commit and discover `SKILL.md` files
   recursively, including at the repository root. If the API listing is
   truncated, discard it and use a temporary partial Git snapshot instead.
4. Retrieve the discovered skill files at that same commit through the selected
   reader.
5. Parse their names and descriptions and assemble the catalog entries.
6. Replace the repository's existing entries in one SQLite transaction.
7. Clean up scan resources, including any temporary Git repository.
8. Present the command outcome.

Repository contents must be read remotely, but a full clone is unnecessary.
Only skill file contents and the metadata needed to discover them are required.
All reads are pinned to the resolved commit so a branch update during the scan
cannot mix metadata from different repository versions.

Skill definitions are input data. Scanning does not execute repository code or
follow instructions contained in skill files.

## Catalog data model

Each skill entry contains the following logical fields. The physical database
schema can be chosen during implementation.

| Field | Meaning |
| --- | --- |
| `repository_url` | Canonical GitHub repository URL. |
| `repository_name` | Repository owner and name, in `owner/repository` form. |
| `skill_path` | Repository-relative path to the skill's `SKILL.md` file. |
| `skill_name` | The `name` value from the skill's YAML frontmatter. |
| `description` | The `description` value from the skill's YAML frontmatter. |
| `commit_sha` | Full SHA of the repository snapshot used for the scan. |

A skill is identified within the catalog by `(repository_url, skill_path)`.
Names alone are insufficient because different skills can share a name.

The commit SHA records the scanned snapshot; it is not necessarily the commit
that last modified the skill file.

## Database location

Store `catalog.sqlite3` in the user's application data directory, resolved with
`platformdirs.user_data_path("skill-atlas", appauthor=False, roaming=False)`.
Create the directory on first use.
`SKILL_ATLAS_DB` can override the database file path for development or alternate
catalogs; a relative override is resolved from the working directory.

Typical locations are:

| Platform | Location |
| --- | --- |
| macOS | `~/Library/Application Support/skill-atlas/catalog.sqlite3` |
| Linux | `$XDG_DATA_HOME/skill-atlas/catalog.sqlite3`, defaulting to `~/.local/share/skill-atlas/catalog.sqlite3` |
| Windows | `%LOCALAPPDATA%\skill-atlas\catalog.sqlite3` |

The catalog is persistent application data, rather than a disposable cache or
a file inside the repository being scanned.

## Authentication

Private repository access is part of the initial scope.

Credential lookup order:

1. `GH_TOKEN` environment variable.
2. `GITHUB_TOKEN` environment variable.
3. The existing GitHub CLI login, using `gh auth token --hostname github.com`,
   if `gh` is installed and authenticated.
4. Anonymous access for public repositories when no credential is available.

Use the credential for repository listing and skill content requests. Do not
persist it in the catalog. An authentication or access failure leaves the
existing catalog entries intact.
The Git fallback receives the same credential through a GitHub-scoped HTTP
authorization header in the subprocess environment. It does not place tokens
in command arguments, remote URLs, or files, and disables interactive credential
prompts. Raw Git error output is not displayed.

## Metadata extraction rules

- Discover regular files named exactly `SKILL.md`, at any depth including the
  repository root. Do not follow symlinks or traverse submodules.
- Decode as UTF-8, allowing an initial byte-order mark.
- Require YAML frontmatter at the start of the file, delimited by lines
  containing `---`.
- Parse with `yaml.safe_load`; the frontmatter must be a mapping.
- Read `name` and `description`. Both must be strings and nonempty after trimming
  leading and trailing whitespace. Support YAML multiline strings.
- Preserve internal description text in storage. Wrap it for terminal display.
- Ignore other frontmatter fields and the Markdown body. Do not infer missing
  metadata from a directory name or heading.
- Silently skip files that cannot be decoded or do not satisfy these extraction
  rules. Malformed-skill diagnostics are not part of the command.
- Keep skills with the same name as distinct entries when their paths differ.

Retrieval failures remain scan failures; they are not skipped as malformed
metadata. Under these rules, the stored entries and displayed count
include only successfully parsed skills.

## Rescans and consistency

A successful scan replaces only the scanned repository's entries. This updates
existing skills, adds newly discovered skills, and removes skills no longer
present. Repeating a scan of the same commit does not create duplicate entries.
A successful scan that finds no skills removes that repository's old entries.
Entries belonging to other repositories remain unchanged.

Collect results before modifying the catalog. If repository access, file
retrieval, or database persistence fails, leave the previous entries intact.
An incomplete repository listing must not be treated as a successful scan.

## Command output

The first line of successful output contains the repository name and skill
count. Each skill then has a one-based index, its name aligned left, and a
right-aligned hyperlink whose visible text is the same skill name. When
descriptions are visible, each description appears below its skill's name row.

Example layout (the right-hand names are hyperlinks):

```text
acme/example — 2 skills

1. code-review                                      code-review
   Review code changes for correctness and maintainability.

2. release-notes                                  release-notes
   Draft release notes from a set of changes.

[Hide descriptions]
```

The initial version includes an interactive terminal view with a button to
show or hide descriptions. This is a terminal user interface (TUI) launched by
the CLI command after a successful scan.

Presentation and interaction details:

- Open the interactive view when both standard input and standard output are
  attached to an interactive terminal. Provide `--no-interactive` to print the
  results and exit instead. Redirected output uses the noninteractive format.
- Show descriptions by default. The button toggles all descriptions; `d` is an
  equivalent keyboard shortcut, and `q` exits the view.
- Sort skills by name, then path, for deterministic numbering.
- Link to the scanned `SKILL.md` at its recorded commit:
  `https://github.com/{owner}/{repository}/blob/{commit_sha}/{skill_path}`,
  with the path URL-encoded as needed. Activating a link in the interactive view
  opens it in the user's browser.
- In noninteractive terminal output, use terminal hyperlinks where supported.
  For redirected output or unsupported terminals, include the literal URL,
  wrapping onto another line when necessary. Clickable terminal labels depend
  on the terminal's hyperlink support.
- Adapt to terminal width and render repository metadata as literal text, not
  Rich markup or terminal control sequences.
- Noninteractive output includes descriptions and has no toggle button.

Exit codes: `0` for a completed scan (including zero skills), `1` for a
scan or storage failure, and `2` for invalid command usage. Operational errors
go to standard error; noninteractive successful results go to standard output.

## Outside the initial scope

- A shared catalog or remote database.
- Scan history or version comparison.
- Malformed-skill reporting.
- Skill installation or execution.
- Other Git hosting providers.
- Branch or tag selection and automatic background updates. The local `serve`
  command is specified separately in [the Web UI specification](web-ui.md).

## GitHub access strategy

Use the REST API to read repository metadata, resolve the default branch's
commit, and obtain its root tree SHA. A recursive Git tree request discovers
skill files. Small repositories stay entirely on the API path and do not need
Git or a temporary directory.

If GitHub truncates the listing, discard it and select the Git snapshot reader.
Do not enumerate each directory with a separate API request: that scales poorly
on repositories with thousands of directories. API access and network failures
remain errors; they are not reasons to switch readers.

The Git reader requires Git 2.31 or later. It lazily creates a temporary bare
repository and fetches the exact API-resolved commit with `--depth=1`,
`--filter=blob:none`, `--no-tags`, and no submodule recursion. The fetched root
tree must match the API-resolved tree SHA. No branch is resolved a second time.

Use `git ls-tree -r -z` to enumerate paths without checking out source files.
Only regular `SKILL.md` blobs are read, through `git cat-file`, which lazily
fetches their contents. Symlinks and submodules are excluded. No worktree,
checkout filters, or hooks are used. In the API reader, skill contents continue
to come from the Git blobs API. Both paths read immutable object identifiers.

The composition root owns the Git reader's context and releases it before
opening the results view. Each temporary directory is registered for cleanup
before any Git operation begins. Successful scans, failures (including catalog
failures), timeouts, and Ctrl+C all unwind that context. On timeout or interruption,
stop Git and its transport helpers before removing the directory. Nothing is
kept as a persistent Git cache. A forced process kill or power loss can prevent
normal cleanup.

Requests have explicit timeouts. Access failures, rate limits, invalid responses,
and network errors become command errors without tracebacks. HTTP requests use
a 30-second timeout; Git commands have a 120-second timeout. The first version
does not automatically retry or wait out rate limits. A repository with no
commits cannot supply a snapshot and produces an operational error; this differs
from a committed repository containing zero skills, which is a successful scan.

## Evolution and extension points

Use dependency inversion at I/O and policy boundaries. Application services
depend on small Python `Protocol` interfaces; adapters satisfy them structurally.
Immutable dataclasses carry values between components. Constructor injection
keeps dependencies explicit. No dependency injection framework or plugin loader
is needed for the initial version.

| Module | Role and extension point |
| --- | --- |
| `cli.py` | Builds the Typer application and registers subcommands. |
| `commands/` | One module per command; adapts arguments, exit codes, and presentation. |
| `models.py` | Immutable repository, snapshot, metadata, skill, and scan-result values. |
| `ports.py` | Repository/snapshot reader, parser, and catalog interfaces. |
| `scanner.py` | Scan use case; no dependencies on HTTPX, SQLite, Typer, or Textual. |
| `runtime.py` | Composition root that constructs adapters and owns HTTP and Git resource lifetimes. |
| `github.py` | GitHub transport, snapshot resolution, and file discovery rules. |
| `git.py` | Temporary partial Git snapshots, authenticated subprocesses, and cleanup. |
| `readers.py` | Fallback selection policy behind the repository reader interface. |
| `parsing.py` | Frontmatter extraction policy behind the parser interface. |
| `storage/` | SQLite adapter and ordered database migrations. |
| `presentation/` | Independent text and interactive views over completed scan results. |
| `config.py`, `auth.py` | Local settings and credential resolution. |

### Adding a subcommand

Add a module in `commands/` with a `register(app)` function and register it in
`cli.create_app()`. Keep business behavior in an application service rather than
in the command function. Reuse or add narrow ports for its actual dependencies,
and wire concrete adapters in `runtime.py`. A future read-only catalog command
should introduce a read interface rather than expanding the scan service.

### Changing rules or adding components

Change frontmatter rules in the parser, discovery rules in the reader, and
presentation rules in the views. A replacement implementation can satisfy the
same protocol and be selected in the composition root without editing the
scanner. When a genuinely separate responsibility emerges, give it a narrow
interface and inject it into the service that needs it. Avoid speculative base
classes, generic repositories, or a universal component registry.

### Evolving the data model

Update the relevant dataclass and explicitly map new persisted fields in the
SQLite adapter. Append a numbered migration in `storage/migrations.py`; do not
edit shipped migrations. Use defaults or a backfill when existing records need
new values. The database's `PRAGMA user_version` tracks its schema version.

Migrations run under a write lock before catalog replacement. Schema changes
and their version marker commit or roll back together. Replacing repository
entries uses a separate atomic transaction. A newer, unsupported schema version
is rejected without modification. Opening a database never drops and recreates
the catalog as an upgrade strategy.

## Verification

Tests exercise the parser and repository identity rules, HTTP requests through
an in-memory mock transport, the scanner through substitute port implementations,
and migrations and rollback using temporary SQLite files. End-to-end command
tests cover persistence and output without network access. Textual's headless
test runner checks description toggles, links, and narrow terminal layouts.
Git tests use local repositories to verify partial fetching, commit consistency,
blob selection, and cleanup. Timeout and interruption tests verify the Git
process has stopped before its temporary directory is removed.

Unit tests live in `tests/unit/`; component and command integration tests live
in `tests/integration/`. The full scan scenarios run against both the GitHub API
transport fixture and a real local Git fallback, including identical copies in
`.claude` and `.agents`, same-name skills, rescans, removals, failures, and branch
movement during a scan. Test sockets are disabled except Unix sockets needed by
the event loop; Git remotes use local fixture repositories.

Run `uv run pytest --cov=skill_atlas --cov-report=term-missing`, `uv run ruff check .`,
`uv run ruff format --check .`, and `uv run mypy`. CI enforces a 90% combined
coverage floor with branch measurement. It checks Linux on Python 3.11 and 3.13
and macOS on Python 3.13, builds the package, and smoke-tests the installed wheel
outside the source checkout. Commit the lockfile when dependencies change.
`AGENTS.md` defines the testing and CI rules for future changes.
