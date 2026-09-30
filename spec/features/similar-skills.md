# Similar skills

Status: accepted and implemented. This feature finds alternatives to a catalog
skill using its stored name and description, through the CLI and Web UI.
The [architecture](../architecture.md)
owns catalog identity and read consistency; the [Web UI](web-ui.md) owns browser interaction
and HTTP contracts.

## Scope and behavior

Search all scanned repositories, including the starting repository. There is no
repository filter. Exclude the starting entry by its canonical repository URL
and exact path, never by name. A catalog text query carried in the URL is only
return-navigation context; it does not narrow the candidate set. Searching
performs no scans, document fetches, writes, migrations, or external model requests.

Read the starting skill and every candidate in one catalog snapshot. A missing
starting skill is an error, not an empty result. Each fresh search uses current
metadata, including changes made by CLI scans. No index or score is persisted.

Group entries with the same normalized name and description into one result,
labelled **Same metadata**, with expandable locations. Normalize grouping keys
with Unicode NFKC, case folding, and collapsed whitespace; preserve punctuation.
Do not claim matching document bodies. Grouping changes only presentation, never
catalog identity. A copy of the starting skill at another location remains a
candidate.

## Ranking and score

Use standard-library TF-IDF with separately normalized name and description
vectors. Compute corpus statistics over distinct metadata pairs, including the
starting skill, across the complete catalog. Copies must not change scores or
consume separate top-result slots.

- Normalize Unicode with NFKC, case-fold, and split hyphens/underscores. Preserve technical suffixes such as `C++` and `C#`.
- Extract Unicode word tokens and adjacent two-word phrases. Remove a fixed small
  list of common English function words and generic `skill`/`skills` tokens.
  Form phrases only from originally adjacent non-stopword tokens. No stemming,
  synonym dictionary, or language detection is applied.
- Use sublinear term frequency `1 + ln(count)` and smoothed inverse document
  frequency `1 + ln((N + 1) / (document_frequency + 1))`.
- Normalize each vector to unit length; an empty vector contributes zero.
- Score `100 × (0.8 × description cosine + 0.2 × name cosine)`, clamped to
  `[0, 100]`. Never normalize against the best result.
- Return at most ten groups with an unrounded score of at least 10. Sort by
  unrounded score descending, then representative name (case-folded), canonical
  repository URL, and exact path. Sort locations by that same identity order.

Display the score as a percentage rounded to the nearest integer (halves up).
The [Web UI](web-ui.md#similar-skills) owns bar presentation, colour thresholds,
and accessibility. Scores measure names and descriptions, not probability,
quality, or identical instructions. A rounded 100% does not establish identical
metadata or bodies. Scores may change as the catalog grows because IDF depends
on the corpus.

The 80/20 weights and cutoff of 10 are initial defaults, covered by a small
relevance regression set. They are not calibrated probabilities. Lexical ranking
can miss synonyms and can match capabilities mentioned only to exclude them.
Embeddings and body-based ranking are outside this version; consider them only
after evaluation against the lexical baseline.

## CLI command

```sh
skill-atlas similar <github-repo-url> <skill-path> [--no-interactive] [--json]
```

Both positional arguments are required. Normalize the repository URL using the
shared rules. The path is the exact, nonempty repository-relative catalog path
to `SKILL.md`, including case and whitespace; do not resolve it as a local file,
trim it, decode it as a URL, or select by skill name. Quote paths containing
spaces or shell metacharacters. The starting skill must already be scanned.
Read the catalog selected by the shared settings, including `SKILL_ATLAS_DB`.
This command performs no credential lookup and requires neither Git nor a
running Web server.

Use the [shared CLI results presentation](../architecture.md#shared-cli-results-presentation),
including automatic terminal detection, `--no-interactive`, description toggling,
scrolling, and keyboard controls. Show the starting skill and its repository/path
and commit-pinned URL, the number of result groups, and score guidance. Each
numbered match shows its representative name followed by the rounded percentage,
its description, and every grouped repository/path and commit-pinned URL.
Multiple locations are labelled **Same metadata · N locations**. Use the service's
group and location order. A successful empty search shows **No similar skills
found**. The results view performs no new searches or catalog reads.

`--json` always prints one JSON object followed by a newline and exits, even on
a terminal or alongside `--no-interactive`, without terminal formatting or
explanatory text. Preserve metadata exactly, escaping control characters as
JSON data. Its fields are:

- `source`: a skill object.
- `matches`: an ordered array of groups, empty when no candidates meet the cutoff.
  Each group has numeric `score` (unrounded, on the 0–100 scale), integer
  `display_score` (the shared rounded percentage), and `locations` (an ordered
  array of skill objects). The first location is the representative.
- Each skill object contains `repository_url` (canonical), `repository_name`,
  `skill_path`, `name`, `description`, `commit_sha`, and `url` (commit-pinned).

Exit `0` for a completed search, including no matches; `1` for a missing source
or catalog error; and `2` for invalid command usage. Successful output goes to
stdout; errors go only to stderr, also with `--json`. Missing sources explain
how to check the identity or scan the repository first. A missing catalog is an
empty catalog and therefore a missing-source error, without creating any files.

`cli/commands/similar.py` adapts arguments and errors and uses
`runtime.create_similarity()` to compose the existing service and catalog reader.
`cli/output/results.py` adapts the result for the shared terminal views, and
`cli/output/similarity.py` owns JSON serialization. Ranking, grouping, cutoffs,
and snapshot consistency remain shared with the Web UI.

## Acceptance and verification

1. Useful task matches rank above same-name/different-purpose candidates; an
   unrelated candidate is omitted. Same-description/disjoint-name scores 80,
   and same-name/disjoint-description scores 20 when vectors are nonempty.
2. Case, separators, phrases, repeated words, technical tokens, Unicode, and
   empty vocabularies have deterministic finite scores. Scores are not rescaled
   to make the highest result 100.
3. Source identity exclusion, same- and cross-repository results, matching metadata
   groups, stable ties, and top-ten limits are tested.
   Adding copies does not change existing scores.
4. Existing catalogs work without rescanning or schema changes. Missing,
   corrupt, unsupported, concurrently replaced, and zero-skill catalogs preserve
   the shared read and error contracts. Search does not persist data.
5. Browser tests cover entry from metadata even after document failure, result
   selection without losing the source, grouping, percentage bars and colour bands,
   shared skill cards with expandable description previews, absence
   of shared-term lists and retired controls, keyboard/mobile behavior, refresh/back,
   stale/deleted selections, and late responses. Documents retain commit-pinned
   retrieval and safe rendering.
6. Installed-wheel checks exercise the new page and fragment. Benchmark a
   synthetic catalog of thousands of skills to check on-demand ranking latency;
   avoid timing assertions in CI. Follow [AGENTS.md](../../AGENTS.md) for delivery.
7. CLI text and JSON results match the Web UI's scores, order, and grouped
   locations. Exact paths, same-name skills, URL normalization, and encoded
   commit links work with catalogs populated by both scan readers. Subsequent
   searches reflect updates, removals, and zero-skill scans.
8. CLI help, invalid usage, no matches, missing sources, and unreadable, corrupt,
   or unsupported catalogs have the documented output streams and exit codes.
   Searches do not resolve credentials, access GitHub, or change the catalog.
   Both terminal views include descriptions and all grouped locations at narrow
   widths. The interactive view supports the shared toggle and keyboard controls;
   `--no-interactive` and redirected streams print and exit. JSON bypasses the
   interactive view and preserves metadata and score precision without active
   control sequences. The installed wheel exercises
   command help and both output formats outside the checkout.
