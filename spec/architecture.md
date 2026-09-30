# skill-atlas architecture

Status: accepted and implemented. This document owns the shared architecture
and adopted technology choices. See the [specification index](README.md) for
feature behavior and [AGENTS.md](../AGENTS.md) for contribution and CI rules.

## Purpose and scope

skill-atlas discovers AI skills in GitHub repositories and stores their metadata
in a local catalog on each user's machine. One Python application exposes the
[`scan` command](features/scan.md) and the local
[`serve` Web UI](features/web-ui.md). Both use the same catalog and scan service.
Public and private GitHub repositories are supported, subject to user access.

The catalog holds each repository's latest successfully scanned state. It is
persistent application data, not a shared database or a disposable repository
cache. There is no scan history, automatic refresh, or skill execution.

## Adopted technology stack

The application uses Python 3.11 or later and a `src/` package layout. The
`skill-atlas` entry point is declared in [pyproject.toml](../pyproject.toml).
Installations can use uv, pip, or pipx.

This section records purpose and rationale rather than duplicating package
versions. `pyproject.toml` owns Python requirements and dependency ranges;
[uv.lock](../uv.lock) owns resolved Python package versions. Bundled frontend
assets carry their version and license in `src/skill_atlas/web/static/`.

### Runtime

| Technology | Purpose and rationale |
| --- | --- |
| Python | One implementation language for the CLI, application services, and local Web backend. |
| Typer | Subcommand registration, argument validation, options, and generated help. |
| Textual | Interactive terminal results with buttons and keyboard shortcuts. |
| Rich | Text layout and terminal hyperlinks for interactive and ordinary output. |
| HTTPX | Explicit GitHub HTTP requests, timeouts, and mockable transport boundaries without a provider-specific SDK. |
| PyYAML | Safe YAML frontmatter parsing. |
| platformdirs | OS-appropriate persistent user data locations. |
| SQLite via standard-library `sqlite3` | Local transactional persistence without a database server or ORM. |
| Git 2.31 or later | Temporary partial snapshots when a repository exceeds GitHub's complete tree-listing capacity. Small repositories need no Git subprocess. |
| FastAPI and Uvicorn | HTTP routing and the local ASGI server. |
| Jinja2 | Server-rendered pages and HTML fragments with escaped metadata. |
| HTMX, plain CSS, and a small JavaScript layer | Scan submission, polling, fragment updates, selection history, and stale-response handling without a frontend build toolchain. |
| markdown-it-py | Markdown preview with raw HTML disabled and controlled link rendering. |

HTMX and its license, templates, CSS, and JavaScript are bundled with the Python
package. There is no runtime CDN or separate frontend development server. The
installed application must work outside its source checkout.

### Development and delivery

| Tool | Purpose and rationale |
| --- | --- |
| uv | Locked environment synchronization, command execution, and package builds. |
| Hatchling | Build backend for the source distribution and wheel, including Web assets. |
| pytest and pytest-asyncio | Unit and integration testing, including asynchronous services and terminal interactions. |
| pytest-cov | Branch-aware coverage measurement and the CI coverage floor. |
| pytest-socket | Block accidental external network access in tests. |
| Ruff | Consistent lint and formatting checks. |
| mypy and types-PyYAML | Strict static typing, including YAML library stubs. |
| Playwright with Chromium | Browser interaction and rendering verification. |
| GitHub Actions | Reproducible quality, package, Python test, and browser gates. |

Required commands, supported CI test environments, coverage requirements, and
the push/check/fix loop are defined in [AGENTS.md](../AGENTS.md). The workflow
and manifests hold tool pins; this document need not change for routine version
bumps unless a documented constraint or architectural choice changes.

## Components and dependency boundaries

These are modules within one application, not separate services. Application
services depend on small Python `Protocol` interfaces at I/O and policy
boundaries; adapters satisfy them structurally. Immutable dataclasses carry
values between components. Constructor injection makes dependencies explicit.
No dependency injection framework or plugin loader is needed.

