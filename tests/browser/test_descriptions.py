import re
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import expect

from skill_atlas.models import Repository, ScanResult

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])

LONG_DESCRIPTION = "Review code changes for correctness and maintainability. " * 14 + "UniqueTail"


def assert_collapsed(card):
    expect(card.locator(".description-toggle")).to_be_visible()
    expect(card.locator(".description-toggle")).to_have_attribute("aria-expanded", "false")
    assert card.locator(".skill-description").evaluate("el => el.scrollHeight > el.clientHeight")


def assert_expanded(card):
    expect(card.locator(".description-toggle")).to_have_attribute("aria-expanded", "true")
    assert card.locator(".skill-description").evaluate("el => el.scrollHeight === el.clientHeight")


@pytest.mark.parametrize("width", [1360, 390], ids=["desktop", "mobile"])
def test_similarity_reuses_description_controls_and_keeps_scores_and_selection(
    browser_page, web_environment, similar_catalog, width
):
    page, state, fixture = browser_page, web_environment, similar_catalog
    for repository in (fixture.source.repository, fixture.remote.repository):
        skills = tuple(
            replace(skill, description=LONG_DESCRIPTION)
            for skill in state.catalog.skills(repository)
        )
        state.catalog.replace_repository(ScanResult(repository, skills[0].commit_sha, skills))
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(
        page.base_url
        + "/similar?"
        + urlencode(
            {
                "repository_url": fixture.source.repository.url,
                "skill_path": fixture.source.path,
                "q": "original query",
            }
        )
    )
    cards = page.locator(".skill-item")
    expect(cards).to_have_count(3)
    first, second = cards.nth(0), cards.nth(1)
    assert_collapsed(first)
    assert_collapsed(second)
    expect(first.get_by_role("meter")).to_have_attribute("value", "100")
    expect(cards.locator("code")).to_have_count(0)
    original_url = page.url
    first.locator(".description-toggle").focus()
    page.keyboard.press("Enter")
    assert_expanded(first)
    assert_collapsed(second)
    assert page.url == original_url
    assert not state.requests
    first.locator(".skill-link").click()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    page.get_by_role("button", name="Source", exact=True).click()
    selected_url, reads = page.url, len(state.requests)
    first.locator(".description-toggle").focus()
    page.keyboard.press("Space")
    assert_collapsed(first)
    expect(page.locator("#document-source")).to_be_visible()
    expect(first.locator(".skill-link")).to_have_attribute("aria-current", "true")
    assert page.url == selected_url
    assert len(state.requests) == reads
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.locator(".skills-pane").evaluate("el => el.scrollTop = 0")
    page.screenshot(path=f"test-results/similar-descriptions-{width}.png", full_page=True)
    page.reload()
    assert_collapsed(first)
    expect(first.locator(".skill-link")).to_have_attribute("aria-current", "true")
    # A stale selection replaces the workspace and initializes the shared controls again.
    updated = tuple(
        replace(skill, commit_sha="d" * 40)
        for skill in state.catalog.skills(fixture.source.repository)
    )
    state.catalog.replace_repository(ScanResult(fixture.source.repository, "d" * 40, updated))
    first.locator(".skill-link").click()
    expect(page.get_by_role("link", name="View on GitHub")).to_have_attribute(
        "href", re.compile("/blob/" + "d" * 40 + "/")
    )
    assert_collapsed(first)
    first.locator(".description-toggle").click()
    assert_expanded(first)
    # The shared action can start another search from a result, preserving return context.
    second.get_by_role("link", name="Similar skills", exact=False).click()
    expect(page.get_by_role("heading", name="Similar to “patch-audit”")).to_be_visible()
    assert parse_qs(urlsplit(page.url).query)["q"] == ["original query"]


