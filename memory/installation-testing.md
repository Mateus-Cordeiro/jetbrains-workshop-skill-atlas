# Installation testing

Last verified: 2026-10-01.

The [installation integration fixture](../tests/integration/test_installation_management.py)
uses real SQLite, project files, manifests, application services and interface
composition; only GitHub transport and credential lookup are replaced. Its two
revisions have binary/executable files and different added/removed paths. Use the
fixture's `seed` to change the catalog explicitly; retrieval asserts a full commit
rather than a branch. Do not substitute the installation service when testing
ownership or recovery.

For a normal write failure, inject at the filesystem adapter boundary and let
recovery run. For an abrupt exit at publication, prevent `ProjectTransaction.recover`
within that failure's test context, then remove that substitution before reopening
through the real service. Test both sides of manifest replacement and preserve
edits made before recovery. Cleanup interruption needs separate coverage: deleting
only some backup files must leave a journal that can resume cleanup. See the
[architecture](../spec/architecture.md#journal-and-recovery) for the contract.

The [Git integration tests](../tests/integration/test_git.py) retain the original
scan behavior when extending listing to supporting files: scanning filters to
SKILL.md before decoding unrelated paths. Build non-UTF-8 filename fixtures with
`git mktree`/`commit-tree`, not filesystem writes; APFS cannot create the same
non-UTF-8 paths that Git trees can represent. The parameterized unusual-filename
fixture also verifies that nested bundles ignore unsupported paths outside their
directory, while root bundles still reject them. Git must filter raw bytes before
decoding, and the bundle adapter must validate raw relative strings before
`PurePosixPath` could erase repeated separators or `.` segments. API regressions
verify that unsafe selected paths fail before their blobs are requested.

Temporary project paths must be canonical before constructing expected absolute
destinations. macOS `/tmp` and `/var` aliases differ from their resolved `/private`
paths; the Web destination check intentionally rejects a mismatch. The
[installed-wheel smoke](../tests/smoke_installed.py) resolves its temporary project
before previewing and submitting installation.
