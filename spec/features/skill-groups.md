# Skill groups

Status: accepted and implemented. Explicitly organize catalog metadata by topic
or capability using a local Ollama model. The [architecture](../architecture.md)
owns persistence, identity, consistency, and component boundaries; the
[Web UI](web-ui.md) owns the existing document viewer.

## Grouping behavior

Two perspectives generated together cover the whole saved catalog across repositories:
**Topics** describes subject areas; **Capabilities** describes what skills help
accomplish. The initial provider is Ollama with `qwen3.6:latest`, configurable via
[README settings](../../README.md#ai-topic-and-capability-groups). No embeddings,
vector database, full-document analysis, or external model SDK is involved.

Generation supplies each skill's exact name and description and a request-local
opaque identifier. Repository URLs, paths, credentials, and document bodies are
not sent to the model. Instructions treat metadata as untrusted classification
input, including descriptions that contain commands or attempts to override the
prompt. Generation never executes skills or retrieves documents.

Require structured JSON with only `groups`, each containing `title` and
`skill_ids`. Every input skill must occur at least once; overlapping membership
is allowed, repetition within a group is rejected. Titles must be nonempty,
unique ignoring case and collapsed whitespace, and at most 160 characters.
Distinct skills receive a specific singleton group when necessary. The model is
instructed not to create miscellaneous or uncertainty buckets; the generic titles
Other, Miscellaneous, Uncertain, and Uncategorized are rejected. Missing/unknown
IDs, empty groups, extra fields, malformed output, and unfinished/truncated
responses fail the entire generation. Structural validation does not certify
semantic quality. No automatic retries, fallback model, or partial publication.

One explicit action makes two sequential requests, one per perspective, using
the same complete catalog snapshot. Each request has a
conservative UTF-8 byte budget that includes instructions, metadata, schema, chat
headroom, and reserved output tokens. If it exceeds configured context, fail
before calling Ollama; never silently omit skills or split into unrelated
batches. Ollama receives explicit context/output limits and a bounded timeout.
Do not download models or start Ollama automatically. Report connection, missing
model, timeout, malformed output, and storage failures without raw upstream
responses or credentials.

## Saved results and explicit updates

Generation reads one consistent metadata snapshot and performs both inferences
outside any database transaction. Validate both results before atomically
replacing both saved perspectives in one write transaction. Failure in either
model call, either validation, or either write preserves both previous results.
Source skill rows are unaffected. Existing version-1
catalogs are readable without rescanning or migrating; the first explicit write
migrates transactionally. Browsing creates no database and performs no migration.

Persist only the latest generation for each perspective: model name, fingerprint,
group titles, and repository/path memberships. There is no generation history or
durable queue. Memberships preserve catalog identities, including same-name
skills and copies. No content deduplication is inferred.

Fingerprint repository/path identity, name, and description, sorted independently
of model output. Commit-only changes do not alter grouping inputs. A metadata
addition, change, or removal makes the saved generation stale. Read both saved
perspectives and the current catalog in one transaction, resolve memberships to current
skills and commit links, and hide removed entries and empty groups. Show a clear
regeneration notice for stale results; new skills appear after regeneration.
An in-flight scan may make a just-completed generation stale, including scans
from another process. Compare fingerprints on each browse; never label an old
snapshot current simply because its job just succeeded.

Explicit regeneration may completely rename or rearrange groups. Stability is
not promised across generations. Between generations the saved definitions
remain unchanged. Scanning, browsing, selection, and refresh never initiate AI
work. An empty catalog cannot be generated and does not call Ollama.

## Browser interaction and HTTP

The homepage and Explore page offer **Repositories** and **Explore** navigation.
`/explore` presents a G6 graph with a **Capabilities / Topics** toggle.
Keep the shared light catalog color scheme throughout navigation: page chrome,
controls, graph, directory, and tooltips use the same surfaces, text, and accent
colors as repository pages. Colored group outlines distinguish memberships.
Both perspectives are delivered in the initial page; toggling never calls Ollama
or fetches a new grouping. Initially show group nodes with titles and skill counts.
Clicking a group expands/collapses its skill nodes. An overlapping skill appears
once and connects to every expanded group containing it. Same-name skills retain
separate catalog identities. No inferred group-to-group edges or similarity scores
are shown. No group descriptions, membership explanations, or uncertainty labels.

Nodes are draggable; the canvas supports pan/zoom, fit, and reset layout. Newly
revealed nodes receive deterministic positions near their groups, avoiding visible
nodes where possible. Existing positions remain unchanged. G6 animates transitions
and then settles; reduced-motion preferences disable animations. Hover highlights
neighbors and displays an escaped title/count or skill/repository/description.
A parallel HTML directory provides keyboard-accessible group buttons and skill
links, including focus tooltips; on mobile it sits below the graph. If graph
rendering fails, the directory remains available. Canvas layers are excluded from
the tab order. The renderer uses a private container so HTMX never reapplies its
runtime inline styles; the existing content security policy stays unchanged.

Clicking a skill opens its existing repository/document page, with a **Back to
Explore** link. Encoded URLs preserve exact repository/path identity. Existing
commit-pinned document retrieval, Preview/Source, and stale/late response handling
remain authoritative. The perspective is in the URL; Back and reload restore it.
Per-perspective expanded group IDs and node positions survive navigation and
reload in tab-scoped session storage. Only opaque IDs and coordinates are saved,
never metadata or document bodies; storage failure leaves exploration usable.
Stale IDs are discarded against the current graph. Regeneration may rearrange or
rename groups; positions are not a promise of stable taxonomy.

**Generate groups** / **Regenerate groups** starts one background job for both
perspectives. Show queued/running/succeeded/failed state and Retry on failure.
Keep saved groups usable during work and after failure. Disable generation during
an active job or when the catalog is empty. Duplicate submissions reuse the active
job. A single worker retains the latest status; returning resumes polling. Closing
the browser does not cancel work. Shutdown stops submissions, discards unstarted
work and waits for active inference to finish or time out. Jobs do not resume after
server restart; saved groups remain available. Previously saved single-perspective
results remain readable; the next generation produces the pair without a new schema.

| Method and route | Behavior |
| --- | --- |
| `GET /explore?perspective=capabilities` | Full graph page with both views; perspective defaults to capabilities. |
| `GET /fragments/explore?perspective=...` | Refresh the graph workspace after generation or scan. |
| `POST /explore/generate` | Generate both perspectives; `202` status fragment and status URL in `Location`. |
| `GET /explore/status` | Latest process-local status fragment, or status-unavailable notice. |
| `GET /groups/{perspective}` and its former fragment route | Redirect old bookmarks to Explore; old selected-skill URLs redirect to the repository/document page. |

Successful Web scans refresh an open graph; reload observes CLI changes. Both
views compare their saved fingerprint with current metadata and show a regeneration
notice when stale. Removed skills and empty groups disappear; new skills appear
after explicit regeneration. The topic/capability switch has no effect on inference.

Existing Host/Origin/custom-header protections apply to generation POSTs.
Invalid perspectives return `400`, catalog errors `500`, and shutdown submission
rejection `503`. Job failures appear in their status fragment. Browser input cannot
specify an upstream endpoint, model, credential, or arbitrary skill body.

## Acceptance and verification

- Unit tests cover complete coverage, overlap, singleton/duplicate identities,
  invalid output, topic/capability prompts, context limits, structured requests,
  sanitized provider failures, deduplicated jobs, retries, and shutdown.
- Integration tests use real SQLite, the real Web composition, and mocked Ollama
  and GitHub transports. Cover version-1 reads/migration, paired perspectives and second-result failure,
  rollback, corruption, persistence across service instances, same-name/path
  identities, escaped output, explicit generation only, no credential forwarding,
  stale generation during concurrent scans, removals, and commit-only changes.
- Browser tests cover both perspectives, generation/retry/navigation during work,
  shared skill nodes, pointer drag/hover/expand, zoom controls, source/preview,
  refresh/back and restored positions, stale catalog data, keyboard use, reduced
  motion, renderer failure, safe metadata, narrow layouts, and consistent page
  colors across repository/Explore/document navigation. Existing viewer
  tests continue to cover late document responses and Similar skills.
- Installed-wheel checks cover grouping pages, generation, persisted results,
  and bundled assets. Desktop visual baselines cover homepage navigation and graph perspectives/overlap.
- Evaluate a synthetic catalog against local Qwen separately from CI. All automated
  tests mock model responses; CI requires no running Ollama, model, or credentials.

See [AGENTS.md](../../AGENTS.md) for required checks and delivery. Hosted providers,
embeddings, batch reconciliation, automatic regeneration, stable taxonomies,
manual group editing, and group-specific search are outside this version.
