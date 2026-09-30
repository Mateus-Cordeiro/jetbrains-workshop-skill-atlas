# skill-atlas Web UI

Status: accepted and implemented. This document defines a local Web UI for
browsing the catalog, submitting scans, and reading skill definitions. The
[shared architecture](../architecture.md) owns the stack, component boundaries,
authentication, snapshot consistency, and catalog contracts. The
[scan specification](scan.md) owns discovery, parsing, and repository access.

## Purpose and scope

Provide a browser page where the user can:

- Browse repositories represented in the local catalog.
- Submit a GitHub repository URL to scan, or rescan an existing repository.
- Select a repository and see its skills in a left pane.
- Select a skill and read its `SKILL.md` in a right pane.

The first version runs on the user's machine and shares the CLI's SQLite
catalog and GitHub credentials. Public and private GitHub repositories follow
the existing access rules. This is a single-user local application.

### Agreed storage constraints

- Keep the existing `skills` table and catalog identity rules. Do not add a
  repository table, scan history, scan timestamps, or persisted scan jobs.
- Derive the repository list from stored skill entries. A repository with no
  stored skills does not appear in that list.
- A completed scan with zero valid skills displays **No skills found**. It
  remains a successful scan and removes that repository's previous entries,
  following the existing replacement behavior.
- Retrieve each selected document from GitHub using its stored repository,
  path, and commit SHA. Do not persist document content or require offline
  document viewing.
- Add catalog read operations separately from the scanner's write interface.

No database schema migration or backfill is required for this feature. Existing
catalogs can supply the repository list, skill metadata, and document locations
without rescanning.

## Starting the application

Start the local server with the `serve` subcommand:

```sh
skill-atlas serve
```

The command starts a local HTTP server, prints its browser URL, and remains
running until stopped. Bind to `127.0.0.1` by default; expose a `--port` option
with a default of `8000`. An unavailable port produces a clear startup error.
Opening the printed URL is sufficient; automatic browser launch is optional
future work.

Resolve the catalog through the existing settings, including `SKILL_ATLAS_DB`.
Preserve the existing `scan` command and its terminal presentation. Register
`serve` through the normal command-registration mechanism.

## Pages and interaction

### Repository page

The home page contains a repository URL input, a **Scan** button, and a list of
repositories derived from the catalog. Each repository displays:

- Its `owner/repository` name.
- Its number of stored skills.
- Its scanned commit, abbreviated for display with the full SHA available.
- An action to open its skills.

Sort repositories deterministically by their canonical repository URL. Do not
display a last-scan time: the current catalog does not contain that information.
An empty catalog shows an explanation and the scan form. A catalog read failure
shows an error rather than being presented as an empty catalog.

Validate and normalize submitted URLs with the same rules as the CLI. Invalid
input receives an inline error and does not start a scan.

### Skill filtering and expandable repositories

The homepage has a **Filter skills across repositories** field above its
repository list. Each repository has a separate keyboard-accessible chevron
button to expand its skills inline; the repository name opens the detail page.
Expanded entries show skill name, description, and exact path. Selecting one
opens that repository with the document selected and the filter carried over.
Unfiltered repositories begin collapsed and load metadata from the local backend
only when expanded. Loading failures offer **Retry**.

Both views use the same server-side matching policy: split the query on
whitespace, case-fold Unicode text, and require every term to occur as a literal
substring in either the name or description. Terms may match different fields;
paths, repository names, and document bodies are not searched. Empty or
whitespace-only queries show all entries. Wildcards and regular expressions
have no special meaning. Preserve repository and skill ordering and keep
same-name entries at different paths separate.

The homepage displays only repositories with matches and reveals matching
skills automatically, including previously collapsed repositories. Show the
matching total and repository count, plus **3 of 24 skills** per repository.
Users can collapse matching groups manually; preserve those choices while
editing the query. Clearing the query restores the expansion choices from
before filtering. A page URL containing a query initially reveals matches.

The repository view has a **Filter skills in this repository** field in its
sticky left-pane heading. It updates only the skill list and shows the matching
and total counts. Keep the current document, scroll position, and source/preview
mode even when its skill no longer matches; display **The open skill is hidden
by the filter.** Never automatically select another match. Clearing the filter
restores the selected entry's visible state.

Filter as the user types with a short debounce, without page reload or GitHub
requests. Provide a clear button; Escape clears a focused field. Keep focus in
the field while updating results, announce counts accessibly, and exclude hidden
entries from keyboard navigation. Distinguish **No skills match “…”** with a
**Clear filter** action from an empty catalog or repository. Query failures
retain the previous results and offer **Retry**, rather than showing no matches.

