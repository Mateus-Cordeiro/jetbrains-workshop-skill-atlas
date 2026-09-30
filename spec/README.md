# skill-atlas specifications

Start here before changing application behavior or component boundaries. Read
the shared architecture, then the feature specifications affected by the change.

| Specification | Scope | Status |
| --- | --- | --- |
| [Architecture](architecture.md) | Adopted stack, component boundaries, shared domain and catalog contracts, configuration, credentials, and extension patterns. | Accepted and implemented |
| [Scan](features/scan.md) | `scan` command, discovery and extraction rules, repository access strategy, terminal output, and acceptance criteria. | Accepted and implemented |
| [Web UI](features/web-ui.md) | `serve` command, catalog browsing and filtering, expandable repositories, document viewing, background jobs, HTTP contracts, and acceptance criteria. | Accepted and implemented |

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
