from skill_atlas.application.documents import Document
from skill_atlas.web.rendering import render


def test_rendering_escapes_html_pins_links_and_never_embeds_images(scan_result):
    skill = scan_result.skills[0]
    source = """---
name: example
---
# Example
<script>alert(1)</script>

[relative](../guide%20book.md?q=1#part)
[root](/README.md)
[fragment](#example)
[external](https://example.org)
[unsafe](javascript:alert(1))
![diagram](image.png)
<img src="https://evil.test/tracker">
"""
    output = render(Document(skill, source))
    assert output.frontmatter == "---\nname: example\n---\n"
    assert "<script>" not in output.html
    assert "<img" not in output.html
    assert 'href="javascript:' not in output.html
    assert f"{skill.repository.url}/blob/{skill.commit_sha}/guide%20book.md?q=1#part" in output.html
    assert f"{skill.repository.url}/blob/{skill.commit_sha}/README.md" in output.html
    assert f"{skill.repository.url}/blob/{skill.commit_sha}/review/image.png" in output.html
    assert 'href="#example"' in output.html
    assert 'href="https://example.org"' in output.html
    assert "diagram (image)" in output.html
    assert render(Document(skill, "Plain text")).frontmatter == ""
