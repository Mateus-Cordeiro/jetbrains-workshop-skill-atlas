from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import expect

from skill_atlas.models import Repository

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


def query(page):
    return parse_qs(urlsplit(page.url).query)


def starred_paths(state):
    return [(skill.repository.url, skill.path) for skill in state.catalog.skills() if skill.starred]


def only_document_reads(state):
    return all("/contents/" in request.url.path for request in state.requests)


def test_star_toggles_stay_in_sync_and_starred_only_survives_reload(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    review = scan_result.skills[0]
    page.goto(
        page.base_url
        + "/repository?"
        + urlencode({"repository_url": review.repository.url, "skill_path": review.path})
    )
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    stars = page.get_by_role("button", name="Star code-review", exact=True)
    expect(stars).to_have_count(2)  # The skill card and the open document's header.
    for index in range(2):
        expect(stars.nth(index)).to_have_attribute("aria-pressed", "false")
    stars.first.click()
    for index in range(2):
        expect(stars.nth(index)).to_have_attribute("aria-pressed", "true")
    assert starred_paths(state) == [(review.repository.url, review.path)]
    expect(page.locator(".skill-link[aria-current]")).to_contain_text("code-review")

    history_length = page.evaluate("history.length")
    starred_only = page.get_by_role("checkbox", name="Starred only")
    starred_only.check()
    expect(page.get_by_role("status")).to_have_text("1 of 2 skills")
    expect(page.locator(".skill-link")).to_have_count(1)
    assert query(page)["starred"] == ["1"]
    assert page.evaluate("history.length") == history_length
    Path("test-results").mkdir(exist_ok=True)
    page.screenshot(path="test-results/stars-repository.png", full_page=True)

    page.reload()
    expect(starred_only).to_be_checked()
    expect(page.get_by_role("status")).to_have_text("1 of 2 skills")
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")

    # Unstarring the open document refreshes the starred list but keeps the document.
    page.locator(".document-toolbar").get_by_role("button", name="Star code-review").click()
    expect(page.get_by_text("No starred skills.")).to_be_visible()
    expect(page.get_by_role("status")).to_have_text("0 of 2 skills")
    expect(page.locator("#selection-filter-notice")).to_be_visible()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    assert starred_paths(state) == []
    page.get_by_role("button", name="Show all skills").click()
    expect(starred_only).not_to_be_checked()
    expect(starred_only).to_be_focused()
    expect(page.locator(".skill-link")).to_have_count(2)
    assert "starred" not in query(page)
    assert only_document_reads(state)
    expect(page.locator(".job")).to_have_count(0)


@pytest.mark.parametrize("width", [1360, 390], ids=["desktop", "mobile"])
def test_home_starred_only_reveals_starred_skills_across_navigation(
    browser_page, web_environment, scan_result, width
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    other = Repository("other", "repo")
    state.catalog.replace_repository(replace(scan_result, repository=other))
    review = scan_result.skills[0]
    state.catalog.set_starred(other, review.path, True)
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(page.base_url)
    expect(page.locator(".catalog-skill:visible")).to_have_count(0)
    starred_only = page.get_by_role("checkbox", name="Starred only")
    if width < 600:
        expect(starred_only).to_be_hidden()
        page.get_by_role("button", name="Search skills").click()
    starred_only.focus()
    page.keyboard.press("Space")
    expect(page.get_by_role("status")).to_have_text("1 matching starred skill across 1 repository")
    expect(page.locator(".repository-row")).to_have_count(1)
    expect(page.locator(".repository-row")).to_contain_text("1 of 2 skills")
    expect(page.locator(".catalog-skill:visible")).to_have_count(1)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=f"test-results/stars-home-{width}.png", full_page=True)

    page.locator(".catalog-skill:visible").click()
    expect(page.get_by_role("checkbox", name="Starred only")).to_be_checked()
    expect(page.locator(".skill-link")).to_have_count(1)
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    assert query(page)["starred"] == ["1"]
    page.get_by_role("link", name="All repositories").click()
    expect(starred_only).to_be_checked()
    page.go_back()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    page.go_back()
    expect(starred_only).to_be_checked()
    expect(starred_only).to_be_visible()
    expect(page.locator(".catalog-skill:visible")).to_have_count(1)

    star = page.get_by_role("button", name="Star code-review")
    expect(star).to_have_attribute("aria-pressed", "true")
    star.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_text("No starred skills.")).to_be_visible()
    expect(starred_only).to_be_focused()
    expect(page.get_by_role("heading", name="Repositories 0")).to_be_visible()
    expect(page.locator("#repository-form")).to_be_hidden()
    assert starred_paths(state) == []
    page.keyboard.press("Space")
    expect(page.locator(".repository-row")).to_have_count(2)
    expect(page.locator(".catalog-skill:visible")).to_have_count(0)
    assert only_document_reads(state)


def test_similarity_cards_star_their_own_location(browser_page, web_environment, similar_catalog):
    page, state = browser_page, web_environment
    source = similar_catalog.source
    page.goto(
        page.base_url
        + "/similar?"
        + urlencode({"repository_url": source.repository.url, "skill_path": source.path})
    )
    card = page.locator(".similar-result").first
    card.get_by_role("button", name="Star code-review").click()
    expect(card.get_by_role("button", name="Star code-review")).to_have_attribute(
        "aria-pressed", "true"
    )
    first = card.locator(".skill-heading .skill-link")
    assert starred_paths(state) == [
        (first.get_attribute("data-skill-repository"), first.get_attribute("data-skill-path"))
    ]
    page.reload()
    expect(card.get_by_role("button", name="Star code-review")).to_have_attribute(
        "aria-pressed", "true"
    )
    assert not state.requests