| Module | Responsibility and extension point |
| --- | --- |
| `cli.py`, `commands/` | Register subcommands and adapt arguments, exit codes, and presentation. |
| `models.py` | Immutable repository, snapshot, skill file, metadata, skill, scan result, and repository summary values. |
| `ports.py` | Narrow reader, parser, catalog-write, catalog-read, and document-reader interfaces. |
| `scanner.py` | Coordinate discovery, parsing, and atomic catalog replacement independently of HTTPX, SQLite, Typer, Textual, or Web routing. |
| `runtime.py` | Composition root: select adapters and own HTTP, Git, scanner, and Web application resource lifetimes. |
| `github.py` | GitHub transport, snapshot resolution, file discovery, and commit-pinned document retrieval. |
| `git.py`, `readers.py` | Temporary partial Git snapshots, authenticated subprocesses, cleanup, and fallback selection policy. |
| `parsing.py` | Frontmatter extraction policy with no network or database dependencies. |
| `storage/` | SQLite read/write adapter and ordered schema migrations. |
| `documents.py` | Resolve a catalog selection and retrieve its document at the recorded commit. |
| `jobs.py` | Process-local scan queue and worker lifecycle for the Web UI. |
| `presentation/` | Independent text and interactive views of completed scan results. |
| `web/` | HTTP routes, safe document rendering, templates, and static assets. |
| `config.py`, `auth.py` | Local settings and credential resolution. |

`SnapshotReader` lists and reads files; `RepositoryReader` also resolves a
repository snapshot. `SkillParser` extracts metadata. `Catalog` exposes
`replace_repository` to the scanner, while `CatalogReader` exposes repository
summaries, skill lists, and identity lookup. `DocumentReader` retrieves a file at
a recorded commit independently of scan discovery. Keep these read and write
interfaces separate as commands and views are added.

Commands and Web routes invoke application services. They do not duplicate scan
logic. A Web request must not invoke a CLI command or launch a Textual view.
Terminal views receive completed results and perform no GitHub requests or
catalog writes; description toggling only changes presentation.

