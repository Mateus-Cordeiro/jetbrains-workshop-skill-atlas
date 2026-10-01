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
- Submit a GitHub organization URL to scan all of its eligible repositories.
- Select a repository and see its skills in a left pane.
- Select a skill and read its `SKILL.md` in a right pane.
- Find similar skills across the catalog, see scores, and inspect matches.
- Explicitly generate both topic/capability views and explore their overlapping
  memberships in the G6 graph;
  [Skill groups](skill-groups.md) owns their model, persistence, and HTTP contracts.
- Star skills locally and show only starred skills.

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
- Store [local stars](stars.md) in the `starred` field defined by the
  [catalog model](../architecture.md#catalog-model-and-identity), written only
  through the star service.

Browsing requires no schema migration or backfill. Existing catalogs, including
those created before stars, supply the repository list, skill metadata, and
document locations without rescanning. Explicit writes for scans, stars, or [skill grouping](skill-groups.md) migrate
the catalog transactionally.

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

### Homepage

Offer **Repositories** and **Explore** catalog navigation. Keep the shared light
color scheme when navigating between catalog, Explore, and document pages.
Repositories and Explore share one catalog template and navigation layout; their
content uses the same width, padding, headings, buttons, and toggle styles.
Switching tabs must not move or resize the navigation, including on wide desktops.
Start the repository content with a compact **Repositories** heading and count, a search
field, and **Scan GitHub…**. Omit the introductory hero and permanent scan card
so the catalog is immediately visible. The scan action opens a modal dialog
headed **Scan repository or organization**, focusing its **GitHub URL** field.
Show examples of both URL forms. The submit button starts as **Start scan** and
changes to **Scan repository** or **Scan organization** based on the entered URL
shape; the server remains authoritative for validation. For an organization,
show **Scans repositories in this organization, excluding forks and archived
repositories.** before submission.

Keep focus inside the modal. Escape, Cancel, and the close button dismiss it,
restore focus to the opener, and retain the entered URL. Opening the dialog must
not move the repository list. Keep submission and connection errors inside the
open dialog, preserving the input for correction or retry. After the server
accepts the scan, close the dialog and show progress in the existing activity
area. If the user closes it while submission is pending, report any later error
above the catalog rather than hiding it in the closed dialog.

An unfiltered empty catalog offers the same **Scan GitHub…** action in its empty
state. Do not open the dialog automatically on arrival, a filter update, or when
the last repository disappears. Keep the toolbar and dialog in place when
results refresh, updating the heading's repository count with the list.
Each repository displays:

- Its `owner/repository` name.
- Its number of stored skills.
- An action to open its skills.

Sort repositories deterministically by their canonical repository URL. Do not
display a last-scan time: the current catalog does not contain that information.
An empty catalog shows an explanation and an action to open the scan dialog.
Do not display commit hashes or a rescan action in the repository list.
A catalog read failure shows an error rather than being presented as an empty catalog.

Validate and normalize submitted URLs with the same rules as the CLI. The same
field accepts an [organization URL](scan.md#organization-scans); its examples
and organization hint make both scopes visible.
Invalid input receives an inline error naming both URL forms and does not start
a scan.

### Skill filtering and expandable repositories

The homepage toolbar has a compact **Search skills…** field, accessibly labelled
**Filter skills across repositories**. The repository pane uses the same field,
labelled **Filter skills in this repository**. On desktop the fields remain
visible. At narrow widths, a magnifying-glass button labelled **Search skills**
reveals and focuses the field; it can collapse an empty field. An active query
always keeps the field visible, including after refresh, navigation, or resizing.
Clearing a query keeps the field open and focused; closing it is a separate action.

Each repository has a separate keyboard-accessible chevron button to expand its
skills inline; the repository name opens the detail page.
Expanded entries show skill names and two-line description previews with the
same independent **Show more** / **Show less** controls as the repository view.
Paths are omitted from these entries. Selecting one opens that repository with
the document selected and the filter carried over.
Unfiltered repositories begin collapsed and load metadata from the local backend
only when expanded. Loading failures offer **Retry**.

Both views use the server-side [shared filter matching rules](filter.md#shared-matching-rules).
The CLI uses the same policy. This section owns browser interaction and
presentation.

The homepage displays only repositories with matches and reveals matching
skills automatically, including previously collapsed repositories. Show the
matching total and repository count, plus **3 of 24 skills** per repository.
Users can collapse matching groups manually; preserve those choices while
editing the query. Clearing the query restores the expansion choices from
before filtering. A page URL containing a query initially reveals matches.

The repository view has a **Filter skills in this repository** field in its
sticky left-pane heading. It updates the skill list and the single count above
the search field: **24 skills** unfiltered, or **3 of 24 skills** while filtering.
Keep this count in the sticky heading; do not repeat it below the search field or
beside the repository name. Keep the current document, scroll position, and source/preview
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

Show the repository name and navigation back to the repository list above a
two-pane view. Show the skill count once, in the left-pane heading above search.
Do not display a snapshot hash, scan/rescan button,
or a replacement rescan menu action. Scanning remains available through the
homepage scan dialog, including repeated submissions of an existing repository.

| Left pane: skills | Right pane: selected `SKILL.md` |
| --- | --- |
| Skill name and a description preview of up to two lines. | Document path and commit-pinned link to the file on GitHub, without a visible hash. |
| Skills sorted by name, then path. | Rendered Markdown by default, with a **Source** toggle. |
| A visible selection state. | Loading, content, or a retrieval error with **Retry**. |

Initially show **Select a skill to view its SKILL.md** in the right pane. Select
skills by `(repository_url, skill_path)`, never by name. Identical definitions
copied into different directories and same-name skills remain separate entries.

Each skill card places the skill-name link, its [star toggle](#stars), and the
**Similar skills** action in its heading row. A connected-nodes icon accompanies the similarity text; do not
rely on an icon or colour alone to explain the action. The description follows
below. Its subdued **Show more** / **Show less** control has a chevron and remains
next to the description, separate from similarity navigation.

Descriptions in homepage, repository, and similarity skill lists start collapsed.
Show **Show more** only when a description exceeds two lines at the current pane
width; expanding reveals its full text and offers
**Show less**. Each description expands independently without selecting a skill,
changing the URL, or fetching a document. These controls support keyboard use
and remain available after filtering, inline repository expansion, or scan
refreshes. Do not display paths beneath skills in the list; the selected document
still displays its path in the right pane.

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

### Similar skills

Each catalog skill card has a **Similar skills** link, available without loading its
document. It opens a dedicated two-pane workspace with the starting skill's
name, repository, and path above the results. A **Back** link returns to the page
that opened the search, including the homepage, repository selection, or previous
similarity search. Links carry that page's URL in `return_to`, preserving its filter
and selection. Only local homepage, repository, similarity, and topic/capability
Explore and legacy group URLs are accepted;
a direct link without valid return context falls back to the starting skill's
repository selection. Candidate selection, reload, and automatic refresh retain
this destination, so Back leaves the workspace rather than stepping through its
candidate selections. Preserve the catalog query in `q` as return-navigation
context; it never filters similarity candidates. Omit descriptions from this header.
Result cards reuse the same skill entry component as homepage and repository
lists, including two-line descriptions, independent **Show more** / **Show less**
controls, selection styling, and **Similar skills** links. A result's **Similar skills**
link starts a new search from that skill while preserving `q` and setting the
current similarity page as its return destination. Fetched SKILL.md
documents retain their complete Preview/Source content.

The left pane lists up to ten ranked groups. Each shared skill card adds its
repository name and a compact similarity indicator below its actions. Paths
appear in the selected document and expanded grouped locations. Shared-term
lists are not displayed. Each bar spans 0–100% and fills in proportion to the
rounded score. Use a slim rounded track with a subtle gradient fill; display
**Similarity** and a right-aligned percentage above it, without repeated endpoint
labels. Use red for 0–39%, amber for 40–69%, and green for 70–100%, based on the
same rounded value displayed above the bar. Numeric text stays on the card
background, readable independently of the fill; colour is supplementary.
Expose an accessible named meter with minimum 0, maximum 100, and the current
percentage. Keep colour selection in Web presentation, not the ranking service.

Matching metadata groups have an expandable **Same metadata · N locations**
control; each location is selectable. The right pane reuses the document viewer.
Selecting a result never changes the starting skill. Search all scanned
repositories; there are no **Refresh results**, **Other repositories only**, or
**Apply filter** controls. Scoring, cutoffs, grouping, and limitations belong to
[Similar skills](similar-skills.md).

Show **No similar skills found** when no candidates reach the cutoff, separately
from missing-source and catalog errors.
Escape names and paths. Keep source identity and selected result identity in
the URL. Browser reload and Back restore state using the current
catalog, including changes from CLI scans. Expand a group containing the restored
selection. Stack panes on narrow screens and preserve keyboard selection, focus
visibility, loading, retry, and Preview/Source behavior.

Any successful Web scan automatically refreshes a similarity workspace because
its candidates may span repositories. A stale or removed candidate also refreshes
results before loading again; clear selection if it is no longer among returned
locations. A missing source reports an explicit error. A failed automatic refresh
shows its error above the existing workspace; navigation and browser reload remain
available. Late workspace or document responses cannot replace a newer selection.
Documents still use the displayed candidate's stored commit and existing
authentication.

### Stars

The shared skill card used by homepage expansions, the repository view, and
similarity results has a star toggle, as does the open document's header. It is
a button labelled **Star *skill name*** with `aria-pressed` reflecting the
identity's [local star](stars.md); a filled star marks starred skills. Each card
and header stars its own identity, including a similarity group's representative.
Toggling sends the requested state, not a flip, so repeating a request is
idempotent. Every visible toggle for the same identity updates together. A
toggle never selects a skill, changes the URL, retrieves a document, contacts
GitHub, or starts a scan. A failed request leaves the toggle unchanged and shows
the error above the workspace; a removed identity reports **Skill not found in
the catalog**.

The homepage and repository view have a **Starred only** checkbox next to the
search field. Store it as `starred=1` in the page URL alongside `q`, using the
same replacement history updates, so refresh and back/forward restore it.
Selection, repository, and back links carry it; similarity links do not, because
starred-only never filters similarity candidates. It restricts the
[shared filter scope](filter.md#shared-matching-rules) before the query applies.
An active starred-only filter keeps the search controls open at narrow widths.

While starred-only is active, the homepage behaves like a filtered view: it shows
only repositories with starred matches, reveals them automatically, and shows
**N matching starred skills across M repositories** and **1 of 24 skills** per
repository. The repository view uses its filtered count and hidden-selection
notice. Empty states read **No starred skills.**, or **No starred skills match
“…”.** with a query, and offer **Show all skills** to clear starred-only and,
with a query, **Clear filter**. An empty starred view is not an empty catalog
and does not open the scan dialog. Changing a star while starred-only is active
refreshes the list; if the changed card disappears, focus moves to the checkbox.

### Empty results

After a successful zero-skill scan, show the repository name and **No skills
found** in the scan outcome/detail view. Clear any previous skill selection and
document. The repository disappears from the catalog-derived repository list.

A detail URL with no current skill rows shows **No skills found** with
navigation back to the homepage; it has no scan button. It cannot distinguish a
repository that has never been scanned from a previous zero-skill result. After the process restarts, there is no record of
that earlier successful scan or its commit.

### Scan feedback

The browser submits a scan and receives a job identifier promptly. Show queued,
running, succeeded, or failed status while the user can continue browsing.
Status is sufficient; precise progress percentages are outside this version.

After success, refresh the repository list and the selected repository's skills
from the catalog. If the selected path still exists, reload its document using
the newly stored commit. Otherwise clear the selection. Display the resulting
skill count, including zero.

An organization scan is one job. While it runs, its status shows **Listing
repositories…** until the listing returns, then **Scanning 3 of 12
repositories**, counting repositories with a final outcome against eligible
repositories. It succeeds when every repository succeeded or was empty, showing
the repository and skill totals, such as **12 repositories scanned · 34 skills
found**. Otherwise it fails with the shared explanation, such as **1 repository
failed.**, and lists each failed repository with its reason. Listing and
credential failures fail the job without a list. The organization notice has no
**View results** link. Because each repository is committed independently, a
completed organization job refreshes the repository list, and an open workspace
for one of its repositories, whether it succeeded or failed. **Retry scan**
resubmits the organization URL.

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
Keep the previous successful results visible during a scan of an existing
repository. Their document links stay pinned to the stored commit until the new
scan succeeds; commit hashes are not displayed as interface metadata.

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

The request includes the commit recorded in the selected skill's metadata.
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
filtering, the starred-only state, expansions, and independent list response
handling in `web/static/filters.js`, and star toggle requests in
`web/static/stars.js`. Star routes adapt `application/stars.py`. Dialog focus,
URL scope hints, and submission lifecycle live in `web/static/scan.js`. Package
the required templates and static assets so the installed command works outside
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
normalized repository or organization URL. An organization and one of its
repositories are separate jobs. Keep at most 16 queued jobs and retain the most recent 64 completed jobs;
reject new work clearly if the queue is full. These limits and job IDs
are process-local and are not catalog data.

Each job owns a fresh scanner context through the existing composition root.
An organization job runs on the same background worker and uses the shared
[organization scan service](../architecture.md#following-an-organization-scan),
including its bounded worker pool; later jobs wait behind it in the queue.
Reuse the scanner's default-branch resolution, readers, fallback rules, parser,
atomic replacement, timeouts, and resource cleanup. Catch operational failures
at the job boundary and keep the server and worker available for later jobs.

Closing the browser does not cancel a submitted scan. Graceful shutdown stops
accepting jobs, discards queued jobs, and lets the active scan unwind and clean
up its HTTP/Git resources. An active organization scan is cancelled through its
job's own cancellation signal: it starts no more repositories and stops
in-progress requests and Git processes; repositories that finished stay
committed. A failed job never affects later jobs. No jobs resume after a process restart. A missing
job ID produces **Scan status is no longer available; refresh the catalog**.
After an unexpected stop, a scan may already have committed its results; the
catalog is the source of truth, not the lost in-memory job status.

## HTTP contract

The following routes define the interface. The `q` filter and `starred=1` are
optional on all catalog routes; on similarity routes `q` is return-navigation
context only.
Repository arguments use canonical GitHub URLs; skill paths use exact stored
paths. Encode all query parameters rather than interpolating unescaped values
into URLs.

| Method and route | Behavior |
| --- | --- |
| `GET /?q=...` | Repository page, optional skill filter, and scan dialog. |
| `GET /repository?repository_url=...&skill_path=...&q=...` | Repository detail; skill selection is optional. |
| `GET /fragments/repositories?q=...` | Catalog-derived repository list with matching skills when filtering. |
| `GET /fragments/repository?repository_url=...&skill_path=...&q=...` | Refresh the two-pane workspace; skill selection is optional. |
| `GET /fragments/repository-skills?repository_url=...&q=...` | Inline skill metadata for an expanded homepage repository. |
| `GET /fragments/skills?repository_url=...&skill_path=...&q=...` | Filtered repository skill list and counts without replacing the document. |
| `GET /similar?repository_url=...&skill_path=...` | Similarity workspace; optional `selected_repository`, `selected_path`, and return-context `q` and `return_to`. |
| `GET /fragments/similar?repository_url=...&skill_path=...` | Refresh similarity workspace with the same optional parameters. |
| `GET /fragments/document?repository_url=...&skill_path=...&commit_sha=...` | Document fragment containing escaped source and safe rendered content. |
| `POST /scans` | Validate form-encoded `repository_url` as a repository or organization URL; return `202` with scan activity fragments and a job status URL in `Location`. |
| `POST /stars` | Validate form-encoded `repository_url`, exact `skill_path`, and requested `starred` (`1` or `0`); return `200` with the updated star toggle fragment. |
| `GET /scans/{job_id}` | Job status fragment with identity, state, and outcome or error. |

Return escaped HTML errors with a stable `data-error-code` and user-facing
message. Invalid input uses `400`; missing catalog entries (including star
requests, with `missing_skill`) and unknown job IDs use `404`; stale
document selections use `409`. Similarity searches use `404` with
`missing_similarity_source` for a removed starting skill; a missing or no-longer
ranked result selection is cleared in a successful workspace response. The retired
`other_repositories` parameter is ignored, like other unknown query parameters;
old links search all repositories. Distinguish upstream retrieval failures,
local storage failures, and a full scan queue without returning tokens, raw
subprocess output, or tracebacks. An accepted scan that later fails reports `failed` in
its job fragment rather than changing the original submission response.
Document retrieval failures use `502`, catalog failures use `500`, and queue
capacity or shutdown rejections use `503`. HTMX displays error fragments in
the relevant panel; stale selections refresh the workspace before loading again.

Bind only to loopback in this version. Validate allowed Host and Origin values
and protect scan and star submissions against cross-origin requests. Every
`POST`, including `POST /stars`, requires a matching Origin and the custom
`X-Atlas-Request: 1` header sent by the UI. Do not enable
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
   valid scan through the modal. Opening or closing it preserves list geometry,
   entered text, and keyboard focus; Tab stays inside, and Escape/Cancel/close
   return to the opener. Repository and organization URLs update the submit
   label and organization scope hint. Invalid input starts no job; submission
   and connection failures stay visible in the dialog and allow retry. Accepted
   scans close it and show queued/running progress. Empty-catalog refreshes and
   reloads do not automatically open it. These flows work at narrow widths.
2. Existing CLI-populated catalogs display repositories, counts, commits, and
   deterministically sorted skills without rescanning or changing the schema.
   Homepage, repository, and similarity skill descriptions use two-line previews
   with independent expand/collapse controls for overflow, including on narrow screens and after
   filtering, inline repository expansion, and scan refreshes. Paths
   appear in the selected document pane rather than beneath skill list entries.
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
   process restart follow the documented lifecycle. Organization submissions
   create one deduplicated job that reports listing and **Scanning N of M
   repositories** progress, then succeeds or fails with its failed repositories,
   refreshing the catalog in both cases. Successful notices expire
   after five seconds without hiding active scans. Failed notices remain until
   dismissed, and dismissed notices stay hidden across navigation and further
   submissions in the same tab.
8. Failed scans preserve previous catalog entries. Stale selections and late
   document responses cannot overwrite the currently selected document.
9. Unsafe Markdown, metadata, links, and cross-origin scan requests cannot
   execute content or expose credentials. No document content is persisted.
10. Homepage repository expansion loads only catalog metadata. Both filter scopes
    follow the [shared matching rules](filter.md#shared-matching-rules), covering
    the matching cases in the [filter acceptance criteria](filter.md#acceptance-and-verification)
    with consistent counts and ordering. Nonmatches and query failures have
    distinct, recoverable states.
11. Filtering preserves document content and source mode, even for a hidden
    selection. Queries and homepage expansions survive refresh and back/forward;
    clearing restores earlier expansions. Successful rescans reapply filters and
    late list/expansion responses cannot replace newer state. All controls work
    with keyboard navigation and narrow layouts without external requests.
12. The compact homepage opens the scan dialog through keyboard-accessible controls,
    offers it from an empty catalog, and keeps it stable during filtering/scans.
    Search is visible on desktop and expandable on mobile; active queries remain
    visible across navigation, refresh, and resizing. Repository counts update
    with results. The repository skill count appears once above search and updates
    with filtered results, including zero matches, clearing, and refresh.
    No repository scan/rescan controls or visible snapshot hashes
    remain; document links and fetches stay commit-pinned. Skill headings separate
    **Similar skills** from the description's **Show more** control.
    Keyboard navigation, narrow layouts, refresh/back navigation, loading
    states, and errors remain usable. The installed package serves its assets
    outside the checkout, and existing CLI behavior remains intact.
13. Similarity search follows the [ranking acceptance criteria](similar-skills.md#acceptance-and-verification),
    preserves its source while selecting matches, displays accessible percentage
    bars and grouped locations, reuses shared skill cards and description controls,
    omits shared-term lists and retired controls, and handles reload, Back, stale
    responses, keyboard selection, document errors, and narrow layouts.
    Back returns to the originating homepage, repository, or similarity page with
    its filter and selection, including after candidate selection and reload;
    similarity still searches all entries. Selections distinguish equal paths in
    different repositories.

14. Star toggles on shared cards and the document header are idempotent,
    update together, persist across restarts, and match CLI stars. **Starred
    only** filters the homepage and repository view, survives refresh and
    back/forward through `starred=1`, carries across catalog navigation, and has
    distinct empty states. Cross-origin star requests are rejected without
    writes, and starring never contacts GitHub or starts a scan.

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

The desktop visual pilot supplements these checks with four Playwright Test
scenarios: catalog filtering, description expansion and document preview/source,
scan progress with failure and retry, and graph exploration. Named checkpoints compare the browser
directly against reviewed screenshot baselines; recording mode produces videos
from those same scenarios. Mobile baselines and migration of the remaining
Python browser tests are outside the pilot. See the
[architecture](../architecture.md#development-and-delivery) for the fixture and
rendering environment, and [README](../../README.md#desktop-visual-tests) for
running, reviewing, and updating the screenshots.
