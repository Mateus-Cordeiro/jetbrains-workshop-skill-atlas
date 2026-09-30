# skill-atlas

Discover AI skills in GitHub repositories and save their metadata to a local
SQLite catalog. Requires Python 3.11 or later.

From the local checkout directory, install the CLI as a user-level tool:

```sh
uv tool install --editable .
```

Then run it from any directory:

```sh
skill-atlas scan https://github.com/owner/repository
```

The editable installation picks up Python source changes in this checkout.
If your shell cannot find the installed command, run `uv tool update-shell` and
restart the shell to add uv's executable directory to `PATH`.

The results view shows numbered skills with links to their scanned definitions.
Click **Hide descriptions**, or press **d**, to toggle descriptions. Press **q**
to exit. Links open in your default browser.

For ordinary terminal output, use:

```sh
skill-atlas scan https://github.com/owner/repository --no-interactive
```

Redirected output automatically uses plain text, including literal URLs.

## Installation

For an installation that does not follow source edits, use `uv tool install .`
or `pipx install .` from the checkout. You do not need to clone scanned
repositories yourself.

Install Git 2.31 or later to scan large repositories. When GitHub truncates a
file listing, skill-atlas automatically fetches a shallow partial Git snapshot
of the exact scanned commit. It lists paths locally and downloads only the
discovered skill files, with no working checkout or full history.

The temporary Git repository is removed after the scan, including on errors,
timeouts, and Ctrl+C, before the results view opens. No Git cache is retained.

## Authentication and storage

Private repositories are supported. Credentials are resolved in this order:
`GH_TOKEN`, `GITHUB_TOKEN`, then an existing `gh auth login` session for
`github.com`. The token must have read access to the repository's contents.
Without a credential, public repositories are scanned anonymously, subject to
GitHub's lower rate limits. The Git fallback uses the same credential through
process-local configuration; it never writes the token into the repository's
remote URL or Git configuration file.

The catalog lives in the operating system's user data directory:

- macOS: `~/Library/Application Support/skill-atlas/catalog.sqlite3`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/skill-atlas/catalog.sqlite3`
- Windows: `%LOCALAPPDATA%\skill-atlas\catalog.sqlite3`

Set `SKILL_ATLAS_DB` to override the database file location. Credentials are not
stored in the database. A completed scan replaces that repository's previous
entries, including removing entries for skills that disappeared. There is no
scan history. Malformed skill definitions are silently skipped.

## Development

Run these commands from the project checkout:

```sh
uv sync --locked
uv run skill-atlas scan https://github.com/owner/repository
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

`uv run` uses the current project's environment; it does not install the command
globally. From another directory, use the installed `skill-atlas` command above,
or specify the checkout with `uv run --project /path/to/checkout skill-atlas ...`.

See [the architecture specification](spec/cli.md) for component boundaries,
data semantics, and guidance for adding commands, parsing rules, and migrations.
