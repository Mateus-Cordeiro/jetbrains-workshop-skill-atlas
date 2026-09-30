import re
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import expect

from skill_atlas.models import Repository

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


def repository_url(page, result, **query):
    return (
        page.base_url
        + "/repository?"
        + urlencode({"repository_url": result.repository.url, **query})
    )


def test_home_expansion_filter_counts_clear_and_history(browser_page, web_environment, scan_result):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    other = Repository("other", "repo")
    state.catalog.replace_repository(replace(scan_result, repository=other))
    page.goto(page.base_url)
    toggle = page.get_by_role("button", name="Toggle skills in Acme/skills")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(page.locator(".catalog-skill:visible")).to_have_count(2)
    expect(page.locator(".catalog-skill").first).not_to_contain_text("review/SKILL.md")
    assert "skill_path=review%2FSKILL.md" in page.locator(".catalog-skill").first.get_attribute(
        "href"
    )
    field = page.get_by_role("searchbox", name="Filter skills across repositories")
    history_length = page.evaluate("history.length")
    field.fill("CODE maintain")
    expect(page.get_by_role("status")).to_have_text("2 matching skills across 2 repositories")
    expect(page.locator(".catalog-skill:visible")).to_have_count(2)
    expect(page.locator(".repository-row").first).to_contain_text("1 of 2 skills")
    Path("test-results").mkdir(exist_ok=True)
    page.screenshot(path="test-results/filtered-home.png", full_page=True)
    assert page.evaluate("history.length") == history_length
    toggle.click()
    field.fill("review")
    expect(page.get_by_role("status")).to_have_text("2 matching skills across 2 repositories")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(page.locator(".catalog-skill:visible")).to_have_count(1)
    page.reload()
    expect(field).to_have_value("review")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    page.locator(".catalog-skill:visible").click()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    expect(page.get_by_role("searchbox")).to_have_value("review")
    expect(page.locator(".skill-link")).to_have_count(1)
    page.go_back()
    expect(field).to_have_value("review")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    field.focus()
    page.keyboard.press("Escape")
    expect(field).to_have_value("")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_role("button", name="Toggle skills in other/repo")).to_have_attribute(
        "aria-expanded", "false"
    )
    expect(page.locator(".catalog-skill:visible")).to_have_count(2)
    assert "q" not in parse_qs(urlsplit(page.url).query)
    assert len(state.requests) == 1  # Only the selected document, never filtering/expansion.


def test_repository_filter_keeps_document_and_source_mode(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    page.goto(repository_url(page, scan_result, skill_path=scan_result.skills[0].path))
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    page.get_by_role("button", name="Source", exact=True).click()
    reads = len(state.requests)
    field = page.get_by_role("searchbox", name="Filter skills in this repository")
    field.fill("notes")
    expect(page.get_by_role("status")).to_have_text("1 of 2 skills")
    expect(page.locator(".skill-link")).to_have_count(1)
    expect(page.locator("#selection-filter-notice")).to_be_visible()
    expect(page.locator("#document-source")).to_be_visible()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    field.fill("no matches")
    expect(page.get_by_text("No skills match “no matches”.")).to_be_visible()
    expect(page.locator(".skill-link")).to_have_count(0)
    expect(page.locator("#document-source")).to_be_visible()
    assert len(state.requests) == reads
    page.locator(".filter-input button").click()
    expect(page.get_by_role("status")).to_have_text("2 skills")
    expect(page.locator(".skill-link[aria-current]")).to_contain_text("code-review")
    expect(page.locator("#selection-filter-notice")).to_be_hidden()
    expect(field).to_be_focused()
    field.fill("changes")
    expect(page.get_by_role("status")).to_have_text("2 of 2 skills")
    page.locator(".skill-link").nth(1).click()
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    page.go_back()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    expect(field).to_have_value("changes")
    page.reload()
    expect(field).to_have_value("changes")
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    page.get_by_role("link", name="All repositories").click()
    expect(page.get_by_role("searchbox")).to_have_value("changes")
    expect(page.locator(".catalog-skill:visible")).to_have_count(2)


def test_filter_empty_catalog_and_narrow_keyboard_layout(
    browser_page, web_environment, scan_result
):
    page = browser_page
    page.goto(page.base_url + "/?q=review")
    expect(page.get_by_text("No skills match “review”.")).to_be_visible()
    page.locator(".filter-input button").click()
    expect(page.get_by_text("No repositories in your catalog yet.", exact=False)).to_be_visible()
    web_environment.catalog.replace_repository(scan_result)
    page.reload()
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Search skills", exact=True).click()
    field = page.get_by_role("searchbox")
    field.fill("notes")
    expect(page.locator(".catalog-skill:visible")).to_have_count(1)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    Path("test-results").mkdir(exist_ok=True)
    page.screenshot(path="test-results/filtered-home-mobile.png", full_page=True)
    skill = page.locator(".catalog-skill")
    skill.focus()
    page.keyboard.press("Enter")
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    expect(page.get_by_role("searchbox")).to_have_value("notes")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path="test-results/filtered-repository-mobile.png", full_page=True)
    page.get_by_role("searchbox").focus()
    page.keyboard.press("Escape")
    expect(page.locator(".skill-link")).to_have_count(2)
    expect(page.get_by_role("searchbox")).to_be_focused()