Store the query in the URL's `q` parameter with replacement history updates, so
keystrokes do not create history entries. Selection links preserve it. Refresh
and browser back/forward restore the query and selection; homepage expansion
choices are saved in that history entry, not persistent browser storage.
Reapply the query after successful scans and retain expansion choices for
remaining repositories. Discard superseded filter responses and detached
expansion responses, independently of document selection requests.

### Repository detail

Show the repository name, scanned commit, a **Rescan** button, and navigation
back to the repository list above a two-pane view:

| Left pane: skills | Right pane: selected `SKILL.md` |
| --- | --- |
| Skill name, description, and repository-relative path. | Document path, scanned commit, and link to the file on GitHub. |
| Skills sorted by name, then path. | Rendered Markdown by default, with a **Source** toggle. |
| A visible selection state. | Loading, content, or a retrieval error with **Retry**. |

Initially show **Select a skill to view its SKILL.md** in the right pane. Select
skills by `(repository_url, skill_path)`, never by name. Identical definitions
copied into different directories and same-name skills remain separate entries.

The source view displays the complete decoded file, including YAML frontmatter.
The rendered view displays frontmatter separately as escaped source text and
renders the Markdown body. Switching views reuses the document already loaded
for the current selection and does not trigger another GitHub request.

Both panes must support long content without making navigation inaccessible.
On narrow screens, stack the skill list and document vertically. Use semantic
links and buttons, visible keyboard focus, and accessible loading/error states.

Repository and skill selections belong in the page URL so that refresh and
browser back/forward navigation restore the selection. Refresh reads the
current catalog; it does not retain older catalog snapshots.

### Empty results

After a successful zero-skill scan, show the repository name and **No skills
found** in the scan outcome/detail view. Clear any previous skill selection and
document. The repository disappears from the catalog-derived repository list.

A detail URL with no current skill rows shows **No skills found** and offers
**Scan**. It cannot distinguish a repository that has never been scanned from a
previous zero-skill result. After the process restarts, there is no record of
that earlier successful scan or its commit.

### Scan feedback

The browser submits a scan and receives a job identifier promptly. Show queued,
running, succeeded, or failed status while the user can continue browsing.
Status is sufficient; precise progress percentages are outside this version.

After success, refresh the repository list and the selected repository's skills
from the catalog. If the selected path still exists, reload its document using
the newly stored commit. Otherwise clear the selection. Display the resulting
skill count, including zero.

Queued and running notices remain visible until the scan finishes. A successful
notice disappears after five seconds and can also be dismissed immediately.
Replacing the activity panel must not restart that countdown. Past successes
are hidden on page load; dismissed notices must not reappear when another scan
is submitted or the user navigates within the same browser tab. Hide the empty
activity area once no notices remain.

After failure, show a useful error with **Retry scan** and a dismiss button.
Failed notices do not expire automatically, so users can read the error and
retry at their own pace. Remember dismissal using only opaque job IDs in browser
session storage; it does not alter job execution, the server's bounded job
registry, or the catalog. Dismissal still works on the current page if browser
storage is unavailable. Existing successful catalog entries remain available.
A failed first scan does not create a saved repository.
Keep the previous successful results visible during a rescan, labelled with
their stored commit until the new scan succeeds.

## Document retrieval

The backend looks up the selected catalog entry and retrieves its document from
GitHub at the stored full commit SHA. For example, GitHub's contents API accepts
the repository-relative path and `ref=<commit_sha>`. Encode the path correctly
and request file content, accounting for the API's response format and errors.
The existing scan reader uses blob SHAs; the catalog does not store those SHAs,
so the document reader needs a separate operation accepting repository, path,
and commit.

Do not resolve the default branch again, scan the repository, or infer document
text from the stored name and description. Those fields locate and describe a
skill but do not contain its full definition. If the recorded commit or file is
unavailable, report that failure instead of substituting the current branch.

Use the existing credential lookup order and HTTP timeout. Requests originate
from the backend so private repository access works without exposing GitHub
credentials to the browser. Credential, permission, rate-limit, missing-file,
network, decoding, and unsupported-response failures are document errors; they
do not change catalog entries or trigger an automatic rescan.

Decode UTF-8 with the same allowance for an initial byte-order mark as scanning.
Document content is transient request/view state. Do not write it to SQLite,
files, browser local storage, or a persistent application cache. Send document
responses with `Cache-Control: no-store`. Offline document viewing is not a
supported feature.

