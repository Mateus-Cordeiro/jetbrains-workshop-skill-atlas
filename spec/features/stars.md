# skill-atlas stars

Status: accepted and implemented in the CLI and Web UI.
This document owns local stars: the `star` and `unstar` commands, star
semantics, terminal markers, and acceptance criteria across interfaces. The
[filter specification](filter.md) owns the starred-only scope for `filter`, and
the [Web UI specification](web-ui.md#stars) owns the browser toggles, the
**Starred only** control, and the HTTP route. The
[shared architecture](../architecture.md#catalog-model-and-identity) owns star
storage, identity, rescan consistency, and migrations.

## Purpose and scope

Let users mark skills they use often so they can get back to them quickly from
the CLI and the Web UI. Stars are local to the user's catalog, including a
catalog selected with `SKILL_ATLAS_DB`. They are not GitHub stars: starring
makes no GitHub request, resolves no credentials, and never triggers a rescan.

Stars mark one [catalog identity](../architecture.md#catalog-model-and-identity),
`(repository_url, skill_path)`. Identical copies at different paths, including
copies under `.claude/skills/` and `.agents/skills/`, are starred independently.
A rescan keeps the star of a surviving identity, drops the star of a removed
identity, and leaves other repositories' stars unchanged. A moved path is a new
identity and starts unstarred.

Stars change neither the [filter matching rules](filter.md#shared-matching-rules)
nor [similarity ranking](similar-skills.md#ranking-and-score); they only
restrict a scope or mark results.

## Commands

```sh
skill-atlas star <github-repo-url> <skill-path>
skill-atlas unstar <github-repo-url> <skill-path>
```

Both positional arguments are required. Normalize the repository URL using the
[shared rules](../architecture.md#shared-domain-contracts). The path is the
exact, nonempty repository-relative catalog path to `SKILL.md`, as for
[`similar`](similar-skills.md#cli-command); do not trim it, resolve it as a
local file, or select by skill name. Quote paths containing spaces or shell
metacharacters.

Both commands are idempotent. Starring an already starred skill and unstarring a
skill without a star succeed. On success, print one line naming the result and
the identity, for example `Starred code-review · acme/skills · review/SKILL.md`,
with metadata rendered as terminal-safe text.

Exit `0` after a successful change or no-op; `1` when the identity is not in the
catalog or on a catalog failure; and `2` for invalid usage, including invalid
repository URLs and empty paths. An identity that is not in the catalog reports
**Skill not found in the catalog** on stderr, with guidance to check the exact
path or scan the repository first. A missing catalog has no skills to star and
is not created. Starring writes through the catalog's write path, so it migrates
an older supported catalog in place and rejects a newer one without changing it.

## Terminal and JSON output

Commands using the [shared CLI results presentation](../architecture.md#shared-cli-results-presentation)
mark a starred entry with ` ★` after its name, before a similarity percentage:
`1. code-review ★ · 100%`. In similarity groups with multiple locations, each
starred location line also ends with ` ★`, because locations are separate
identities and the representative's star applies only to itself. A starred
similarity source has the marker after its name in the summary line. Scan output
shows stars retained by the stored result of a rescan.

`filter` and `similar` JSON skill objects include a boolean `starred` field. It
is `false` for catalogs created before stars until a star is added.

## Application boundaries

`application/stars.py` owns the starring use case through the narrow
`StarWriter` port and reports unknown identities. The SQLite adapter sets the
identity's `starred` field in one transaction. `cli/commands/stars.py` adapts
arguments, exit codes, and output, using `runtime.create_stars()` without
credential or network setup. Web routes adapt the same service. Catalog reads
return each skill's `starred` state from the same read snapshot as its metadata.

## Outside this version

- Syncing with GitHub stars or sharing stars between machines.
- Notes, tags, ordering, or star counts on skills.
- Carrying a star to a moved path or to copies of the same definition.

## Acceptance and verification

1. Star and unstar are idempotent, persist across `serve` restarts, and are
   shared by the CLI and the Web UI without rescanning or GitHub requests.
2. Copies at different paths and same-name skills in other repositories are
   starred independently. Accepted URL forms resolve to the stored identity.
3. A rescan keeps stars on surviving skills and drops them on removed or moved
   paths in the same transaction, with both the GitHub API listing and the Git
   fallback. Other repositories' stars are unaffected. Failed scans and failed
   writes preserve existing stars.
4. Existing catalogs remain readable before migration and upgrade in place on
   the first write. A failed migration rolls back its schema change and version.
5. Unknown identities exit `1` with **Skill not found in the catalog**, invalid
   usage exits `2`, and catalog errors exit `1` without modifying the catalog.
   A missing catalog is not created.
6. Terminal output places the ★ marker after starred names and grouped starred
   locations, and `filter` and `similar` JSON include `starred`.
7. The installed wheel exposes both commands and the Web toggle outside the
   checkout.

Follow [AGENTS.md](../../AGENTS.md) for required checks and delivery.
