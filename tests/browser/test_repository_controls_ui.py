from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from skill_atlas.models import Repository

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


def seed(state, scan_result):
    for name, count in (("alpha", 3), ("beta", 1), ("gamma", 1)):
        repository = Repository("acme", name)
        state.catalog.replace_repository(
            replace(
                scan_result,
                repository=repository,
                skills=tuple(
                    replace(scan_result.skills[0], path=f"{i}/SKILL.md") for i in range(count)
                ),
            )
        )
        state.catalog.set_starred(repository, "0/SKILL.md", True)


def expect_order(page, names):
    expect(page.locator(".repository-row strong")).to_have_text([f"acme/{name}" for name in names])


@pytest.mark.parametrize(
    "width", [1360, 768, 601, 390], ids=["desktop", "tablet", "narrow", "mobile"]
)
def test_sort_filter_history_and_confirmed_removal(
    browser_page, web_environment, scan_result, width
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(page.base_url)
    sort = page.get_by_role("combobox", name="Sort by skills")
    expect(sort).to_have_value("none")
    expect_order(page, ["alpha", "beta", "gamma"])
    toggle = page.get_by_role("button", name="Toggle skills in acme/alpha")
    toggle.click()
    expect(page.locator(".catalog-skill:visible")).to_have_count(3)
    sort.focus()
    # Native select arrow keys open an OS popup on macOS; type-ahead works on both platforms.
    page.keyboard.press("a")
    page.keyboard.press("Enter")
    expect(sort).to_have_value("asc")
    expect_order(page, ["beta", "gamma", "alpha"])
    expect(toggle).to_have_attribute("aria-expanded", "true")
    assert parse_qs(urlsplit(page.url).query)["sort"] == ["asc"]
    expect(sort).to_be_focused()
    page.reload()
    expect(sort).to_have_value("asc")
    expect_order(page, ["beta", "gamma", "alpha"])
    page.get_by_role("link", name="acme/beta", exact=True).click()
    expect(page.get_by_role("link", name="All repositories")).to_be_visible()
    page.go_back()
    expect(sort).to_have_value("asc")
    expect_order(page, ["beta", "gamma", "alpha"])
    sort.select_option("desc")
    expect_order(page, ["alpha", "beta", "gamma"])
    if width < 600:
        page.get_by_role("button", name="Search skills", exact=True).click()
    field = page.get_by_role("searchbox")
    field.fill("review")
    page.get_by_role("checkbox", name="Starred only").check()
    expect(page.get_by_role("status")).to_have_text(
        "3 matching starred skills across 3 repositories"
    )
    sort.select_option("asc")
    expect_order(page, ["beta", "gamma", "alpha"])
    remove = page.get_by_role("button", name="Remove acme/alpha from catalog")
    page.once("dialog", lambda dialog: dialog.dismiss())
    remove.click()
    expect_order(page, ["beta", "gamma", "alpha"])
    assert len(state.catalog.skills(Repository("acme", "alpha"))) == 3

    def accept(dialog):
        assert "local stars" in dialog.message and "acme/alpha" in dialog.message
        dialog.accept()

    page.once("dialog", accept)
    remove.focus()
    page.keyboard.press("Enter")
    expect_order(page, ["beta", "gamma"])
    expect(page.get_by_role("heading", name="Repositories 2")).to_be_visible()
    expect(page.get_by_role("status")).to_have_text(
        "2 matching starred skills across 2 repositories"
    )
    expect(sort).to_be_focused()
    expect(sort).to_have_value("asc")
    assert not state.catalog.skills(Repository("acme", "alpha"))
    assert all(skill.starred for skill in state.catalog.skills())
    page.reload()
    expect_order(page, ["beta", "gamma"])
    sort.select_option("none")
    expect(sort).to_have_value("none")
    assert "sort" not in parse_qs(urlsplit(page.url).query)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert state.requests == []


def test_removal_failure_retry_and_last_repository(browser_page, web_environment, scan_result):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    page.goto(page.base_url)
    remove = page.get_by_role("button", name="Remove Acme/skills from catalog")
    page.on("dialog", lambda dialog: dialog.accept())
    page.route(
        "**/repositories/remove",
        lambda route: route.fulfill(
            status=500, body='<div role="alert">Could not remove the repository.</div>'
        ),
    )
    remove.click()
    expect(page.get_by_text("Could not remove the repository.")).to_be_visible()
    expect(page.locator(".repository-row")).to_have_count(1)
    expect(remove).to_be_enabled()
    assert state.catalog.skills() == scan_result.skills
    page.unroute("**/repositories/remove")
    remove.click()
    expect(page.get_by_role("heading", name="Repositories 0")).to_be_visible()
    expect(page.get_by_text("No repositories in your catalog yet.", exact=False)).to_be_visible()
    expect(page.get_by_role("dialog")).not_to_be_visible()
    expect(page.get_by_role("combobox", name="Sort by skills")).to_be_focused()
    page.reload()
    expect(page.locator(".repository-row")).to_have_count(0)
    assert state.catalog.repositories() == () and state.requests == []


def test_late_sort_response_cannot_restore_removed_repository(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    page.goto(page.base_url)
    held = []

    def hold(route):
        # Capture the response from before the removal, then deliver it late.
        held.append((route, route.fetch()))

    page.route("**/fragments/repositories?*sort=asc*", hold, times=1)
    sort = page.get_by_role("combobox", name="Sort by skills")
    with page.expect_request("**/fragments/repositories?*sort=asc*"):
        sort.select_option("asc")
    expect(page.locator("#repositories")).to_have_attribute("aria-busy", "true")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Remove acme/alpha from catalog").click()
    expect_order(page, ["beta", "gamma"])
    assert len(held) == 1
    route, response = held.pop()
    route.fulfill(response=response)
    expect_order(page, ["beta", "gamma"])
    assert state.requests == []


def test_scan_refresh_preserves_sort_and_reorders_changed_counts(
    browser_page, web_environment, scan_result, scan_from_home
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(replace(scan_result, skills=scan_result.skills[:1]))
    state.catalog.replace_repository(replace(scan_result, repository=Repository("other", "repo")))
    page.goto(page.base_url + "/?sort=desc")
    expect(page.locator(".repository-row strong")).to_have_text(["other/repo", "Acme/skills"])
    scan_from_home(scan_result.repository.url)
    expect(page.locator('.job[data-state="succeeded"]')).to_be_visible()
    expect(page.locator(".repository-row strong")).to_have_text(["acme/skills", "other/repo"])
    expect(page.get_by_role("combobox", name="Sort by skills")).to_have_value("desc")
    assert parse_qs(urlsplit(page.url).query)["sort"] == ["desc"]
