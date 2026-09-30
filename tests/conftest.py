import pytest

from skill_atlas.models import Repository, ScanResult, Skill


@pytest.fixture(autouse=True)
def isolated_catalog_and_credentials(tmp_path, monkeypatch):
    """A test must never touch a developer's catalog or use their API tokens."""
    monkeypatch.setenv("SKILL_ATLAS_DB", str(tmp_path / "catalog.sqlite3"))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    for name in ("URL", "MODEL", "TIMEOUT", "CONTEXT", "OUTPUT_TOKENS"):
        monkeypatch.delenv(f"SKILL_ATLAS_OLLAMA_{name}", raising=False)


@pytest.fixture
def repository():
    return Repository("Acme", "skills")


@pytest.fixture
def scan_result(repository):
    return ScanResult(
        repository,
        "a" * 40,
        (
            Skill(
                repository,
                "review/SKILL.md",
                "code-review",
                "Review code changes for correctness and maintainability.",
                "a" * 40,
            ),
            Skill(
                repository,
                "release notes/SKILL.md",
                "release-notes",
                "Draft release notes from a set of changes.",
                "a" * 40,
            ),
        ),
    )


@pytest.fixture
def web_environment(tmp_path, scan_result):
    from tests.web_environment import create_web_environment

    with create_web_environment(tmp_path, scan_result) as state:
        yield state


@pytest.fixture
def similar_catalog(web_environment, scan_result):
    """Catalog entries with copies, cross-repository alternatives, and encoded paths."""
    from dataclasses import replace
    from types import SimpleNamespace

    source = scan_result.skills[0]
    local_copy = replace(source, path=".agents/skills/review/SKILL.md")
    remote = replace(
        source,
        repository=Repository("other", "skills"),
        path="review #?/SKILL.md",
        commit_sha="b" * 40,
    )
    remote_copy = replace(remote, path="nested/copy/SKILL.md")
    alternative = replace(
        remote,
        path="alternative/SKILL.md",
        name="patch-audit",
        description=source.description,
    )
    web_environment.catalog.replace_repository(
        replace(scan_result, skills=(*scan_result.skills, local_copy))
    )
    web_environment.catalog.replace_repository(
        ScanResult(remote.repository, remote.commit_sha, (remote, remote_copy, alternative))
    )
    return SimpleNamespace(source=source, remote=remote, alternative=alternative)
