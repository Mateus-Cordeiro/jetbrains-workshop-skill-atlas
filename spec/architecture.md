# skill-atlas architecture

Status: accepted and implemented. This document owns the shared architecture
and adopted technology choices. See the [specification index](README.md) for
feature behavior and [AGENTS.md](../AGENTS.md) for contribution and CI rules.

## Purpose and scope

skill-atlas discovers AI skills in GitHub repositories and stores their metadata
in a local catalog on each user's machine. One Python application exposes the
[`scan` command](features/scan.md), [`filter` command](features/filter.md),
[`similar` command](features/similar-skills.md), [`star` and `unstar`
commands](features/stars.md), and local [`serve` Web UI](features/web-ui.md).
These interfaces share the same catalog and application services for scanning,
filtering, similarity search, local stars, and explicit [AI grouping](features/skill-groups.md).
Public and private GitHub repositories are supported, subject to user access.

The catalog holds each repository's latest successfully scanned state and the
user's local stars. It is persistent application data, not a shared database or
a disposable repository cache. There is no scan history, automatic refresh, or
skill execution.

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
| Python | One implementation language for the CLI, application services, and local Web backend. Standard-library threads run the bounded organization scan workers. |
| Typer | Subcommand registration, argument validation, options, and generated help. |
| Textual | Interactive terminal results with buttons and keyboard shortcuts. |
| Rich | Text layout and terminal hyperlinks for interactive and ordinary output. |
| HTTPX | Explicit GitHub REST/GraphQL and local Ollama requests, timeouts, request hooks for cancellation, and mockable transport boundaries without a provider-specific SDK. |
| PyYAML | Safe YAML frontmatter parsing. |
| platformdirs | OS-appropriate persistent user data locations. |
| SQLite via standard-library `sqlite3` | Local transactional persistence without a database server or ORM. |
| Ollama (optional local runtime) | Run a user-installed model for explicit structured topic/capability grouping without sending catalog metadata to a hosted provider. No Python SDK, agent framework, or embeddings are needed. |
| Git 2.31 or later | Temporary partial snapshots when a repository exceeds GitHub's complete tree-listing capacity. Small repositories need no Git subprocess. |
| FastAPI and Uvicorn | HTTP routing and the local ASGI server. |
| Jinja2 | Server-rendered pages and HTML fragments with escaped metadata. |
| HTMX, plain CSS, and a small JavaScript layer | Scan submission, polling, fragment updates, selection history, and stale-response handling without a frontend build toolchain. |
| AntV G6 | Locally bundled interactive Explore graph with draggable nodes, gestures, and animations. Framework-independent; graph view state stays in plain JavaScript. |
| markdown-it-py | Markdown preview with raw HTML disabled and controlled link rendering. |

HTMX, G6 and their licenses, templates, CSS, and JavaScript are bundled with the Python
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
| Playwright Test, TypeScript, and Node.js | Desktop screenshot comparisons, traces, reports, and optional demo recordings from the same test scenarios. Development tooling and G6 vendoring only; no Node runtime dependency. |
| Docker | One pinned Linux amd64 browser/font environment for generating and comparing visual baselines locally and in CI. |
| GitHub Actions | Reproducible quality, package, Python test, and browser gates. |

Required commands, supported CI test environments, coverage requirements, and
delivery and CI status reporting are defined in [AGENTS.md](../AGENTS.md). The
workflow and manifests hold tool pins; this document need not change for routine
version bumps unless a documented constraint or architectural choice changes.

The desktop visual pilot lives in `tests/browser/visual/`, alongside the existing
Python browser suite, which retains its desktop and mobile coverage. Each
Playwright Test scenario starts its own Python server and temporary catalog.
`tests/web_environment.py` shares the real application composition and mocked
GitHub transport with pytest. A stdin protocol controls fixture responses and
scan gates; no test endpoints or controls enter the installed application.
Python and browser requests are restricted to loopback, and the container runs
without external networking after dependency installation.