def test_filter_failures_keep_results_and_offer_retry(browser_page, web_environment, scan_result):
    page = browser_page
    web_environment.catalog.replace_repository(scan_result)
    page.goto(page.base_url)
    page.route("**/fragments/repositories?*", lambda route: route.fulfill(status=500))
    page.get_by_role("searchbox").fill("notes")
    expect(page.locator("#filter-error")).to_contain_text("Previous results are still shown")
    expect(page.locator(".repository-row")).to_have_count(1)
    expect(page.get_by_text("No skills match", exact=False)).to_have_count(0)
    page.unroute("**/fragments/repositories?*")
    page.locator("#filter-error").get_by_role("button", name="Retry").click()
    expect(page.locator(".catalog-skill")).to_have_count(1)
    expect(page.locator("#filter-error")).to_be_empty()
    page.locator(".filter-input button").click()
    expect(page.get_by_role("searchbox")).to_have_value("")
    expect(page.locator(".repository-toggle")).to_have_attribute("aria-expanded", "false")
    page.route("**/fragments/repository-skills?*", lambda route: route.fulfill(status=500))
    page.locator(".repository-toggle").click()
    expect(page.locator(".repository-skills")).to_contain_text("Could not load skills")
    page.unroute("**/fragments/repository-skills?*")
    page.locator(".repository-skills").get_by_role("button", name="Retry").click()
    expect(page.locator(".catalog-skill:visible")).to_have_count(2)


def test_late_filter_and_expansion_responses_are_ignored(
    browser_page, web_environment, scan_result
):
    page = browser_page
    web_environment.catalog.replace_repository(scan_result)
    held = []
    page.route("**/fragments/repositories?q=review", lambda route: held.append(route))
    page.goto(page.base_url)
    with page.expect_request("**/fragments/repositories?q=review"):
        page.get_by_role("searchbox").fill("review")
    page.get_by_role("searchbox").fill("notes")
    expect(page.locator(".catalog-skill")).to_have_count(1)
    expect(page.locator(".catalog-skill")).to_contain_text("release-notes")
    held.pop().fulfill(status=200, content_type="text/html", body="<p>Obsolete filter</p>")
    expect(page.get_by_text("Obsolete filter")).to_have_count(0)
    page.locator(".filter-input button").click()
    expect(page.locator(".repository-toggle")).to_have_attribute("aria-expanded", "false")
    page.route("**/fragments/repository-skills?*", lambda route: held.append(route))
    with page.expect_request("**/fragments/repository-skills?*"):
        page.locator(".repository-toggle").click()
    page.get_by_role("searchbox").fill("notes")
    expect(page.locator(".catalog-skill")).to_have_count(1)
    held.pop().fulfill(status=200, content_type="text/html", body="<p>Obsolete expansion</p>")
    expect(page.get_by_text("Obsolete expansion")).to_have_count(0)
    assert not web_environment.requests


def test_pending_list_filter_preserves_newer_document_selection(
    browser_page, web_environment, scan_result
):
    page = browser_page
    web_environment.catalog.replace_repository(scan_result)
    held = []

    def hold(route):
        held.append((route, route.fetch()))

    page.route("**/fragments/skills?*", hold)
    page.goto(repository_url(page, scan_result, skill_path=scan_result.skills[0].path))
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    with page.expect_request("**/fragments/skills?*"):
        page.get_by_role("searchbox").fill("changes")
    page.locator(".skill-link").nth(1).click()
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    route, response = held.pop()
    route.fulfill(response=response)
    expect(page.get_by_role("status")).to_have_text("2 of 2 skills")
    expect(page.locator(".skill-link[aria-current]")).to_contain_text("release-notes")
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    assert parse_qs(urlsplit(page.url).query)["q"] == ["changes"]


