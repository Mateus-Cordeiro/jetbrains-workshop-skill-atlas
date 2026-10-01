import pytest

from skill_atlas.models import Organization, Repository, scan_target


@pytest.mark.parametrize(
    "url",
    ["https://github.com/Acme/Skills", "https://github.com/Acme/Skills.git/"],
)
def test_repository_identity_is_normalized(url):
    repository = Repository.from_url(url)
    assert repository.url == "https://github.com/acme/skills"
    assert repository.full_name == "Acme/Skills"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/acme/skills",
        "http://github.com/acme/skills",
        "https://github.com/acme/skills/tree/main",
        "https://github.com/acme",
        "https://github.com/acme/skills?token=secret",
        "https://user:secret@github.com/acme/skills",
        "https://github.com:1234/acme/skills",
        "https://github.com:bad/acme/skills",
        "https://github.com/acme/..",
        "https://github.com/acme/skills#fragment",
        "https://[invalid/acme/skills",
    ],
)
def test_invalid_urls_are_rejected(url):
    with pytest.raises(ValueError):
        Repository.from_url(url)


def test_skill_link_is_commit_pinned_and_path_encoded(scan_result):
    assert scan_result.skills[1].url == (
        "https://github.com/acme/skills/blob/" + "a" * 40 + "/release%20notes/SKILL.md"
    )


@pytest.mark.parametrize("url", ["https://github.com/Acme", "https://github.com:443/Acme/"])
def test_owner_only_urls_name_an_organization(url):
    target = scan_target(url)
    assert target == Organization("Acme")
    assert target.url == "https://github.com/acme"
    assert target.full_name == "Acme"


def test_repository_urls_remain_repository_scan_targets():
    assert scan_target("https://github.com/acme/skills.git") == Repository("acme", "skills")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/",
        "https://github.com/acme.git",
        "https://github.com/acme?tab=repositories",
        "https://github.com/acme#people",
        "https://token@github.com/acme",
        "https://github.com/orgs/acme/repositories",
        "https://gitlab.com/acme",
    ],
)
def test_invalid_scan_targets_mention_both_url_forms(url):
    with pytest.raises(ValueError, match="organization URL"):
        scan_target(url)
