from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


@pytest.mark.parametrize("width", [1360, 390], ids=["desktop", "mobile"])
def test_compact_home_add_form_and_search(browser_page, web_environment, scan_result, width):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(page.base_url)
    expect(page.get_by_role("heading", name="Repositories 1")).to_be_visible()
    expect(page.locator(".repository-row code")).to_have_count(0)
    assert page.locator(".repository-row").bounding_box()["y"] < 300
    expect(page.get_by_text("Your skill library.", exact=True)).to_have_count(0)
    add = page.get_by_role("button", name="Add repository")
    url = page.get_by_role("textbox", name="GitHub repository URL")
    expect(url).to_be_hidden()
    add.focus()
    page.keyboard.press("Enter")
    expect(add).to_have_attribute("aria-expanded", "true")
    expect(url).to_be_focused()
    url.fill("https://github.com/example/new")
    add.click()
    expect(url).to_be_hidden()
    add.click()
    expect(url).to_have_value("https://github.com/example/new")

    field = page.get_by_role("searchbox")
    search = page.get_by_role("button", name="Search skills", exact=True)
    if width == 390:
        expect(field).to_be_hidden()
        search.focus()
        page.keyboard.press("Space")
        expect(field).to_be_focused()
        expect(search).to_have_attribute("aria-expanded", "true")
    else:
        expect(field).to_be_visible()
        expect(search).to_be_hidden()
    field.fill("notes")
    expect(page.get_by_role("status")).to_have_text("1 matching skill across 1 repository")
    expect(url).to_have_value("https://github.com/example/new")
    field.fill("missing")
    expect(page.get_by_role("heading", name="Repositories 0")).to_be_visible()
    field.press("Escape")
    expect(page.get_by_role("heading", name="Repositories 1")).to_be_visible()
    expect(field).to_be_focused()
    assert not state.requests
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("scope", ["home", "repository"])
def test_mobile_search_visibility_history_and_resize(
    browser_page, web_environment, scan_result, scope
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    page.set_viewport_size({"width": 390, "height": 1000})
    start = page.base_url
    if scope == "repository":
        start += "/repository?" + urlencode({"repository_url": scan_result.repository.url})
    page.goto(start)
    field = page.get_by_role("searchbox")
    toggle = page.get_by_role("button", name="Search skills", exact=True)
    expect(field).to_be_hidden()
    toggle.click()
    expect(field).to_be_focused()
    toggle.click()
    expect(field).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    toggle.click()
    field.fill("notes")
    expect(page.get_by_role("status")).to_contain_text("1")
    toggle.click()
    expect(field).to_be_visible()
    expect(field).to_be_focused()
    page.reload()
    expect(field).to_have_value("notes")
    expect(field).to_be_visible()
    page.set_viewport_size({"width": 1360, "height": 1000})
    expect(field).to_be_visible()
    expect(toggle).to_be_hidden()
    page.set_viewport_size({"width": 390, "height": 1000})
    expect(field).to_be_visible()
    page.locator(".catalog-skill, .skill-link").first.click()
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    page.go_back()
    expect(field).to_have_value("notes")
    expect(field).to_be_visible()
    field.press("Escape")
    expect(field).to_be_visible()
    expect(field).to_be_focused()
    expect(field).to_have_value("")
    toggle.click()
    expect(field).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_empty_catalog_opens_form_but_no_matches_does_not(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    page.goto(page.base_url)
    field = page.get_by_role("textbox", name="GitHub repository URL")
    expect(field).to_be_visible()
    expect(page.get_by_role("button", name="Add repository")).to_have_attribute(
        "aria-expanded", "true"
    )
    state.catalog.replace_repository(scan_result)
    page.goto(page.base_url + "/?q=absent")
    expect(field).to_be_hidden()
    expect(page.get_by_text("No skills match “absent”.")).to_be_visible()
    state.catalog.replace_repository(replace(scan_result, skills=()))
    page.get_by_role("searchbox").press("Escape")
    expect(field).to_be_visible()
    expect(page.get_by_role("heading", name="Repositories 0")).to_be_visible()
    assert not state.requests


@pytest.mark.parametrize("width", [1360, 390], ids=["desktop", "mobile"])
def test_skill_actions_are_separate_and_repository_has_no_scan_or_hash(
    browser_page, web_environment, scan_result, width
):
    page, state = browser_page, web_environment
    skill = replace(scan_result.skills[0], description="Review code and documentation. " * 25)
    state.catalog.replace_repository(replace(scan_result, skills=(skill,)))
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(page.base_url + "/repository?" + urlencode({"repository_url": skill.repository.url}))
    expect(page.get_by_role("button", name="Scan repository", exact=False)).to_have_count(0)
    expect(page.get_by_role("button", name="Rescan", exact=False)).to_have_count(0)
    expect(page.get_by_text(skill.commit_sha[:8], exact=False)).to_have_count(0)
    card = page.locator(".skill-item")
    title = card.get_by_role("link", name=skill.name, exact=True)
    similar = card.get_by_role("link", name="Similar skills", exact=False)
    more = card.get_by_role("button", name="Show more", exact=False)
    expect(similar).to_be_visible()
    expect(more).to_be_visible()
    assert similar.bounding_box()["y"] < more.bounding_box()["y"]
    assert title.bounding_box()["x"] + title.bounding_box()["width"] <= similar.bounding_box()["x"]
    original_url = page.url
    more.click()
    expect(card.get_by_role("button", name="Show less", exact=False)).to_be_visible()
    assert page.url == original_url and not state.requests
    title.click()
    expect(page.locator(".document-toolbar strong")).to_have_text(skill.name)
    expect(page.get_by_role("link", name="View on GitHub")).to_have_attribute("href", skill.url)
    expect(page.get_by_text(skill.commit_sha[:8], exact=False)).to_have_count(0)
    assert state.requests[-1].url.params["ref"] == skill.commit_sha
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    Path("test-results").mkdir(exist_ok=True)
    page.screenshot(path=f"test-results/catalog-layout-{width}.png", full_page=True)

    similar.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("heading", name=f"Similar to “{skill.name}”")).to_be_visible()
