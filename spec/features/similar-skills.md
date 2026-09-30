# Similar skills

Status: accepted and implemented. This feature finds alternatives to a catalog
skill using its stored name and description. The [architecture](../architecture.md)
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

Display the score as a percentage in a colour-coded bar spanning 0–100%, rounded
to the nearest integer (halves up). The [Web UI](web-ui.md#similar-skills) owns
bar presentation, colour thresholds, and accessibility. Explain that it measures
names and descriptions, not probability, quality, or identical instructions. A rounded 100% does not establish identical metadata or
bodies. Scores may change as the catalog grows because IDF depends on the corpus.

The 80/20 weights and cutoff of 10 are initial defaults, covered by a small
relevance regression set. They are not calibrated probabilities. Lexical ranking
can miss synonyms and can match capabilities mentioned only to exclude them.
Embeddings and body-based ranking are outside this version; consider them only
after evaluation against the lexical baseline.

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
   score guidance, shared skill cards with expandable description previews, absence
   of shared-term lists and retired controls, keyboard/mobile behavior, refresh/back,
   stale/deleted selections, and late responses. Documents retain commit-pinned
   retrieval and safe rendering.
6. Installed-wheel checks exercise the new page and fragment. Benchmark a
   synthetic catalog of thousands of skills to check on-demand ranking latency;
   avoid timing assertions in CI. Follow [AGENTS.md](../../AGENTS.md) for delivery.
