# Skill groups

Status: accepted and implemented. Explicitly organize catalog metadata by topic
or capability using a local Ollama model. The [architecture](../architecture.md)
owns persistence, identity, consistency, and component boundaries; the
[Web UI](web-ui.md) owns the existing document viewer.

## Grouping behavior

Two independent perspectives cover the whole saved catalog across repositories:
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

One request handles the complete catalog for the selected perspective. A
conservative UTF-8 byte budget includes instructions, metadata, schema, chat
headroom, and reserved output tokens. If it exceeds configured context, fail
before calling Ollama; never silently omit skills or split into unrelated
batches. Ollama receives explicit context/output limits and a bounded timeout.
Do not download models or start Ollama automatically. Report connection, missing
model, timeout, malformed output, and storage failures without raw upstream
responses or credentials.

## Saved results and explicit updates

Generation reads a consistent metadata snapshot and performs inference outside
any database transaction. Persist a complete validated result atomically for
that perspective; a failed generation leaves its previous result intact. The
other perspective and source skill rows are unaffected. Existing version-1
catalogs are readable without rescanning or migrating; the first explicit write
migrates transactionally. Browsing creates no database and performs no migration.

Persist only the latest generation for each perspective: model name, fingerprint,
group titles, and repository/path memberships. There is no generation history or
durable queue. Memberships preserve catalog identities, including same-name
skills and copies. No content deduplication is inferred.

Fingerprint repository/path identity, name, and description, sorted independently
of model output. Commit-only changes do not alter grouping inputs. A metadata
addition, change, or removal makes the saved generation stale. Read the saved
groups and current catalog in one transaction, resolve memberships to current
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

The homepage and grouping pages offer **Repositories**, **Capabilities**, and
**Topics** navigation. Group pages list titles followed directly by existing
skill cards; no group description, membership explanation, probability, or
uncertainty indicator is displayed. Cards retain skill descriptions, repository
labels, Similar skills navigation, and the shared document viewer. Overlapping
cards have unique description-control IDs and select the same catalog identity.

**Generate groups** / **Regenerate groups** starts a background job. Show queued,
running, succeeded, or failed state and retry on failure. Keep saved groups usable
while working and after failure. Disable generation while the selected perspective
is active or the catalog is empty. Requests for an already-active perspective
reuse its job. One worker handles up to two active jobs (one per perspective),
retaining only the most recent status for each. Returning to the page resumes
polling; closing a browser does not cancel work. Shutdown discards queued work
and waits for active inference to finish or time out. Jobs do not resume after
server restart; saved groups remain available.

| Method and route | Behavior |
| --- | --- |
| `GET /groups/{perspective}` | Full page; perspective is `topics` or `capabilities`. |
| `GET /fragments/groups/{perspective}` | Refresh the grouping workspace. |
| `POST /groups/{perspective}/generate` | Explicit generation; `202` status fragment and status URL in `Location`. |
| `GET /groups/{perspective}/status` | Latest process-local status fragment, or status-unavailable notice. |

Page/fragment routes accept `selected_repository` and `selected_path`, preserving
exact identity in selection links, refresh, and back navigation. A removed
selection clears; documents use the existing commit checks and late-response
protection. Successful Web scans refresh an open grouping workspace; reload
observes CLI changes. Similar skills can return to either grouping perspective.
Mobile layouts stack the list and viewer. Controls support native keyboard
navigation; statuses and errors are accessible.

Existing Host/Origin/custom-header protections apply to generation POSTs.
Perspective validation failures return `400`, catalog errors `500`, and shutdown
submission rejection `503`. Job failures are reported in their status fragment,
not as a changed response code on the original accepted submission. Browser input
cannot specify an upstream endpoint, model, credential, or arbitrary skill body.

## Acceptance and verification

- Unit tests cover complete coverage, overlap, singleton/duplicate identities,
  invalid output, topic/capability prompts, context limits, structured requests,
  sanitized provider failures, deduplicated jobs, retries, and shutdown.
- Integration tests use real SQLite, the real Web composition, and mocked Ollama
  and GitHub transports. Cover version-1 reads/migration, independent perspectives,
  rollback, corruption, persistence across service instances, same-name/path
  identities, escaped output, explicit generation only, no credential forwarding,
  stale generation during concurrent scans, removals, and commit-only changes.
- Browser tests cover both perspectives, generation/retry/navigation during work,
  overlapping cards, source/preview, refresh/back, Similar skills return context,
  stale selections, late document responses, keyboard use, and narrow layouts.
- Installed-wheel checks cover grouping pages, generation, persisted results,
  and bundled assets. Existing desktop visual baselines cover homepage navigation.
- Evaluate a synthetic catalog against local Qwen separately from CI. All automated
  tests mock model responses; CI requires no running Ollama, model, or credentials.

See [AGENTS.md](../../AGENTS.md) for required checks and delivery. Hosted providers,
embeddings, batch reconciliation, automatic regeneration, stable taxonomies,
manual group editing, and group-specific search are outside this version.