@pytest.mark.parametrize("width", [1360, 390], ids=["desktop", "mobile"])
def test_home_description_controls_after_expansion_filtering_and_navigation(
    browser_page, web_environment, scan_result, width
):
    page, state = browser_page, web_environment
    first = replace(
        scan_result.skills[0], path="nested/a #? &/SKILL.md", description=LONG_DESCRIPTION
    )
    short = replace(scan_result.skills[1], description="Short description.")
    state.catalog.replace_repository(replace(scan_result, skills=(first, short)))
    state.catalog.replace_repository(
        replace(scan_result, repository=Repository("other", "repo"), skills=(first,))
    )
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(page.base_url)
    groups = page.locator(".repository-group")
    for group in groups.all():
        group.locator(".repository-toggle").click()
    expect(page.locator(".catalog-skill")).to_have_count(3)
    first_card = groups.nth(0).locator(".skill-item").first
    other_card = groups.nth(1).locator(".skill-item").first
    assert_collapsed(first_card)
    assert_collapsed(other_card)
    expect(groups.nth(0).locator(".description-toggle").nth(1)).to_be_hidden()
    expect(page.locator(".repository-skill-list code")).to_have_count(0)
    assert first.path not in page.locator("#repositories").inner_text()
    ids = page.locator(".skill-description").evaluate_all("els => els.map(el => el.id)")
    assert len(ids) == len(set(ids))
    for button in page.locator(".description-toggle").all():
        assert button.evaluate(
            "el => document.getElementById(el.getAttribute('aria-controls'))"
            " === el.parentElement.querySelector('.skill-description')"
        )
    original_url = page.url
    first_card.locator(".description-toggle").focus()
    page.keyboard.press("Enter")
    assert_expanded(first_card)
    assert_collapsed(other_card)
    expect(first_card.locator(".skill-description")).to_have_text(LONG_DESCRIPTION)
    page.keyboard.press("Space")
    assert_collapsed(first_card)
    assert page.url == original_url
    assert not state.requests

    field = page.get_by_role("searchbox")
    if not field.is_visible():
        page.get_by_role("button", name="Search skills", exact=True).click()
    field.fill("UniqueTail")
    expect(page.get_by_role("status")).to_have_text("2 matching skills across 2 repositories")
    assert_collapsed(first_card)
    assert_collapsed(other_card)
    other_card.locator(".description-toggle").click()
    assert_expanded(other_card)
    assert_collapsed(first_card)
    groups.nth(1).locator(".repository-toggle").click()
    groups.nth(1).locator(".repository-toggle").click()
    assert_expanded(other_card)
    assert not state.requests
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    Path("test-results").mkdir(exist_ok=True)
    page.screenshot(path=f"test-results/home-descriptions-{width}.png", full_page=True)

    page.reload()
    assert_collapsed(first_card)
    assert_collapsed(other_card)
    other_card.locator(".catalog-skill").click()
    expect(page.locator(".document-toolbar code")).to_have_text(first.path)
    assert parse_qs(urlsplit(page.url).query)["q"] == ["UniqueTail"]
    assert len(state.requests) == 1


def test_filtered_repository_descriptions_keep_selection_source_and_query(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    long_skill = replace(scan_result.skills[1], description=LONG_DESCRIPTION)
    state.catalog.replace_repository(
        replace(scan_result, skills=(scan_result.skills[0], long_skill))
    )
    page.goto(
        page.base_url
        + "/repository?"
        + urlencode(
            {
                "repository_url": scan_result.repository.url,
                "skill_path": scan_result.skills[0].path,
            }
        )
    )
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    page.get_by_role("button", name="Source", exact=True).click()
    reads = len(state.requests)
    field = page.get_by_role("searchbox")
    if not field.is_visible():
        page.get_by_role("button", name="Search skills", exact=True).click()
    field.fill("UniqueTail")
    expect(page.get_by_role("status")).to_have_text("1 of 2 skills")
    card = page.locator(".skill-item")
    assert_collapsed(card)
    filtered_url = page.url
    card.locator(".description-toggle").click()
    assert_expanded(card)
    expect(page.locator("#document-source")).to_be_visible()
    expect(page.locator("#selection-filter-notice")).to_be_visible()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    assert page.url == filtered_url
    assert len(state.requests) == reads
    field.fill("no matching skills")
    expect(page.locator(".skill-item")).to_have_count(0)
    field.press("Escape")
    expect(page.locator(".skill-item")).to_have_count(2)
    assert_collapsed(page.locator(".skill-item").nth(1))
    expect(page.locator(".skill-link[aria-current]")).to_contain_text("code-review")
    page.locator(".skill-item").nth(1).locator(".description-toggle").click()
    assert_expanded(page.locator(".skill-item").nth(1))
    expect(page.locator("#document-source")).to_be_visible()
    assert len(state.requests) == reads


def test_home_scan_refresh_reinitializes_description_controls(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    state.source = f"---\nname: refreshed\ndescription: {LONG_DESCRIPTION}\n---\n# Refreshed\n"
    page.goto(page.base_url + "/?q=UniqueTail")
    expect(page.locator(".catalog-skill")).to_have_count(0)
    page.get_by_role("button", name="Add repository").click()
    page.get_by_role("textbox", name="GitHub repository URL").fill(scan_result.repository.url)
    page.get_by_role("button", name="Scan repository").click()
    expect(page.get_by_role("status")).to_have_text("2 matching skills across 1 repository")
    card = page.locator(".skill-item").first
    assert_collapsed(card)
    reads = len(state.requests)
    card.locator(".description-toggle").click()
    assert_expanded(card)
    expect(page.get_by_role("searchbox")).to_have_value("UniqueTail")
    assert len(state.requests) == reads
