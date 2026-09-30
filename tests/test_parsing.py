import pytest

from skill_atlas.parsing import FrontmatterParser


def test_extracts_multiline_frontmatter_and_ignores_body():
    content = (
        b"\xef\xbb\xbf---\r\nname: ' review '\r\ndescription: |\r\n"
        b"  First line.\r\n  Second line.\r\nextra: ignored\r\n---\r\nIgnore this body."
    )
    parsed = FrontmatterParser().parse(content)
    assert parsed.name == "review"
    assert parsed.description == "First line.\nSecond line."


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"No frontmatter",
        b"\n---\nname: review\ndescription: test\n---",
        b"---\nname: missing-terminator",
        b"---\n[bad: yaml\n---",
        b"---\n- list\n---",
        b"---\nname: yes\ndescription: test\n---",
        b"---\nname: review\ndescription: 42\n---",
        b"---\nname: review\n---",
        b"---\nname: ' '\ndescription: test\n---",
        b"---\nname: review\ndescription: ' '\n---",
        b"---\nname: review\ndescription: \xff\n---",
        b"---\n!!python/object/apply:os.system ['exit 1']\n---",
    ],
)
def test_unusable_metadata_is_silently_skipped(content):
    assert FrontmatterParser().parse(content) is None
