from dataclasses import replace
from urllib.parse import urlencode

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


def register_and_preview(page, project, source):
    page.get_by_label("Register local project").fill(str(project))
    page.get_by_role("button", name="Register project", exact=True).click()
    expect(page.get_by_label("Project", exact=True).locator("option")).to_have_count(2)
    page.get_by_label("Project", exact=True).select_option(str(project))
    page.get_by_label("Catalog skill", exact=True).select_option(
        source.repository.url + "|" + source.path
    )
    page.get_by_role("button", name="Preview destination / refresh status").click()
    expect(page.locator("#installation-destination")).to_have_text(
        str(project / ".agents/skills/code-review")
    )


@pytest.mark.parametrize("width", [1360, 390])
def test_registration_destination_install_conflict_update_uninstall(
    browser_page, web_environment, scan_result, tmp_path, width
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    project = tmp_path / "my local project"
    project.mkdir()
    source = scan_result.skills[0]
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(page.base_url)
    page.get_by_role("link", name="Installations", exact=True).click()
    expect(
        page.get_by_text("Select a registered project to see its installations.")
    ).to_be_visible()
    assert not state.requests
    register_and_preview(page, project, source)
    assert not (project / ".agents").exists()
    page.get_by_role("button", name="Install skill", exact=True).focus()
    page.keyboard.press("Enter")
    expect(page.locator(".installation-status")).to_have_text("current")
    target = project / ".agents/skills/code-review"
    assert (target / "SKILL.md").read_text() == state.source
    page.reload()
    expect(page.locator(".installation-status")).to_have_text("current")
    page.get_by_role("button", name="Install skill", exact=True).click()
    expect(page.locator("#installation-feedback")).to_contain_text("Already installed")
    (target / "notes.txt").write_text("Keep my work")
    page.get_by_role("button", name="Uninstall skill", exact=True).click()
    expect(page.locator("#installation-feedback")).to_contain_text("notes.txt")
    expect(page.locator("#installation-feedback")).to_be_focused()
    page.reload()
    expect(page.locator(".installation-status")).to_have_text("modified")
    expect(page.get_by_role("button", name="Uninstall skill", exact=True)).to_be_disabled()
    (target / "notes.txt").unlink()
    state.commit = "d" * 40
    state.source += "\nUpdated scanned content.\n"
    state.catalog.replace_repository(
        replace(
            scan_result,
            commit_sha=state.commit,
            skills=tuple(replace(s, commit_sha=state.commit) for s in scan_result.skills),
        )
    )
    # A stale preview cannot install the new scan without another destination review.
    page.get_by_role("button", name="Update installed skill", exact=True).click()
    expect(page.locator("#installation-feedback")).to_contain_text("catalog changed")
    page.reload()
    expect(page.locator(".installation-status")).to_have_text("update available")
    page.get_by_role("button", name="Update installed skill", exact=True).click()
    expect(page.locator(".installation-status")).to_have_text("current")
    assert "Updated scanned content" in (target / "SKILL.md").read_text()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=f"test-results/installations-{width}.png", full_page=True)
    state.catalog.remove_repository(source.repository)
    page.goto(page.base_url + "/installations?" + urlencode({"project": str(project)}))
    expect(page.locator(".installation-status")).to_have_text("source unavailable")
    page.get_by_role("button", name="Uninstall skill", exact=True).click()
    expect(page.get_by_text("No skills installed in this project.")).to_be_visible()
    assert not target.exists()


def test_document_install_link_explicit_project_and_claude_destination(
    browser_page, web_environment, scan_result, tmp_path
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    source = scan_result.skills[0]
    project = tmp_path / "claude project"
    project.mkdir()
    page.goto(
        page.base_url
        + "/repository?"
        + urlencode({"repository_url": source.repository.url, "skill_path": source.path})
    )
    page.get_by_role("link", name="Install…", exact=True).click()
    expect(page.get_by_label("Catalog skill", exact=True)).to_have_value(
        source.repository.url + "|" + source.path
    )
    expect(page.get_by_role("button", name="Install skill", exact=True)).to_have_count(0)
    register_and_preview(page, project, source)
    page.get_by_label("Agent", exact=True).select_option("claude")
    page.get_by_role("button", name="Preview destination / refresh status").click()
    expect(page.locator("#installation-destination")).to_have_text(
        str(project / ".claude/skills/code-review")
    )
    page.get_by_role("button", name="Install skill", exact=True).click()
    expect(page.locator(".installation-status")).to_have_text("current")
    assert (project / ".claude/skills/code-review/SKILL.md").exists()
    page.go_back()
    expect(page.get_by_label("Agent", exact=True)).to_have_value("codex")
