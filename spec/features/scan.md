# skill-atlas scan

Status: accepted and implemented. This document owns scan discovery, extraction,
repository access, organization scans, and terminal behavior. The [shared architecture](../architecture.md)
owns the stack, component boundaries, credentials, snapshot and catalog contracts.
The [Web UI](web-ui.md) reuses this scan service for background jobs.

## Purpose and command

Discover AI skills in a GitHub repository and save their metadata to the local
catalog:

```sh
skill-atlas scan <github-repo-url> [--no-interactive]
skill-atlas scan <github-organization-url>
```

`scan` is a subcommand; `<github-repo-url>` is its required positional argument.
Scan the repository's default branch. A URL with only an owner names an
organization and scans its eligible repositories, as described in
[Organization scans](#organization-scans). Public and private repositories use the
shared [URL and snapshot rules](../architecture.md#shared-domain-contracts) and
[credentials](../architecture.md#configuration-and-authentication).

Store repository name, skill name, description, and commit SHA, along with the
repository URL and path required by [catalog identity](../architecture.md#catalog-model-and-identity).
The catalog contains the latest successful result for each repository and does
not update automatically.

## Scan flow

Implementation starts in `cli/commands/scan.py` and the shared
`application/scan.py` service. Reader selection is in
`application/reader_fallback.py`; GitHub, Git, frontmatter, and SQLite
implementations live in `adapters/`. Terminal output lives in `cli/output/`.
See the [architecture walkthrough](../architecture.md#following-a-scan) for
wiring and resource ownership.

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
Use the shared snapshot contract so a branch update cannot mix repository
versions during a scan.

Skill definitions are input data. Scanning does not execute repository code or
follow instructions contained in skill files.

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

Retrieval failures remain scan failures; they are not skipped as malformed
metadata. Under these rules, the stored entries and displayed count
include only successfully parsed skills.

## Rescans and consistency

Apply the shared [atomic replacement contract](../architecture.md#write-consistency)
only after complete discovery, retrieval, and parsing. A rescan updates the
repository's current skills, including additions and removals; zero valid skills
is a successful empty replacement. Retrieval failures remain operational errors,
not malformed metadata to skip. Never commit a truncated or otherwise incomplete
listing. Failed scans leave the previous catalog entries available.

## Command output

Use the [shared CLI results presentation](../architecture.md#shared-cli-results-presentation)
for interactive and printed output. The first line contains the repository name
and skill count. Preserve the shared skill order and present each catalog
identity separately, including identical metadata at different paths.

Example entry (URLs wrap to terminal width):

```text
acme/example — 1 skill

1. code-review
   Review code changes for correctness and maintainability.
   acme/example · .agents/skills/code-review/SKILL.md
   https://github.com/acme/example/blob/<commit>/.agents/skills/code-review/SKILL.md
```

Zero-skill scans show **No skills found in the repository** beneath the summary.
The interactive view adds the shared description toggle, scrolling, and keyboard
controls; `--no-interactive` prints the full results and exits.

Exit codes: `0` for a completed scan (including zero skills), `1` for a
scan or storage failure, and `2` for invalid command usage. Operational errors
go to standard error; noninteractive successful results go to standard output.

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

Use the shared [timeouts, credentials, and error policy](../architecture.md#configuration-and-authentication).
A repository with no commits cannot supply a snapshot and produces an
operational error; this differs from a committed repository containing zero
skills, which is a successful scan.

## Organization scans

`skill-atlas scan https://github.com/<org>` scans every eligible repository in
the organization in one run, following the shared
[organization URL rules](../architecture.md#shared-domain-contracts) and the
[organization scan walkthrough](../architecture.md#following-an-organization-scan)
for listing and concurrency. Single-repository scans are unchanged.

Organization scans require a GitHub credential, using the shared credential
precedence. Without one, the scan fails with a clear error before any request.
A user account, or an organization the credential cannot see, fails with a clear
error. Both, and any other listing failure, exit `1` and change nothing.

- Forks and archived repositories are excluded.
- Every other listed repository is eligible. Each goes through the extraction
  rules above, starting from the snapshot resolved during listing, and is saved
  with its own atomic catalog replacement as soon as it completes.
- A repository with zero valid skills is a success, as for a single scan.
- A repository with no commits is reported as **empty**. It is not scanned and is
  not a failure.
- A repository that fails is reported with its reason and preserves its previous
  entries. The other repositories continue.
- When GitHub rate-limits a repository, no new repositories are started.
  Repositories already in progress may finish. Repositories never started are
  reported as **not scanned**.
- Ctrl+C stops the scan. Repositories that finished stay committed; in-progress
  repositories stop their requests and Git processes and clean up their HTTP and
  Git resources before the command exits.

Nothing new is stored: no organization records, membership, or scan history. A
repository that has left the organization keeps its entries until it is
rescanned. Up to four repositories are scanned at a time.

### Organization output and exit codes

The command prints a summary instead of the skill list; `filter` and `serve`
browse the results. The first line contains the organization, its eligible
repository count, and the total stored skill count. One line per eligible
repository follows, in canonical URL order, with its skill count or outcome.
Each repository stays on one line, including in redirected output:

```text
acme — 5 repositories, 4 skills
acme/agents — 4 skills
acme/docs — no skills
acme/new-project — empty
acme/private — failed: GitHub's rate limit was reached. Retry later, or configure a GitHub credential.
acme/tools — not scanned
```

An organization with no eligible repositories prints **No repositories to scan in
the organization** after the summary line. On an interactive standard error, a
transient status shows **Listing repositories…**, then **Scanning N of M
repositories…**, where N counts repositories with a final outcome.

Exit codes: `0` when every repository succeeded or was empty; `1` when listing
failed, a credential was missing, any repository failed, or a rate limit stopped
the scan; and `2` for invalid usage. Unsuccessful outcomes print the summary to
standard output and a one-line explanation to standard error, such as
**GitHub's rate limit stopped the scan. 1 repository failed. 1 repository was
not scanned.** Ctrl+C uses the CLI's interrupt status.

## Outside this version

- A shared catalog or remote database.
- Scan history or version comparison.
- Malformed-skill reporting.
- Skill installation or execution.
- Other Git hosting providers.
- Branch or tag selection and automatic background updates. The local `serve`
  command is specified separately in [the Web UI specification](web-ui.md).
- Organization scans of user accounts, anonymous organization scans, options to
  include forks or archived repositories, pruning repositories that left the
  organization, and retrying after a rate limit.

## Acceptance and verification

The scan must satisfy these outcomes through both a complete API tree listing
and the temporary Git fallback:

1. Discover root and nested regular `SKILL.md` files, including paths with spaces;
   exclude symlinks and submodules. Store only metadata that meets the extraction
   rules, silently skipping malformed definitions alongside valid ones.
2. Keep identical copies under `.claude/skills/` and `.agents/skills/`, same-name
   skills at different paths, and skills from different repositories distinct
   according to catalog identity.
3. Repeated scans update, add, and remove entries without duplication. Zero-skill
   scans clear only the scanned repository; other repositories are unchanged.
4. A moving branch cannot mix snapshots. Catalog entries, retrieved contents,
   fallback fetches, and displayed links all use the single resolved commit.
5. Failed retrieval or writes preserve previous entries. Truncated API listings
   trigger the Git fallback; API errors do not. Git resources are cleaned after
   success, failure, timeout, and Ctrl+C, before the results view opens.
6. Terminal output has the required first line, deterministic numbering, encoded
   links, and descriptions. Interactive description toggling works; redirected
   and explicitly noninteractive output prints and exits with the documented
   status codes.
7. An organization scan produces the same catalog entries as scanning each
   eligible repository one by one. Request counts with mocked transports show one
   GraphQL request per 100 repositories, one tree request per repository, one blob
   request per `SKILL.md` on the API path, no per-repository metadata or commit
   requests, and no Git process unless a listing is truncated.
8. Paginated listings cover forks, archived, empty, zero-skill, failing, and
   rate-limited repositories, plus a repository that needs the Git fallback.
   No more than four workers run at once. A failed repository keeps its previous
   entries and does not affect the others. Git resources are cleaned up after
   Ctrl+C partway through an organization scan, while finished repositories stay
   committed. The summary, outcomes, and exit codes are deterministic.

Follow [AGENTS.md](../../AGENTS.md) for required checks and CI delivery. Parser,
identity, adapter, and scanner unit tests isolate policies and I/O boundaries.
Integration tests use mocked GitHub transports, real local Git fixtures,
temporary SQLite databases, CLI composition, and Textual's headless runner.
Keep migration, rollback, authentication, process cleanup, and narrow-layout
coverage without live GitHub or real credentials.
