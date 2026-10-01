import json
from dataclasses import replace

import pytest

from skill_atlas.adapters.installation.records import decode, encode
from skill_atlas.installation import (
    BundleFile,
    FileHash,
    Installation,
    InstallationError,
    checked_commit,
    hashes,
    relative_path,
    source_path,
    target_directory,
)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/absolute",
        "../escape",
        "a/../../x",
        "a//b",
        "a/./b",
        "a\\b",
        "C:drive",
        "a\x00b",
        ".git/config",
        "a/space ",
        "a/dot.",
    ],
)
def test_unsafe_paths_are_rejected(path):
    with pytest.raises(InstallationError):
        relative_path(path)


@pytest.mark.parametrize(
    "bundle",
    [
        (BundleFile("missing", b"x"),),
        (BundleFile("SKILL.md", b"x"), BundleFile("skill.MD", b"x")),
        (BundleFile("SKILL.md", b"x"), BundleFile("a/b", b"x"), BundleFile("a", b"x")),
        (BundleFile("SKILL.md", b"x"), BundleFile("a", b"x"), BundleFile("a/b", b"x")),
        (BundleFile("SKILL.md", b"x"), BundleFile("../escape", b"x")),
    ],
)
def test_invalid_bundles_fail_before_filesystem_changes(bundle):
    with pytest.raises(InstallationError):
        hashes(bundle)


def test_limits_and_agent_name_commit_validation():
    with pytest.raises(InstallationError, match="10,000"):
        hashes(
            (BundleFile("SKILL.md", b"x"),) + tuple(BundleFile(str(i), b"") for i in range(10000))
        )
    for agent, name in [("unknown", "review"), ("codex", "../escape"), ("claude", "bad name")]:
        with pytest.raises(InstallationError):
            target_directory(agent, name)
    with pytest.raises(InstallationError):
        source_path("readme.md")
    with pytest.raises(InstallationError):
        checked_commit("HEAD")


def record():
    return Installation(
        "https://github.com/acme/skills",
        "review/SKILL.md",
        "a" * 40,
        "codex",
        ".agents/skills/review",
        (FileHash("SKILL.md", "b" * 64, False),),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"repository_url": "https://github.com/ACME/skills"},
        {"commit_sha": "HEAD"},
        {"destination": ".agents/skills/../outside"},
        {"files": ()},
        {"files": (FileHash("SKILL.md", "not-a-hash", False),)},
        {"files": (FileHash("SKILL.md", "b" * 64, False),) * 2},
    ],
)
def test_invalid_ownership_records_are_not_loaded(change):
    with pytest.raises(InstallationError, match="unsupported"):
        decode(encode((replace(record(), **change),)))


def test_manifest_roundtrip_and_rejects_duplicates_unknown_version_bad_modes():
    original = record()
    assert decode(encode((original,))) == (original,)
    with pytest.raises(InstallationError):
        decode(encode((original, original)))
    data = json.loads(encode((original,)))
    data["installations"][0]["files"][0]["executable"] = "false"
    with pytest.raises(InstallationError):
        decode(json.dumps(data).encode())
    for raw in (b"[]", b"null", b"{", b'{"version":2,"installations":[]}'):
        with pytest.raises(InstallationError):
            decode(raw)
