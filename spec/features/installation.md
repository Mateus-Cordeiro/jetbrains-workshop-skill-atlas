# Install and manage skills

Status: accepted and implemented. This feature owns project-scoped installation,
status, updates, removal, and project selection in the CLI and Web UI. The
[architecture](../architecture.md#project-installation-consistency) owns shared
identity, persistence, filesystem safety, and recovery contracts.

## Purpose and scope

Copy a catalogued skill and its supporting files into an explicitly selected
local project, initially for Codex and Claude Code. Installation never executes
instructions, scripts, dependency installers, checkout filters, or Git hooks.

Project locations were verified on 2026-10-01 against current official documentation:

| Agent | Project destination | Official reference |
| --- | --- | --- |
| Codex | `.agents/skills/<name>/` | [Codex skills](https://developers.openai.com/codex/skills/) |
| Claude Code | `.claude/skills/<name>/` | [Claude Code skills](https://code.claude.com/docs/en/skills) |

The filesystem adapter supports macOS and Linux. Other platforms fail before
writing project files because descriptor-relative, no-follow operations are
required for the current safety contract. This does not change existing catalog
or scan platform support.

## CLI

```sh
skill-atlas install REPOSITORY_URL EXACT_SKILL_PATH --agent codex [--project PATH] [--name NAME]
skill-atlas installed [--project PATH] [--json]
skill-atlas status [--project PATH] [--json]
skill-atlas update REPOSITORY_URL EXACT_SKILL_PATH --agent codex [--project PATH]
skill-atlas uninstall REPOSITORY_URL EXACT_SKILL_PATH --agent codex [--project PATH]
```

`--agent` is required for mutations and accepts `codex` or `claude`. `status` is
an alias for `installed`. Resolve an explicit `--project` to an existing directory;
otherwise use the current Git worktree's root. Outside Git, require the explicit
path. Git root discovery ignores inherited Git repository overrides and does not
execute hooks. Never create a project directory implicitly.

Select a source by canonical repository URL and exact repository-relative
`SKILL.md` path, including root-level `SKILL.md`. Use the catalog's recorded
commit; update selects the latest successfully scanned commit, without scanning,
resolving a branch, or substituting upstream HEAD. An unavailable commit fails.

The default folder name is the scanned skill name. `--name` explicitly chooses
another name for a new installation; accept 1–64 ASCII letters, digits, hyphens,
or underscores, beginning with a letter or digit. Invalid names fail with guidance.
An update retains the owned destination even if scanned metadata was renamed.
Two sources with the same name remain different identities and produce a collision
if their destinations overlap. Never adopt an existing directory or select by name.

An unchanged revision with an unchanged bundle is a successful no-op and needs
no credential lookup or download. Installing over a different revision asks the
user to use `update`. Local changes still block the no-op so it cannot hide drift.
Updating a source that is not installed fails. Uninstall requires an owned record.
There is no force-replace or force-remove option.

Listings show agent, absolute destination, source repository/path, recorded
commit, and one of **current**, **update available**, **source unavailable**, or
**modified**. Conflicts include exact project-relative paths for missing, edited,
added, symlinked, hardlinked, or executable-mode-changed files and extra directories.
Status and uninstall work offline, including after source removal from the catalog.
CLI success exits `0`; operational/validation failures exit `1` with a plain
stderr message; Typer usage failures exit `2`. JSON lists installation records,
conflicts, catalog commits, and status, without credentials or file bodies.

## Bundle retrieval

The bundle is the directory containing the selected `SKILL.md`. A root skill
includes all regular files in the repository root recursively. Preserve relative
paths, bytes (including binary content), and Git's executable bit. Do not rewrite
frontmatter or other content. Do not traverse symlinks or submodules or fetch
references mentioned in skill instructions. A root skill may include other nested
skills and unrelated regular repository files; disclose this in the preview.

Resolve the recorded commit to its tree using the existing authenticated GitHub
adapter. A complete recursive tree supplies blob IDs and modes. If truncated,
discard it and use the same temporary partial Git reader as scanning, fetching
the exact commit and verifying its tree. Only the selected bundle's blobs are
read. Existing private-repository credential precedence and error handling apply.

Validate all relative paths; reject absolute, traversal, backslash, control,
`.git`, and nonportable filenames, including trailing dots/spaces and Windows
reserved punctuation. Reject case/Unicode-normalization collisions and file/directory
collisions. Require a regular root `SKILL.md`. Limit a bundle to 10,000 files and
128 MiB of content. An unsupported bundle fails before destination publication.

## Web management

**Installations** is a catalog navigation item. A selected document also offers
**Install…**, carrying its exact source identity. The management page supports:

1. Register an existing absolute project path on the server's local computer.
   Registrations persist independently of the catalog. Registration alone does
   not install anything. No project is inferred from the server working directory.
2. Explicitly select a registered project, catalog source, agent, and optional
   folder name. The URL carries those selections; reload and Back restore them.
3. **Preview destination / refresh status** shows the exact absolute destination,
   scanned commit, bundle scope, and install/update actions. The backend checks
   both the displayed commit and destination again on submission.
4. List installed skills independently of catalog membership, review updates,
   and uninstall an unchanged installation. A stale uninstall form cannot remove
   an installation updated since the form was rendered.

Operations run in the server thread pool, outside the async event loop. The page
shows pending state, blocks duplicate form submission, then refreshes after
success. Errors stay visible with focus and preserve the selection. Network failure
explains that an operation may have completed and recommends refreshing status.
No credentials or repository bodies enter browser storage. Cross-origin protection
and safe escaping remain those of the [Web UI](web-ui.md#http-contract).

| Method and route | Contract |
| --- | --- |
| `GET /installations` | Management page; optional `project`, `source` (`repository URL` + `\|` + exact path), `agent`, and `name`. Reads local state and recovers interrupted project transactions; no remote requests. |
| `POST /installations/register` | Form-encoded absolute `project`; persist registration. |
| `POST /installations/install` and `/installations/update` | Registered `project`, `repository_url`, `skill_path`, `agent`, displayed `commit_sha`, exact absolute `destination`, optional `name`. |
| `POST /installations/uninstall` | Registered `project`, `repository_url`, `skill_path`, `agent`, installed `commit_sha`. No catalog lookup or network required. |

Mutation responses are JSON with `message` and, on failure, `code`. Success is
`200`; malformed requests are `400`; missing catalog selections are `404`;
stale selections, ownership conflicts, and local installation failures are `409`;
upstream repository failures are `502`. Every POST requires a matching Origin and
`X-Atlas-Request: 1`. UI messages use text content, never HTML interpretation.

## Outside this version

User/global installations, other agents, Windows filesystem installation,
automatic updates or rescans, skill execution, dependency installation, symlink
installation, remote project management, adopting existing directories, and forced
destruction of local modifications. Existing installations are not automatically
imported from agent directories or removed when a catalog source disappears.

## Acceptance and verification

Use [AGENTS.md](../../AGENTS.md) for required checks and delivery. Verify:

- Root/nested bundles, supporting files, binary bytes, executable bits, paths with
  spaces, exclusions, private credentials, fixed commits and truncated Git fallback.
- Exact identities, both agents, separate project targets, same-name collisions,
  existing unowned paths, unsafe paths, symlink escapes, malformed manifests,
  unchanged no-ops and explicit updates with added/removed files.
- Offline listing/removal after catalog deletion; changed/missing/extra files and
  executable modes preventing destructive actions with useful path reporting.
- Concurrent operations in threads and processes, download/write failures,
  interrupted publication, recovery on reopening, and edits after interruption.
- CLI explicit paths and Git-root defaults; Web registration, destination preview,
  stale selections, CLI/Web parity, request protection, keyboard/mobile use,
  refresh/Back, and visible errors. Tests use temporary projects and mock remote
  boundaries. Installed-wheel smoke tests cover packaged management routes/assets.
