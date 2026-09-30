# skill-atlas filter

Status: accepted and implemented in the CLI and Web UI.
This document owns filter matching, command behavior, and acceptance criteria
across interfaces. The [Web UI specification](web-ui.md#skill-filtering-and-expandable-repositories)
owns browser interactions and HTTP presentation. The [shared architecture](../architecture.md)
owns catalog storage, identity, ordering, configuration, and read consistency.

## Purpose and scope

Find skills by their saved names and descriptions, across the local catalog or
within one repository. Expose the existing Web filter through a command that
prints results and exits, with structured output for scripts.

Use the existing [catalog configuration](../architecture.md#configuration-and-authentication),
including `SKILL_ATLAS_DB`. Results reflect the latest successful scans already
stored there. Filtering works offline without a running Web server, GitHub
credentials, Git, document retrieval, or a rescan. No database migration or new
dependency is needed.

## Shared matching rules

These rules preserve the existing homepage and repository filters:

- Split the query on whitespace and case-fold Unicode text in the query, skill
  name, and description.
- Require every term to occur as a literal substring in either the name or
  description. Different terms may match different fields; their order does
  not matter.
- Search only names and descriptions. Repository names, paths, and document
  bodies do not participate in matching.
- Empty or whitespace-only queries match all entries in the selected scope.
- Wildcards, regular expressions, and punctuation have no special meaning.
- Preserve the [catalog identity and ordering contracts](../architecture.md#catalog-model-and-identity).
  Same-name skills and copies at different paths remain separate results.
  Filtering does not rank or group entries by similarity.

For example, `CODE maintain` matches a skill named `code-review` whose
description contains `maintainability`. `STRASSE` matches `Straße` through
Unicode case folding. `%`, `_`, and `.*` match only those literal substrings.

## Command

```sh
skill-atlas filter [QUERY] [--repository GITHUB_REPO_URL] [--json]
```

`QUERY` is an optional positional argument, defaulting to an empty string. Quote
queries containing spaces so the shell passes them as one argument:

```sh
skill-atlas filter "code review"
skill-atlas filter "code review" --repository https://github.com/owner/repository
skill-atlas filter "code review" --json
skill-atlas filter
```

Search the whole catalog by default. `--repository` restricts the scope to one
repository and uses the existing [repository URL validation and normalization](../architecture.md#shared-domain-contracts).
A valid repository URL with no saved entries produces an empty result. Do not
infer whether it has never been scanned or was scanned successfully with zero
skills; the catalog does not record that distinction.

Omitting `QUERY`, passing `""`, or passing only whitespace lists all skills in
the selected scope. The command always prints and exits, including in an
interactive terminal. It does not open a TUI or browser.

### Human-readable output

Print a matching skill count, followed by numbered results in catalog order.
Include each skill's name, description, repository name, exact path, and
commit-pinned GitHub link so same-name entries can be distinguished. Number
results consecutively across repositories.

Adapt to terminal width and render metadata as literal text, escaping terminal
control sequences and avoiding Rich markup interpretation. Redirected output
contains literal URLs and no terminal styling or control sequences. Terminal
hyperlinks may be used where supported.

Distinguish an empty selected scope (**No saved skills in the selected scope**)
from a populated scope with no matches (**No skills match the query**). Both
are successful queries with zero matches. Catalog errors must not be presented
as empty results.

### JSON output

With `--json`, stdout contains one JSON object followed by a newline, without
headings, progress messages, terminal styling, or hyperlinks encoded as terminal
controls. The object contains:

- `matching_count`: the number of matching entries.
- `skills`: an array in the same order as human-readable output. Each entry
  contains `repository_url`, `repository_name`, `skill_path`, `skill_name`,
  `description`, `commit_sha`, and `url` (the commit-pinned GitHub link).

Use canonical repository URLs, exact stored paths, full commit SHAs, and the
shared [encoded link contract](../architecture.md#shared-domain-contracts).
Preserve metadata values with JSON escaping rather than terminal sanitization.
An empty result is `{"matching_count": 0, "skills": []}` for both empty scopes
and queries without matches.

### Errors and exit codes

Exit `0` after a successful query, including zero matches; `1` on an operational
catalog failure; and `2` for invalid command usage, including invalid repository
URLs. Operational errors go to stderr, with no partial results on stdout in
either output mode. Follow the shared [catalog read contract](../architecture.md#catalog-reads)
for missing, unreadable, corrupt, and unsupported databases.

## Application boundaries

Follow the existing [component map](../architecture.md#components-and-dependency-boundaries).
Keep matching and query coordination in `application/catalog.py`, reuse
`CatalogReader`, and wire the read-only service through `runtime.py`. The CLI
adapter in `cli/commands/filter.py` handles arguments, exit codes, and
output through `cli/output/filter.py`; it must not call Web routes or duplicate matching
in a command handler or SQL query.

The unfiltered homepage reads repository summaries and loads skills only on
expansion. `BrowseCatalog.filter()` returns a `FilteredSkills` value containing
actual matches and the total number of skills in scope, including for empty
queries. The CLI uses this operation independently of the homepage's unloaded
groups, preserving the Web optimization.
Use the existing [read snapshot contract](../architecture.md#catalog-reads) for
matches and any counts derived from them, including during concurrent scans.

This extends the existing catalog service without changing dependency direction;
see the [filter walkthrough](../architecture.md#following-a-catalog-filter).

## Outside this version

- Fuzzy, semantic, regular-expression, or document-body search.
- Similarity scores, relevance ranking, or metadata deduplication; see
  [Similar skills](similar-skills.md) for that separate feature.
- Automatic catalog refresh, remote search, or skill execution.
- Interactive filtering in the terminal, pagination, or a persistent search index.
- Changes to browser expansion, selection, history, or document behavior.

## Acceptance and verification

The CLI and Web filters must preserve these outcomes:

1. The same catalog, query, and repository scope produce the same ordered skill
   identities in CLI and Web results. Cover Unicode case folding, terms across
   fields, literal punctuation, repeated whitespace, duplicate names, copies at
   different paths, and exclusion of repository names, paths, and document bodies.
2. Omitted, empty, and whitespace-only queries return all skills in scope.
   Repository restrictions normalize accepted URL forms, exclude other
   repositories, and reject invalid URLs with exit `2`.
3. Missing catalogs, empty catalogs, unknown repositories, and populated scopes
   without matches exit `0`. Human-readable empty states remain distinct;
   JSON returns the documented empty object. Missing databases are not created.
4. Corrupt, unreadable, or unsupported catalogs exit `1`, report an error on
   stderr, leave stdout empty, and do not modify the catalog.
5. Results and counts remain consistent during atomic repository replacement.
   Filtering makes no network requests, resolves no credentials, starts no scan
   or server, and performs no catalog writes or migrations.
6. Text output distinguishes duplicate names by repository and path, preserves
   descriptions and deterministic numbering, and handles narrow terminals,
   redirected output, and untrusted metadata safely. Links use stored commits
   and correctly encode paths containing spaces or URL-significant characters.
7. JSON parses independently of terminal detection and round-trips metadata,
   identity, and full commits with correct counts and ordering. It contains no
   presentation text or raw terminal control sequences.
8. The installed wheel exposes `filter --help` and queries a temporary catalog
   outside the checkout. Existing `scan`, `serve`, and Web filters retain their
   behavior, including lazy loading on the unfiltered homepage.

Follow [AGENTS.md](../../AGENTS.md) for required checks and delivery. Reuse and
extend matching unit tests, add CLI integration tests with real temporary SQLite
catalogs, and verify CLI/Web parity against the same fixtures. Cover the new
command in the installed-wheel smoke test. Run the Web checks when shared
filtering changes affect the Web UI.
