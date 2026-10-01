# Python test suite

Last verified: 2026-10-01.

## Unique test module names

`tests/unit/` and `tests/integration/` subdirectories have no `__init__.py`, so
pytest imports test modules by basename. Two files with the same name, such as
`test_organization_scan.py` in both trees, pass when run separately but fail
collection with an "import file mismatch" when run together. Give integration
modules a distinct suffix, as in
[test_scan_catalog.py](../tests/integration/test_scan_catalog.py) and
[test_organization_scan_catalog.py](../tests/integration/test_organization_scan_catalog.py).

## Parametrized inputs and fixture dependencies

A parametrized argument replaces a fixture with the same name throughout that
test's dependency graph. In the
[repository-removal tests](../tests/integration/test_repository_controls.py),
calling an invalid URL parameter `repository` replaced the shared `Repository`
fixture used by `scan_result` and `web_environment`. Catalog seeding then failed
with `AttributeError` before the request under test. Use `repository_url` for
the string input, preserving the domain fixture from
[the shared conftest](../tests/conftest.py).

## Deterministic organization scan tests

The `organization_harness` fixture in the
[integration conftest](../tests/integration/conftest.py) serves a GraphQL
listing of local fixture repositories. It records requests by kind for
request-count assertions, and the fixture server chooses page boundaries
(`page_size`) while the client still requests 100. Per-repository hooks
(`on_tree`, `on_fetch`, `failed_trees`, `truncated_repositories`) control
outcomes without timing assumptions:

- Which repositories are in progress when a rate limit arrives depends on
  thread timing. Hold tree requests at a `threading.Barrier(4)` before returning
  the limit; the outcome becomes deterministic and also proves four workers run
  in parallel.
- Simulate Ctrl+C with `_thread.interrupt_main()` from a worker hook, then wait
  on the scan's cancellation event (captured as `harness.cancellations`) before
  letting the worker continue. The interrupt only lands because the calling
  thread polls its result queue with a bounded timeout. Typer reports Ctrl+C
  with exit code 130, not 1.

The concurrency model these tests protect is described in
[the architecture](../spec/architecture.md#following-an-organization-scan).
