"""Exercise the CLI, reader selection, parsing, persistence, and output together."""

import pytest

COPIES = (
    ".agents/skills/review/SKILL.md",
    ".claude/skills/review/SKILL.md",
    ".claude/skills/another-review/SKILL.md",
)


def skill(name="review", description="Review code changes."):
    return f"---\nname: {name}\ndescription: {description}\n---\n"


def assert_clean(harness):
    assert not list(harness.git_temporary.iterdir())
    assert bool(harness.git_fetches) == harness.truncated


def test_copies_across_agent_directories_remain_distinct_and_rescans_are_idempotent(scan_harness):
    harness = scan_harness
    source = harness.add_repository()
    for path in COPIES:
        source.write(path, skill())
    snapshot = source.commit()

    for _ in range(2):
        result = harness.scan(source)
        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[0] == "acme/skills — 3 skills"
        assert "1. review" in result.stdout and "3. review" in result.stdout
        rows = harness.rows()
        assert {row["skill_path"] for row in rows} == set(COPIES)
        assert len(rows) == 3
        assert {row["skill_name"] for row in rows} == {"review"}
        assert {row["commit_sha"] for row in rows} == {snapshot.commit_sha}
        for path in COPIES:
            assert f"{source.identity.url}/blob/{snapshot.commit_sha}/{path}" in result.stdout
        assert_clean(harness)


def test_same_names_with_different_content_and_repositories_do_not_overwrite_each_other(
    scan_harness,
):
    harness = scan_harness
    first = harness.add_repository()
    second = harness.add_repository("other/skills")
    first.write(COPIES[0], skill(description="Agent version."))
    first.write(COPIES[1], skill(description="Claude version."))
    second.write(COPIES[0], skill(description="Another repository."))
    first.commit()
    second.commit()

    for source in (first, second):
        result = harness.scan(source)
        assert result.exit_code == 0, result.output
    rows = harness.rows()
    assert len(rows) == 3
    assert {row["description"] for row in rows} == {
        "Agent version.",
        "Claude version.",
        "Another repository.",
    }
    assert {row["repository_url"] for row in rows} == {first.identity.url, second.identity.url}
    assert_clean(harness)


def test_rescan_updates_removes_and_adds_skills_without_changing_other_repositories(scan_harness):
    harness = scan_harness
    source = harness.add_repository()
    other = harness.add_repository("other/skills")
    for path in COPIES:
        source.write(path, skill())
    other.write("SKILL.md", skill(description="Preserved."))
    source.commit()
    other.commit()
    assert harness.scan(source).exit_code == harness.scan(other).exit_code == 0
    other_rows = [row for row in harness.rows() if row["repository_url"] == other.identity.url]

    (source.path / COPIES[0]).unlink()
    (source.path / COPIES[2]).unlink()
    source.write(COPIES[1], skill("updated", "Updated metadata."))
    source.write("nested/new/SKILL.md", skill("new", "New skill."))
    snapshot = source.commit()
    result = harness.scan(source)
    assert result.exit_code == 0, result.output
    rows = [row for row in harness.rows() if row["repository_url"] == source.identity.url]
    assert [(row["skill_name"], row["description"]) for row in rows] == [
        ("new", "New skill."),
        ("updated", "Updated metadata."),
    ]
    assert {row["commit_sha"] for row in rows} == {snapshot.commit_sha}
    assert [
        row for row in harness.rows() if row["repository_url"] == other.identity.url
    ] == other_rows
    assert_clean(harness)


def test_committed_repository_with_no_skills_clears_only_its_previous_entries(scan_harness):
    harness = scan_harness
    source = harness.add_repository()
    other = harness.add_repository("other/skills")
    for repo in (source, other):
        repo.write("SKILL.md", skill())
        repo.commit()
        assert harness.scan(repo).exit_code == 0
    other_rows = [row for row in harness.rows() if row["repository_url"] == other.identity.url]
    (source.path / "SKILL.md").unlink()
    source.write("README.md", "No skill definitions here.")
    source.commit()

    result = harness.scan(source)
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "acme/skills — 0 skills"
    assert harness.rows() == other_rows
    assert_clean(harness)


def test_malformed_definitions_are_skipped_while_root_and_nested_skills_are_stored(scan_harness):
    harness = scan_harness
    source = harness.add_repository()
    source.write("SKILL.md", skill("root"))
    source.write("nested space/skill/SKILL.md", skill("nested"))
    source.write(".claude/skills/invalid/SKILL.md", "---\nname: [wrong type]\n---")
    source.write(".agents/skills/invalid/SKILL.md", b"\xffinvalid UTF-8")
    source.write("lowercase/skill.md", skill("ignored"))
    snapshot = source.commit()

    result = harness.scan(source)
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "acme/skills — 2 skills"
    assert result.stderr == ""
    assert {row["skill_name"] for row in harness.rows()} == {"root", "nested"}
    assert f"/blob/{snapshot.commit_sha}/nested%20space/skill/SKILL.md" in result.stdout
    assert_clean(harness)


def test_branch_updates_during_scan_do_not_mix_commits(scan_harness):
    harness = scan_harness
    source = harness.add_repository()
    source.write(COPIES[0], skill(description="Original."))
    snapshot = source.commit()

    def advance_branch():
        source.write(COPIES[0], skill(description="New branch tip."))
        source.write(COPIES[1], skill())
        source.commit()

    harness.on_resolved = advance_branch
    result = harness.scan(source)
    assert result.exit_code == 0, result.output
    assert len(harness.rows()) == 1
    assert harness.rows()[0]["description"] == "Original."
    assert harness.rows()[0]["commit_sha"] == snapshot.commit_sha
    if harness.truncated:
        assert harness.git_fetches == [snapshot.commit_sha]
    assert_clean(harness)


def test_failed_rescan_preserves_catalog_and_cleans_up(scan_harness):
    harness = scan_harness
    source = harness.add_repository()
    source.write(COPIES[0], skill())
    source.commit()
    assert harness.scan(source).exit_code == 0
    previous_rows = harness.rows()
    source.write(COPIES[0], skill(description="Updated."))
    source.write(COPIES[1], skill(description="Failed download."))
    snapshot = source.commit()
    harness.failed_blob = next(
        entry["sha"] for entry in source.entries(snapshot.tree_sha) if entry["path"] == COPIES[1]
    )

    result = harness.scan(source)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr
    assert harness.rows() == previous_rows
    assert_clean(harness)


@pytest.mark.parametrize("directory", [".claude", ".agents"])
def test_multiple_skills_in_each_agent_directory_are_numbered_deterministically(
    scan_harness, directory
):
    harness = scan_harness
    source = harness.add_repository()
    source.write(f"{directory}/skills/z/SKILL.md", skill("zebra"))
    source.write(f"{directory}/skills/a/SKILL.md", skill("alpha"))
    source.commit()
    result = harness.scan(source)
    assert result.exit_code == 0, result.output
    assert result.stdout.index("1. alpha") < result.stdout.index("2. zebra")
    assert [row["skill_name"] for row in harness.rows()] == ["alpha", "zebra"]
    assert_clean(harness)