Named browser screenshots are compared with reviewed PNGs in Git. Videos record
the same scenarios and are optional review evidence, not comparison inputs.
Missing baselines fail normal runs; updates are explicit and forbidden in CI.
The pinned container owns browser, OS, and fonts; `package.json` and
`package-lock.json` own the JavaScript development dependencies. Python pins stay
in their existing manifests. Baselines are generated and reviewed in that
container, not on the host OS. This adds a development toolchain in exchange for
using Playwright Test's maintained comparison and reporting features rather than
implementing a screenshot assertion framework in Python.

Coding agents share development context through curated Markdown in
[`memory/`](../memory/index.md), maintained with an
[instruction-only skill](../.agents/skills/shared-memory/SKILL.md). Keeping notes
in the repository makes them portable between Codex and Claude and reviewable
with the code they describe. Separate checkouts exchange updates through Git.
[AGENTS.md](../AGENTS.md#shared-project-memory) owns the lifecycle policy and
is read directly by both agents.

## Components and dependency boundaries

These are modules within one application, not separate services. Application
services depend on small Python `Protocol` interfaces at I/O and policy
boundaries; adapters satisfy them structurally. Immutable dataclasses carry
values between components. Constructor injection makes dependencies explicit.
No dependency injection framework or plugin loader is needed.

The source layout separates application workflows (`application/`), concrete
integrations (`adapters/`), and user interfaces (`cli/` and `web/`). Shared values,
ports, errors, settings, and the composition root remain at the package root.
Application modules depend on shared values and ports, not concrete adapters or
UI frameworks. Adapters implement the ports; interfaces adapt user input and
service results. `runtime.py` wires them together and owns I/O resource contexts.

| Module | Responsibility and extension point |
| --- | --- |
| `cli/app.py`, `cli/commands/` | Register subcommands and adapt arguments, exit codes, and presentation. |
| `models.py` | Immutable repository, organization, scan target, snapshot, organization listing, skill file, metadata, skill (including its local star), scan result, and repository summary values. |
| `ports.py` | Narrow reader, organization-reader, parser, catalog-write, repository-removal, star-write, catalog-read, and document-reader interfaces. |
| `errors.py` | Shared operational error types translated by adapters and presented by interfaces. |
| `application/scan.py` | Coordinate discovery, parsing, and atomic catalog replacement independently of HTTPX, SQLite, Typer, Textual, or Web routing. Starts from a repository or an already resolved snapshot. |
| `application/organization_scan.py` | List an organization once, apply eligibility rules, run per-repository scans through a bounded worker pool, and aggregate per-repository outcomes, progress, rate-limit stops, and cancellation. |
| `application/reader_fallback.py` | Select the fallback reader after a truncated listing without depending on HTTP or Git implementations. |
| `application/catalog.py` | Read-only catalog browsing, CLI filter results, shared name/description matching, the starred-only scope, and repository grouping/count sorting with consistent counts. |
| `application/repositories.py` | Idempotently remove one repository from the local catalog through a dedicated removal port. |
| `application/stars.py` | Idempotently star and unstar one catalog identity through the star-write port. |
| `application/documents.py` | Resolve a catalog selection and retrieve its document at the recorded commit. |
| `application/similarity.py` | Rank catalog metadata with local TF-IDF and group matching metadata. |
| `grouping.py` | Immutable grouping perspectives, identities, saved-result values, and shared group limit. |
| `application/grouping.py` | Complete-membership validation, metadata fingerprints, explicit generation, and current-catalog group views. |
| `application/grouping_jobs.py` | One process-local job generates both perspectives; duplicate submissions reuse it. |
| `adapters/ollama.py` | Structured local model requests, per-skill assignment translation, context options, truncation protection, and provider error adaptation. |
| `adapters/storage/grouping.py` | Atomic saved-group writes and consistent group/catalog read snapshots. |
| `web/grouping_routes.py` | Explore pages, workspace fragments, legacy redirects, and explicit generation/status HTTP adaptation. |
| `web/exploration.py` | Graph presentation serialization: opaque node IDs, memberships, metadata, and encoded navigation links. |
| `web/static/explore.js`, `explore.css` | G6 lifecycle, graph layout/interaction, accessible HTML directory, and per-perspective browser view state. |
| `application/scan_jobs.py` | Process-local repository and organization scan queue, progress, and worker lifecycle for the Web UI. |
| `runtime.py` | Composition root: wire catalog filtering, similarity queries, and stars, select adapters, and own HTTP, Git, scanner, organization worker, and Web application resource lifetimes. |
| `adapters/github.py` | GitHub REST and GraphQL transport, error translation, snapshot resolution, organization listing, file discovery, and commit-pinned document retrieval. |
| `adapters/git.py` | Temporary partial Git snapshots, authenticated and cancellable subprocesses, and cleanup. |
| `adapters/frontmatter.py` | YAML implementation of the metadata parser, with no network or database dependencies. |
| `adapters/storage/` | SQLite read/write adapter, star storage, and ordered schema migrations. |
| `adapters/credentials.py` | Credential resolution from the environment and GitHub CLI. |
| `cli/output/` | Shared result view models, terminal mode selection, Rich/Textual skill lists, the organization scan summary, and command-specific JSON serialization. |
| `web/app.py` | Assemble the Web app, mount assets, and manage the worker lifespan. |
| `web/routes.py` | Catalog pages, HTMX fragments, and HTTP error adaptation. |
| `web/middleware.py` | Local Host and Origin checks and browser response protections. |
| `web/rendering.py`, `web/templates/`, `web/static/` | Safe document rendering, full pages and fragments, and browser assets. |
| `config.py` | Local settings. |

Templates use `pages/` for full pages and `fragments/` for partial responses and
shared page content, with `base.html` owning the page shell and `catalog.html`
owning the navigation shared by Repositories and Explore. Shared headings, buttons,
and toggles use `app.css`; Explore-specific CSS stays within the graph workspace.
This keeps graph presentation from changing navigation geometry or page styling.
Keep the browser assets bundled beside the Web interface. Tests retain their unit, integration,
and browser levels; unit tests group application, adapter, and Web responsibilities
separately. Integration scenarios keep the real components involved together.

`SnapshotReader` lists and reads files; `RepositoryReader` also resolves a
repository snapshot. `OrganizationReader` lists an organization's repositories
with their eligibility flags and resolved snapshots. `SkillParser` extracts metadata. `Catalog` exposes
`replace_repository` to the scanner and returns the stored result, including
stars retained by surviving identities. `RepositoryRemover` exposes
`remove_repository` independently of scan writes. `StarWriter` exposes
`set_starred` to
the starring service, while `CatalogReader` exposes repository summaries, skill
lists (one repository or the whole catalog), and identity lookup, each skill
carrying its star. `DocumentReader` retrieves a file at a recorded commit
independently of scan discovery. Keep these read and write interfaces separate
as commands and views are added. Starring has its own port rather than widening
`Catalog`, so the scanner cannot change stars and the starring service cannot
replace repository entries.

Commands and Web routes invoke application services. They do not duplicate scan
logic. A Web request must not invoke a CLI command or launch a Textual view.
Terminal views receive completed results and perform no GitHub requests or
catalog writes; description toggling only changes presentation. Organization
scans print a summary rather than opening the results view.

The composition root creates a fresh scanner context for each CLI scan or Web
job, and one context per worker within an organization scan. Release HTTP and temporary Git resources on success, operational errors,
timeouts, and interruption, before opening a terminal view. The scan feature
owns [Git cleanup details](features/scan.md#github-access-strategy); the Web
feature owns [worker shutdown](features/web-ui.md#scan-execution-and-lifecycle).

### Following a scan

Start at `cli/commands/scan.py` for a terminal scan or `web/routes.py` for a Web
submission. Web submissions go through `application/scan_jobs.py`; both paths
use `runtime.create_scanner()` to supply `application/scan.py` with a reader,
parser, and catalog. `application/reader_fallback.py` selects GitHub or the
temporary Git reader, `adapters/frontmatter.py` extracts metadata, and
`adapters/storage/sqlite.py` commits the complete result. The CLI then presents
the result through `cli/output/`; the Web UI reads the job status and catalog.

### Following an organization scan

`cli/commands/scan.py` and `application/scan_jobs.py` parse the URL with the
shared scan-target rules and call `runtime.create_organization_scanner()`. It
requires a credential, then supplies `application/organization_scan.py` with
`GitHubOrganizationReader` and a worker factory. The service lists the
organization once through GraphQL, filters forks and archived repositories,
marks empty repositories, and queues the remaining snapshots in canonical URL
order. Each worker calls `Scanner.scan_snapshot()`, which reuses the
single-repository discovery, fallback, parsing, and atomic replacement from the
listed snapshot without resolving its branch again. The CLI prints the result
through `cli/output/organization.py`; the Web job records progress and failures.

**Listing.** One GraphQL query per page of 100 repositories returns each
repository's name, fork, archived and empty flags, plus its default-branch
commit SHA and root tree SHA. Snapshots are therefore resolved during listing,
once per repository, and satisfy the shared snapshot contract without separate
metadata or commit REST requests. Per repository, only the recursive tree
request and one blob request per `SKILL.md` remain; a truncated tree still
selects the temporary Git snapshot. A listing failure stops the scan before any
catalog change. GraphQL is used only for listing because it combines these
fields into one paginated request; content retrieval stays on the REST and Git
paths shared with single-repository scans.

**Concurrency.** Up to four standard-library threads scan repositories in
parallel. Each worker owns one HTTP client for its lifetime and a Git snapshot
reader per repository, so temporary Git directories are released as each
repository finishes. Catalog writes use the existing short-lived SQLite
connection and one transaction per repository; migrations take the write lock
first, so concurrent first writes are safe. Results return to the calling thread
through a queue, which reports progress and polls briefly so Ctrl+C stays
responsive. One failed repository does not affect the others. A rate-limit
error stops new repositories from starting while running ones finish. Each scan
owns its stop signal. Ctrl+C sets it, and a caller's cancellation signal, such as
a Web job's on shutdown, is forwarded to it. The scanner never sets the caller's
signal, so a failed scan cannot cancel later ones. Once stopped, the HTTP clients
refuse further requests, Git subprocesses are stopped, and every worker unwinds
its resources before the scan returns or raises. Repositories that already finished stay
committed. Four workers bound GitHub's concurrent-request load and local
resource use while overlapping network latency; threads suffice because the
work is I/O-bound and the existing adapters are synchronous.

**Rejected alternatives.** GitHub code search can miss skills (index lag, a
1,000-result cap, and a low rate limit) and is not pinned to a commit. Cloning
each repository downloads far more than the skill files needed. An `asyncio`
rewrite would duplicate the synchronous adapters without reducing requests.

### Following a document selection

The browser requests a document fragment from `web/routes.py`.
`application/documents.py` checks the selected identity and commit against the
catalog, then retrieves the document through the GitHub adapter configured in
`runtime.py`. `web/rendering.py` prepares safe Markdown and the document fragment
renders preview and source together. Selection history, source toggling, and
late document response handling stay in `web/static/app.js`.

### Following a catalog filter

`web/routes.py` adapts queries to `application/catalog.py`. Both scopes use the
same [filter matching policy](features/filter.md#shared-matching-rules) there,
keeping rules out of routes, SQL, and JavaScript.
An unfiltered homepage requests repository summaries; expanding one requests
its metadata. A filtered homepage requests all skill metadata in one read
snapshot, groups matches and counts on the server, and renders only matches.
This avoids transferring every catalog entry to the browser or doing one query
per repository. It uses a linear in-memory pass on the local backend; pagination
and indexed full-text search are not introduced for this metadata-only catalog.
`web/static/filters.js` handles query and starred-only history, expansion
state, repository count sorting, and cancellable list requests separately from
document loading. No filtering operation reads
GitHub, changes the catalog, or retrieves document bodies.

`cli/commands/filter.py` invokes `BrowseCatalog.filter()` through
`runtime.create_catalog_browser()`. This operation reads the selected scope
once through `CatalogReader.skills()`, returning matches and the scope count
from that snapshot. It also returns all skills for an empty query, independently
of the homepage's lazy loading. `cli/output/results.py` adapts the result for the
shared terminal views; `cli/output/filter.py` serializes lossless JSON. The command
does not construct a scanner, HTTP client, or Web app, or resolve credentials. Reusing the matching policy keeps CLI and Web
results consistent without coupling command output to browser view state. See
the [filter specification](features/filter.md) for command and output contracts.

Homepage, repository, and similarity skill lists share `fragments/skill-entry.html`
for compact descriptions, expansion controls, and links to similarity search.
Similarity results supply their selection URL, repository label, and optional
score; the shared card owns their presentation. Grouped location links remain
in the similarity workspace, where repository/path disambiguation is needed.
Description expansion stays in
`web/static/app.js`, with controls initialized after list updates from
`web/static/filters.js` as well as page and workspace loads.

### Following a repository removal

The homepage X action confirms deletion of local skills and stars, then
`POST /repositories/remove` invokes `application/repositories.py`, wired through
`runtime.py`. Its narrow `RepositoryRemover` port lets the SQLite adapter delete
only the canonical repository's skill rows in one write transaction. Repeated
removals succeed, including when the catalog is absent, without creating it.
Migration and failure handling reuse the existing write path. No GitHub access,
credentials, scan, or AI generation is involved. Saved grouping definitions stay
unchanged; current-catalog membership resolution hides removed skills and marks
changed inputs stale. `web/static/repositories.js` owns confirmation and submission;
`filters.js` refreshes the list with its current query, starred scope, and sort.

### Following a star change

`cli/commands/stars.py` and the `POST /stars` route in `web/routes.py` adapt a
repository URL, exact path, and requested state to `application/stars.py`, wired
by `runtime.create_stars()` or `runtime.create_web_app()` without credentials or
network clients. The service calls `StarWriter.set_starred()`; the SQLite adapter
migrates under the write lock, then checks the identity and writes the star in
one transaction. Reads return each row's star, so `application/catalog.py`
restricts the starred-only scope before applying the unchanged matching rules,
and the CLI and Web presentations mark starred skills. `web/static/stars.js`
sends toggles and updates every control for the same identity; `filters.js`
owns the `starred=1` list state alongside `q`. Starring never reads GitHub or
starts a scan. See the [stars specification](features/stars.md).

### Following a similarity search

`web/routes.py` and `cli/commands/similar.py` adapt a source identity to
`application/similarity.py`, wired by `runtime.py`. The CLI uses
`runtime.create_similarity()` to configure a local catalog reader without
credential or network setup. The service reads all catalog
skills once through `CatalogReader.skills()`, resolving the source from the
same transaction as candidates. It computes TF-IDF scores and groups matching
metadata without document retrieval or catalog writes. The workspace reuses the
shared skill card with a score fragment, keeping description and selection
behavior consistent across lists; selecting a match uses the existing document
service. The CLI adapts completed results through `cli/output/results.py` for the
shared terminal views, or uses `cli/output/similarity.py` for JSON output.
Presentation never adds ranking or grouping rules.

Ranking lives in an application service so both interfaces reuse the
policy. SQLite remains responsible only for consistent reads, and routes only
adapt parameters and presentation. Standard-library sparse dictionaries and
math suffice for the initial lexical algorithm, avoiding a numerical runtime
dependency. On-demand computation avoids an index invalidation protocol across
CLI and Web processes, at the cost of recalculation per search. No schema change,
new persistence, embedding model, or remote service is introduced. See the
[similar-skills specification](features/similar-skills.md) for ranking rules.

### Following group generation

`web/grouping_routes.py` submits one paired job to `application/grouping_jobs.py`.
`runtime.py` supplies `application/grouping.py` with `SQLiteGroups` and a fresh
HTTPX/Ollama adapter. Ollama numeric environment values remain unparsed in shared
settings until this explicit job starts. The composition root validates positive,
finite timeouts and positive integer token limits before creating a client;
an explicit context override must exceed the output limit. Invalid values raise
`GroupingError` naming the variable, without affecting scans, filtering,
similarity, or Web startup.
The application reads metadata once, invokes the provider
sequentially for both perspectives, validates both complete memberships, and saves
them atomically. Provider prompts, schemas, context handling and failures remain in the
adapter; completeness, identity, and group-count policy remain in the application.
The Ollama schema requires every skill's assignment and caps proposed titles at
12. The adapter translates numbered assignments into the shared membership format,
discarding unused proposed titles. The application independently validates all
published groups and identifies the failing perspective in errors. Neither the
provider wire format nor its translation changes saved catalog identities.

Context defaults to Ollama's model/server configuration; the adapter sends `num_ctx`
only for an explicit override. Ollama enforces the actual token limit with input
truncation and context shifting disabled, replacing the former UTF-8 byte estimate.
The adapter verifies a stable Ollama release of at least 0.13.0 once per generation,
before sending metadata, because older servers may ignore these flags. This keeps
model-specific tokenization and resource defaults with Ollama while preserving
complete input and atomic publication on context failures. Output and timeout
limits remain explicit; no tokenizer library or model-discovery service is added.

Graph reads use one SQLite transaction for both saved perspectives and current
skill rows. Fingerprints detect scans from any process. `web/exploration.py`
serializes presentation data; it does not infer memberships. The Explore page
includes both views and `web/static/explore.js` switches locally, expands groups,
keeps one node per exact skill identity, and owns G6 cleanup and tab-scoped view
state. `app.js` handles scan/generation completion refreshes. Skill links reuse the
repository/document page and its existing document service; `from_explore` is
restricted to the two perspective values for return navigation.

G6 adds a browser renderer without introducing React or changing Python service
boundaries. It is vendored from the exact npm lockfile version using
`scripts/vendor-g6.mjs`, including transitive license notices. Python distributions
ship the checked-in bundle; no CDN, npm install, or Node process is required to
serve the app. The tradeoff is a larger static asset, loaded only on Explore.
The graph renderer uses an anonymous container, isolated from HTMX attribute
settling, and preserves the existing CSP. HTML group/skill controls provide a
keyboard and rendering-failure alternative to the canvas.

This retains a separate inference worker so slow AI requests cannot block scans.
The [feature specification](features/skill-groups.md) owns grouping and graph behavior.

## Shared CLI results presentation

`scan`, `filter`, and `similar` share terminal presentation in `cli/output/`.
`results.py` adapts their completed service results into immutable `ResultsView`
and `SkillEntry` values; `presentation.py` selects the output mode, `console.py`
renders Rich output, and `tui.py` provides the Textual results app. Keeping this
model in the CLI lets the renderers share layout and interaction without forcing
scan, filter, and similarity services to return the same domain result. JSON
serializers retain each command's existing machine-readable schema.

- Open the interactive view only when stdin and stdout are terminals and the
  terminal is not dumb. Every catalog command accepts `--no-interactive` to
  print and exit. Redirecting either stream falls back to printed output.
  Where supported, `--json` always prints and exits, including alongside
  `--no-interactive`.
- Both views show the command summary, then numbered entries with name,
  description, repository/path, and commit-pinned URL in the same order.
  A ★ follows the name of a [starred](features/stars.md#terminal-and-json-output)
  skill, then any similarity percentage. Multiple locations
  carry a **Same metadata · N locations** label and all location links.
  Preserve service ordering, grouping, and command-specific empty messages.
- Descriptions start visible. The interactive view scrolls, supports keyboard
  focus and link activation, and offers a **Hide descriptions** / **Show
  descriptions** button, `d` to toggle all descriptions, and `q` to exit.
  Links open in the default browser. Printed output always includes descriptions.
- Wrap names, descriptions, paths, and URLs to terminal width. Render metadata
  literally and strip terminal control sequences. Printed URLs stay visible;
  capable terminals may also make them hyperlinks. Redirected stdout contains
  no styling or terminal controls, even when colour is forced by the environment.
  JSON preserves original values with JSON escaping.

Views perform no I/O beyond presentation and opening a user-activated link;
scanning, filtering, ranking, and resource cleanup finish before presentation.
Feature specs own summaries, source context, scores, and empty-state wording.

## Shared domain contracts

Accept repository URLs in `https://github.com/owner/repository` form, allowing
a trailing slash, `.git` suffix, and the default HTTPS port. Reject credentials
in URLs, query strings, fragments, and paths below the repository. Normalize
catalog URLs to `https://github.com/{owner}/{repository}` with lowercase owner
and repository. Display names use `owner/repository` form.

Scan targets also accept an organization URL in `https://github.com/organization`
form: an owner with no repository, allowing a trailing slash and the default
HTTPS port, under the same credential, query, and fragment restrictions. Its
canonical URL is `https://github.com/{organization}` in lowercase, and its
display name is the organization login. Organization URLs identify scan work
only; catalog identity remains per repository.

Resolve a scan's default branch once. Its snapshot contains the full commit SHA
and tree SHA, and all file reads use that snapshot. An organization scan
resolves each repository's snapshot once, while listing, and scans that
snapshot without resolving the branch again. A stored commit identifies
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
| `starred` | Whether the user starred this identity locally; `0` for new rows. |

Catalog identity is `(repository_url, skill_path)`. Same-name skills and
identical definitions at different paths remain separate entries, including
copies under `.claude/skills/` and `.agents/skills/`. Rescanning must not add
duplicate entries for the same identity. There is no name- or content-based
deduplication.

`starred` is local user state, not scanned metadata, so scan writes never set
it. Keeping it on the skill row ties a star to the identity's lifetime: a star
cannot outlive its skill, and no separate cleanup or join is needed. In
exchange, every scan write must update surviving rows in place rather than
replacing them. Stars are not GitHub stars and are never synced.

Repository summaries are derived from skill rows; repositories with no skills
have no saved summary. There are no separate repository, scan-history, timestamp,
or job records. A separate `skill_groupings` table holds the latest derived topic
and capability results, with model names, input fingerprints, and JSON-encoded
repository/path memberships. These are classification data, not scan history.
Full document bodies are transient and are not catalog data.

### Write consistency

Collect a complete scan result before changing catalog entries.
`Catalog.replace_repository` replaces only the target repository's entries in
one transaction: update existing skills in place, add new ones, and remove
absent ones.
Repeating a scan of a commit does not duplicate entries. A successful zero-skill
scan removes that repository's previous entries, leaving other repositories
unchanged. Failed retrieval or persistence preserves the previous entries.
Updating in place leaves `starred` untouched, so surviving identities keep their
stars, and removing a row removes its star. A moved path is a new, unstarred
identity. Other repositories' stars are unchanged, and a failed replacement
preserves them.

`RepositoryRemover.remove_repository` atomically deletes all skill rows and their
stars for one canonical repository, preserving every other repository. It is
idempotent, does not create a missing database, and follows the same migration and
rollback rules as other explicit writes. Separate processes and in-flight scans
retain last-successful-write behavior: a scan committed after removal can add
that repository again. Removal does not cancel queued or running work.

`StarWriter.set_starred` sets or clears `starred` on an existing identity in one
write transaction, changing no other field. It is idempotent and does not create a missing
catalog, because a missing catalog has no skills to star.

CLI and Web scans share this contract. Separate processes retain
last-successful-write behavior; no scan history or cross-process notification
service is introduced.

### Catalog reads

Reads perform no GitHub requests. A missing database represents an empty
catalog; an unreadable, corrupt, or unsupported database is an error. Reads do
not create, migrate, rebuild, or reset the database. A catalog at schema version
1 or 2, created before stars, has no `starred` column; it remains readable, with every
skill unstarred, without changing the file. The next explicit write migrates it.

Use independent, short-lived read-only SQLite connections with a transaction
per operation. Do not share connections across request and worker threads.
Readers see either the previous complete repository entries or the new complete
entries, never a partial replacement. Repository summaries are read in canonical
URL order. The catalog application
service can sort homepage groups by total stored skill count ascending or
descending, with canonical URL ascending as the tie-break; no sort retains URL
order. Filtering does not change which count is sorted. This is presentation
ordering and does not alter skill order or storage; skill queries follow the
shared name/path ordering. A skill
query without a repository returns the whole catalog, ordered by canonical
repository URL, then name/path, in one transaction. Derive filtered groups,
matching counts, and repository totals from that same result so concurrent
replacement cannot mix versions in one response.
Similarity resolves its source and candidates from that same snapshot. Ranking
changes presentation order only and must not alter catalog identity or storage.

### Schema evolution

Explicitly map persisted fields in the SQLite adapter. Append numbered
migrations in `adapters/storage/migrations.py`; do not edit shipped migrations. Use
defaults or backfills when existing rows need new values. `PRAGMA user_version`
tracks the schema version.

Migrations run under a write lock before catalog replacement, explicit grouping
persistence, a star change, or repository removal. Schema changes and their
version marker commit or roll back together. Repository replacement, removal,
and star changes each use a separate atomic transaction. Reject newer unsupported schema versions
without modification. Never drop and recreate a catalog as an upgrade strategy.

Version 2 adds only the derived grouping table. Version 3 adds the `starred`
column with a default of `0`, so existing catalogs
upgrade in place on their next write without rewriting skill rows. Reads accept the
previous versions, as described under [Catalog reads](#catalog-reads), so
upgrading skill-atlas does not require a rescan before browsing or filtering.

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
4. Anonymous public access when no credential is available. Organization
   scans require a credential and fail before any request without one.

Use the credential for repository listing and content retrieval, including
on-demand Web documents. Never persist credentials in the catalog or expose
them to the browser. Access failures preserve stored entries.

The Git fallback receives the same credential through a GitHub-scoped HTTP
authorization header in the subprocess environment. Do not put tokens in
arguments, remote URLs, or files. Disable interactive credential prompts and
do not display raw Git error output.

HTTP requests use a 30-second timeout; Git commands use a 120-second timeout.
There is no automatic retry or rate-limit waiting; adapters report rate limits
as a distinct operational error so organization scans can stop starting new
repositories. Adapters translate access,
rate-limit, network, and invalid-response failures into operational errors;
presentation must not expose tokens, raw subprocess output, or tracebacks.

### Local model configuration

Optional Ollama settings select the loopback HTTP endpoint, installed model tag,
request timeout, optional context override, and reserved output tokens; defaults
and environment variables are documented in [README](../README.md#ai-topic-and-capability-groups).
Only explicit generation constructs an Ollama client. It uses no GitHub headers
or credentials, follows no redirects, and ignores environment proxy settings.
Only loopback HTTP endpoints without embedded credentials, paths, or queries are
accepted. Users must select a locally installed model; hosted/cloud models are
outside this feature. Normal scans, browsing, filtering, and lexical similarity
need no Ollama server. No model is installed or started automatically.

## Evolution patterns

### Add a command or feature

Add a module in `cli/commands/` with `register(app)` and register it in
`cli.app.create_app()`. Keep business behavior in `application/`, reuse or
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