The request includes the commit displayed in the selected skill's metadata.
If the catalog entry has disappeared, report it as unavailable; if its commit
has changed, return a conflict and refresh the skill list before loading again.
Once a request has resolved an entry, its fetch stays pinned to that commit.
The browser must discard late responses for a different selection or superseded
commit so rapid clicks and rescans cannot display the wrong document.

### Rendering rules

Treat repository metadata and document contents as untrusted display data.
Escape metadata and source text, disable embedded raw HTML in Markdown, and
allow only safe link schemes. Never execute scripts, repository code, or skill
instructions. Resolve repository-relative document links against the selected
file's directory at the scanned commit, not the local server's filesystem.

Show images as links in the first version rather than fetching remote media
automatically or forwarding credentials to their hosts. The **View on GitHub**
link uses the existing encoded, commit-pinned skill URL.

## Components and boundaries

`web/app.py` assembles the interface and manages the worker lifespan;
`web/routes.py` adapts requests and errors, and `web/middleware.py` applies local
request protections. Full-page templates live in `web/templates/pages/` and
shared fragments in `web/templates/fragments/`. Document loading and scan jobs
live in `application/documents.py` and `application/scan_jobs.py`; safe Markdown
rendering remains in `web/rendering.py`.

Use the adopted [runtime stack](../architecture.md#runtime) and shared
[component boundaries](../architecture.md#components-and-dependency-boundaries).
Web routes adapt HTTP requests to catalog queries, scan jobs, and document
services; templates and HTMX return pages and fragments. Use
`application/catalog.py` for shared matching and grouped read results.
Keep selection history and document response handling in `web/static/app.js`,
and filtering, expansions, and independent list response handling in
`web/static/filters.js`. Package the required templates and static assets so the installed command works outside
the checkout.

The scanner continues to use the catalog-write port. The document service uses
catalog-read and document-reader ports; browsing never invokes the CLI or the
Textual view. Reuse the shared [catalog read contract](../architecture.md#catalog-reads),
including missing-database handling, schema checks, independent connections,
and consistent read snapshots during atomic scan replacement.

A page refresh sees changes made by CLI scans. Live cross-process notifications
are outside scope.

## Scan execution and lifecycle

Run scans outside the HTTP event loop using one background worker per server
process. Use an in-memory queue and job registry; no external worker service or
durable queue is needed. Poll job status while it is queued or running and stop
polling on completion or failure.

Reuse an existing queued/running job for repeated submissions of the same
normalized repository URL. Keep at most 16 queued jobs and retain the most recent 64 completed jobs;
reject new work clearly if the queue is full. These limits and job IDs
are process-local and are not catalog data.

Each job owns a fresh scanner context through the existing composition root.
Reuse the scanner's default-branch resolution, readers, fallback rules, parser,
atomic replacement, timeouts, and resource cleanup. Catch operational failures
at the job boundary and keep the server and worker available for later jobs.

Closing the browser does not cancel a submitted scan. Graceful shutdown stops
accepting jobs, discards queued jobs, and lets the active scan unwind and clean
up its HTTP/Git resources. No jobs resume after a process restart. A missing
job ID produces **Scan status is no longer available; refresh the catalog**.
After an unexpected stop, a scan may already have committed its results; the
catalog is the source of truth, not the lost in-memory job status.

## HTTP contract

The following routes define the interface. The `q` filter is optional on all
catalog routes. Repository arguments use canonical GitHub URLs; skill paths use exact stored paths. Encode all query
parameters rather than interpolating unescaped values into URLs.

| Method and route | Behavior |
| --- | --- |
| `GET /?q=...` | Repository page, optional skill filter, and scan form. |
| `GET /repository?repository_url=...&skill_path=...&q=...` | Repository detail; skill selection is optional. |
| `GET /fragments/repositories?q=...` | Catalog-derived repository list with matching skills when filtering. |
| `GET /fragments/repository?repository_url=...&skill_path=...&q=...` | Refresh the two-pane workspace; skill selection is optional. |
| `GET /fragments/repository-skills?repository_url=...&q=...` | Inline skill metadata for an expanded homepage repository. |
| `GET /fragments/skills?repository_url=...&skill_path=...&q=...` | Filtered repository skill list and counts without replacing the document. |
| `GET /fragments/document?repository_url=...&skill_path=...&commit_sha=...` | Document fragment containing escaped source and safe rendered content. |
| `POST /scans` | Validate form-encoded `repository_url`; return `202` with scan activity fragments and a job status URL in `Location`. |
| `GET /scans/{job_id}` | Job status fragment with identity, state, and outcome or error. |

Return escaped HTML errors with a stable `data-error-code` and user-facing
message. Invalid
input uses `400`; missing catalog entries and unknown job IDs use `404`; stale
document selections use `409`. Distinguish upstream retrieval failures, local
storage failures, and a full scan queue without returning tokens, raw subprocess
output, or tracebacks. An accepted scan that later fails reports `failed` in
its job fragment rather than changing the original submission response.
Document retrieval failures use `502`, catalog failures use `500`, and queue
capacity or shutdown rejections use `503`. HTMX displays error fragments in
the relevant panel; stale selections refresh the workspace before loading again.

Bind only to loopback in this version. Validate allowed Host and Origin values
and protect scan submissions against cross-origin requests. Scan submissions
require a matching Origin and the custom `X-Atlas-Request: 1` header sent by the UI. Do not enable
permissive CORS. Browser requests can select existing catalog entries but cannot
provide arbitrary upstream content URLs or credentials for the server to fetch.

## Outside this version

- Hosted or multi-user deployment, remote access, and browser-based GitHub login.
- Persistent records for repositories without skills, scan dates, or job history.
- Stored document bodies, persistent document caching, and offline viewing.
- Scheduled scans, durable background jobs, cancellation controls, or live logs.
- Scan history, version comparisons, and branch or tag selection.
- Skill editing, installation, execution, or repository changes.
- Additional Git hosting providers and automatic embedded-media retrieval.

## Acceptance and verification

Implementation must cover these user-visible outcomes:

1. Starting with no catalog displays an empty repository page and accepts a
   valid scan. Invalid input starts no job.
2. Existing CLI-populated catalogs display repositories, counts, commits, and
   deterministically sorted skills without rescanning or changing the schema.
3. A successful Web scan becomes visible in the shared catalog; a rescan adds,
   updates, and removes entries atomically while leaving other repositories
   unchanged. Same-name and copied skills remain distinct.
4. Zero-skill scans show **No skills found**, clear previous results, and leave
   no repository entry in the saved list. A detail link with no rows has the
   same empty view.
5. Selecting root or nested skill paths, including spaces and URL-significant
   characters, retrieves the exact stored commit even if the default branch
   has moved. Source includes the frontmatter; preview and source use the same
   fetched document.
6. Private document requests use backend credentials. Retrieval failures offer
   retry, retain catalog metadata, and never substitute another commit.
7. Browsing remains usable during scans. Duplicate active submissions reuse a
   job; job errors and queue limits have clear outcomes; resource cleanup and
   process restart follow the documented lifecycle. Successful notices expire
   after five seconds without hiding active scans. Failed notices remain until
   dismissed, and dismissed notices stay hidden across navigation and further
   submissions in the same tab.
8. Failed scans preserve previous catalog entries. Stale selections and late
   document responses cannot overwrite the currently selected document.
9. Unsafe Markdown, metadata, links, and cross-origin scan requests cannot
   execute content or expose credentials. No document content is persisted.
10. Homepage repository expansion loads only catalog metadata. Both filter scopes
    apply identical matching, counts, and ordering, including Unicode, multiple
    terms across fields, literal punctuation, duplicate names, and empty queries.
    Nonmatches and query failures have distinct, recoverable states.
11. Filtering preserves document content and source mode, even for a hidden
    selection. Queries and homepage expansions survive refresh and back/forward;
    clearing restores earlier expansions. Successful rescans reapply filters and
    late list/expansion responses cannot replace newer state. All controls work
    with keyboard navigation and narrow layouts without external requests.
12. Keyboard navigation, narrow layouts, refresh/back navigation, loading
    states, and errors remain usable. The installed package serves its assets
    outside the checkout, and existing CLI behavior remains intact.

Follow [the repository testing rules](../../AGENTS.md). Use unit tests for query
and job policies and document handling, and integration tests with temporary
SQLite catalogs, the real application composition, and mocked GitHub transport.
Exercise browser interactions and rendering without live GitHub or real
credentials. Preserve the existing API and local Git fallback scan scenarios.

For changes to this feature, follow the local, browser, and installed-wheel
checks in [AGENTS.md](../../AGENTS.md#required-local-checks). Browser checks use
Playwright with Chromium and a temporary loopback server; all GitHub requests
are mocked. CI also verifies the installed command and packaged Web assets
outside the checkout.
