# skill-atlas specifications

Start here before changing application behavior or component boundaries. Read
the shared architecture, then the feature specifications affected by the change.

| Specification | Scope | Status |
| --- | --- | --- |
| [Architecture](architecture.md) | Adopted stack, component boundaries, shared domain and catalog contracts, CLI results presentation, configuration, credentials, and extension patterns. | Accepted and implemented |
| [Scan](features/scan.md) | `scan` command, repository and organization scans, discovery and extraction rules, repository access strategy, terminal output, and acceptance criteria. | Accepted and implemented |
| [Filter](features/filter.md) | Shared skill matching rules, `filter` command and its starred-only scope, output formats, and CLI/Web consistency criteria. | Accepted and implemented |
| [Stars](features/stars.md) | Local stars on catalog identities, `star` and `unstar` commands, terminal markers, JSON fields, and CLI/Web acceptance criteria. | Accepted and implemented |
| [Similar skills](features/similar-skills.md) | `similar` command, shared catalog-based similarity ranking, scores, grouping, and relevance criteria. | Accepted and implemented |
| [Skill groups](features/skill-groups.md) | Paired AI topic/capability generation, atomic saved memberships, and interactive G6 graph exploration. | Accepted and implemented |
| [Web UI](features/web-ui.md) | `serve` command, catalog browsing and filter interactions, star toggles and the starred-only view, expandable repositories, document viewing, background jobs, HTTP contracts, and acceptance criteria. | Accepted and implemented |

## Organization and ownership

- Keep cross-feature contracts and adopted technology choices in
  [architecture.md](architecture.md). Feature specs link to those contracts
  instead of independently redefining them.
- Keep command- or feature-specific behavior in `features/<feature>.md`. A
  feature can span commands or interfaces; a new command does not automatically
  need its own document. Split a spec when it has a distinct responsibility,
  not merely because it grows.
- Each feature spec states its status, purpose, behavior, relevant boundaries,
  scope exclusions, and acceptance criteria. Distinguish proposals from
  implemented behavior. Add or update its entry here when creating, moving,
  retiring, or changing the status of a spec.
- Proposed libraries stay in the relevant feature proposal until adopted.
  Architecture explains adopted choices; [pyproject.toml](../pyproject.toml)
  and [uv.lock](../uv.lock) remain authoritative for dependency constraints and
  resolved Python package versions.
- [AGENTS.md](../AGENTS.md) owns contribution, testing, and CI delivery rules.
  The project [README](../README.md) owns installation and usage guidance.
  Link to those rules rather than duplicating them in each feature spec.
- [Shared memory](../memory/index.md) holds verified working knowledge and
  practical lessons for agents. It links to these authoritative documents;
  it does not define architecture, feature contracts, or contribution rules.