The composition root creates a fresh scanner context for each CLI scan or Web
job. Release HTTP and temporary Git resources on success, operational errors,
timeouts, and interruption, before opening a terminal view. The scan feature
owns [Git cleanup details](features/scan.md#github-access-strategy); the Web
feature owns [worker shutdown](features/web-ui.md#scan-execution-and-lifecycle).

## Shared domain contracts

Accept repository URLs in `https://github.com/owner/repository` form, allowing
a trailing slash, `.git` suffix, and the default HTTPS port. Reject credentials
in URLs, query strings, fragments, and paths below the repository. Normalize
catalog URLs to `https://github.com/{owner}/{repository}` with lowercase owner
and repository. Display names use `owner/repository` form.

Resolve a scan's default branch once. Its snapshot contains the full commit SHA
and tree SHA, and all file reads use that snapshot. A stored commit identifies
the scanned snapshot, not necessarily the commit that last modified the file.
Document reads use the catalog's recorded commit rather than resolving a branch
again. Never mix versions when a branch moves during an operation.

Skill links use
`https://github.com/{owner}/{repository}/blob/{commit_sha}/{skill_path}` with
the path URL-encoded and its directory separators preserved. Order skill lists
by name, then path, for consistent CLI and Web presentation.

Repository content and metadata are input data. Do not execute repository code
or follow instructions in skill files. Each presentation adapter escapes that
data according to its output format.

## Catalog model and identity

The `skills` table stores these logical fields:

| Field | Meaning |
| --- | --- |
| `repository_url` | Canonical GitHub repository URL. |
| `repository_name` | Repository owner and name in `owner/repository` form. |
| `skill_path` | Exact repository-relative path to `SKILL.md`. |
| `skill_name` | Parsed frontmatter `name`. |
| `description` | Parsed frontmatter `description`. |
| `commit_sha` | Full SHA of the scanned repository snapshot. |

Catalog identity is `(repository_url, skill_path)`. Same-name skills and
identical definitions at different paths remain separate entries, including
copies under `.claude/skills/` and `.agents/skills/`. Rescanning must not add
duplicate entries for the same identity. There is no name- or content-based
deduplication.

Repository summaries are derived from skill rows; repositories with no skills
have no saved summary. There are no separate repository, scan-history, timestamp,
or job records. Full document bodies are transient and are not catalog data.

### Write consistency

Collect a complete scan result before changing catalog entries.
`Catalog.replace_repository` replaces only the target repository's entries in
one transaction: update existing skills, add new ones, and remove absent ones.
Repeating a scan of a commit does not duplicate entries. A successful zero-skill
scan removes that repository's previous entries, leaving other repositories
unchanged. Failed retrieval or persistence preserves the previous entries.

CLI and Web scans share this contract. Separate processes retain
last-successful-write behavior; no scan history or cross-process notification
service is introduced.

### Catalog reads

Reads perform no GitHub requests. A missing database represents an empty
catalog; an unreadable, corrupt, or unsupported database is an error. Reads do
not create, migrate, rebuild, or reset the database.

Use independent, short-lived read-only SQLite connections with a transaction
per operation. Do not share connections across request and worker threads.
Readers see either the previous complete repository entries or the new complete
entries, never a partial replacement. Repository summaries are sorted by
canonical URL; skill queries follow the shared name/path ordering.

### Schema evolution

Explicitly map persisted fields in the SQLite adapter. Append numbered
migrations in `storage/migrations.py`; do not edit shipped migrations. Use
defaults or backfills when existing rows need new values. `PRAGMA user_version`
tracks the schema version.

Migrations run under a write lock before catalog replacement. Schema changes
and their version marker commit or roll back together. Replacing repository
entries uses a separate atomic transaction. Reject newer unsupported schema
versions without modification. Never drop and recreate a catalog as an upgrade
strategy.

## Configuration and authentication

Store `catalog.sqlite3` under
`platformdirs.user_data_path("skill-atlas", appauthor=False, roaming=False)`.
Create the directory on the first write. `SKILL_ATLAS_DB` overrides the file
path; expand `~` and resolve relative overrides from the working directory.

| Platform | Typical location |
| --- | --- |
| macOS | `~/Library/Application Support/skill-atlas/catalog.sqlite3` |
| Linux | `$XDG_DATA_HOME/skill-atlas/catalog.sqlite3`, defaulting to `~/.local/share/skill-atlas/catalog.sqlite3` |
| Windows | `%LOCALAPPDATA%\skill-atlas\catalog.sqlite3` |

Credential lookup order:

1. `GH_TOKEN` environment variable.
2. `GITHUB_TOKEN` environment variable.
3. Existing GitHub CLI login via `gh auth token --hostname github.com`, when
   installed and authenticated.
4. Anonymous public access when no credential is available.

Use the credential for repository listing and content retrieval, including
on-demand Web documents. Never persist credentials in the catalog or expose
them to the browser. Access failures preserve stored entries.

The Git fallback receives the same credential through a GitHub-scoped HTTP
authorization header in the subprocess environment. Do not put tokens in
arguments, remote URLs, or files. Disable interactive credential prompts and
do not display raw Git error output.

HTTP requests use a 30-second timeout; Git commands use a 120-second timeout.
There is no automatic retry or rate-limit waiting. Adapters translate access,
rate-limit, network, and invalid-response failures into operational errors;
presentation must not expose tokens, raw subprocess output, or tracebacks.

## Evolution patterns

### Add a command or feature

Add a module in `commands/` with `register(app)` and register it in
`cli.create_app()`. Keep business behavior in an application service, reuse or
add narrow ports for actual dependencies, and wire adapters in `runtime.py`.
Catalog browsing reuses `CatalogReader` rather than expanding the scan service.
Document feature behavior and acceptance criteria in `features/` and update
the [index](README.md).

### Change a policy or add a component

Change frontmatter rules in the parser, discovery rules in the reader, and
presentation rules in the views. An alternative adapter can satisfy the same
protocol and be selected in the composition root without editing the scanner.
Give a separate responsibility a narrow interface when needed and inject it
into its consumer. Avoid speculative base classes, generic repositories, or a
universal component registry.

### Extend data or adopt technology

Update domain values and their consumers, explicit persistence mappings, and
ordered migrations when stored data changes. Update the shared catalog
contract here and feature behavior where affected. Adopted libraries and major
stack decisions belong here with their rationale; proposed choices remain in
the feature proposal until adopted. Follow the documentation, dependency, and
validation rules in [AGENTS.md](../AGENTS.md).
