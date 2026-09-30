import pytest

from skill_atlas.models import Repository


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