def test_rescan_reapplies_filters_and_clears_deleted_selection(
    browser_page, web_environment, scan_result, scan_from_home
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    page.goto(repository_url(page, scan_result, q="review", skill_path=scan_result.skills[0].path))
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    state.commit = "d" * 40
    scan_from_home(scan_result.repository.url)
    expect(page.get_by_role("link", name="View on GitHub")).to_have_attribute(
        "href", re.compile("/blob/" + "d" * 40 + "/")
    )
    expect(page.get_by_role("searchbox")).to_have_value("review")
    expect(page.get_by_role("status")).to_have_text("2 of 2 skills")
    state.zero = True
    scan_from_home(scan_result.repository.url)
    expect(
        page.locator("#workspace").get_by_role("heading", name="No skills found")
    ).to_be_visible()
    expect(page.locator("#document")).to_have_count(0)
    assert parse_qs(urlsplit(page.url).query)["q"] == ["review"]
    assert "skill_path" not in parse_qs(urlsplit(page.url).query)


def test_query_changed_during_workspace_refresh_is_preserved(
    browser_page, web_environment, scan_result, scan_from_home
):
    page = browser_page
    web_environment.catalog.replace_repository(scan_result)
    held = []

    def hold(route):
        held.append((route, route.fetch()))

    page.route("**/fragments/repository?*", hold, times=1)
    page.goto(repository_url(page, scan_result, skill_path=scan_result.skills[0].path))
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    with page.expect_request("**/fragments/repository?*"):
        scan_from_home(scan_result.repository.url)
    page.get_by_role("searchbox").fill("absent")
    expect(page.get_by_role("status")).to_have_text("0 of 2 skills")
    route, response = held.pop()
    route.fulfill(response=response)
    expect(page.get_by_role("searchbox")).to_have_value("absent")
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    expect(page.get_by_role("status")).to_have_text("0 of 2 skills")
    expect(page.locator("#selection-filter-notice")).to_be_visible()


def test_filter_does_not_cancel_inflight_document(browser_page, web_environment, scan_result):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    held = []

    def hold(route):
        held.append((route, route.fetch()))

    page.route("**/fragments/document?*", hold)
    page.goto(repository_url(page, scan_result))
    with page.expect_request("**/fragments/document?*"):
        page.locator(".skill-link").first.click()
    page.get_by_role("searchbox").fill("notes")
    expect(page.get_by_role("status")).to_have_text("1 of 2 skills")
    expect(page.locator("#selection-filter-notice")).to_be_visible()
    route, response = held.pop()
    route.fulfill(response=response)
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    expect(page.locator(".skill-link")).to_contain_text("release-notes")
    assert len(state.requests) == 1


def test_home_scan_refresh_preserves_filter_and_manual_collapse(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    page.goto(page.base_url + "/?q=review")
    expect(page.get_by_role("status")).to_have_text("1 matching skill across 1 repository")
    page.locator(".repository-toggle").click()
    page.get_by_role("button", name="Add repository").click()
    page.get_by_role("textbox", name="GitHub repository URL").fill(scan_result.repository.url)
    page.get_by_role("button", name="Scan repository").click()
    expect(page.get_by_role("status")).to_have_text("2 matching skills across 1 repository")
    expect(page.locator(".repository-toggle")).to_have_attribute("aria-expanded", "false")
    expect(page.get_by_role("searchbox")).to_have_value("review")
    page.locator(".repository-toggle").click()
    expect(page.locator(".catalog-skill:visible")).to_have_count(2)


@pytest.mark.parametrize("width", [1360, 390])
def test_repository_has_one_live_count_above_filter(
    browser_page, web_environment, scan_result, width
):
    page = browser_page
    web_environment.catalog.replace_repository(scan_result)
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(repository_url(page, scan_result))
    count = page.get_by_role("status")
    expect(count).to_have_count(1)
    expect(count).to_have_text("2 skills")
    expect(page.get_by_text("2 skills", exact=True)).to_have_count(1)
    expect(page.locator(".repository-heading")).not_to_contain_text("2 skills")
    if width == 390:
        page.get_by_role("button", name="Search skills", exact=True).click()
    field = page.get_by_role("searchbox")
    label_box, field_box = count.bounding_box(), field.bounding_box()
    assert label_box["y"] + label_box["height"] < field_box["y"]
    for query, expected in (("review", "1 of 2 skills"), ("absent", "0 of 2 skills")):
        field.fill(query)
        expect(count).to_have_text(expected)
        expect(page.get_by_text(expected, exact=True)).to_have_count(1)
        expect(field).to_be_focused()
    page.reload()
    expect(count).to_have_text("0 of 2 skills")
    field.press("Escape")
    expect(count).to_have_text("2 skills")
    page.route("**/fragments/skills?*", lambda route: route.fulfill(status=500))
    field.fill("review")
    expect(page.locator("#filter-error")).to_contain_text("Previous results are still shown")
    expect(count).to_have_text("2 skills")
    page.unroute("**/fragments/skills?*")
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(count).to_have_text("1 of 2 skills")
