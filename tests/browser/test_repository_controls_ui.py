from dataclasses import replace
from pathlib import Path
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


def expect_sort(page, direction):
    header = page.get_by_role("columnheader").filter(
        has=page.get_by_role("button", name="Sort by skills", exact=True)
    )
    expect(header).to_have_attribute("aria-sort", direction)


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
    sort = page.get_by_role("button", name="Sort by skills", exact=True)
    expect_sort(page, "none")
    expect_order(page, ["alpha", "beta", "gamma"])
    toggle = page.get_by_role("button", name="Toggle skills in acme/alpha")
    toggle.click()
    expect(page.locator(".catalog-skill:visible")).to_have_count(3)
    sort.focus()
    page.keyboard.press("Enter")
    expect_sort(page, "ascending")
    expect_order(page, ["beta", "gamma", "alpha"])
    expect(toggle).to_have_attribute("aria-expanded", "true")
    assert parse_qs(urlsplit(page.url).query)["sort"] == ["asc"]
    expect(sort).to_be_focused()
    page.reload()
    expect_sort(page, "ascending")
    expect_order(page, ["beta", "gamma", "alpha"])
    page.get_by_role("link", name="acme/beta", exact=True).click()
    expect(page.get_by_role("link", name="All repositories")).to_be_visible()
    page.go_back()
    expect_sort(page, "ascending")
    expect_order(page, ["beta", "gamma", "alpha"])
    sort.press("Space")
    expect_sort(page, "descending")
    expect_order(page, ["alpha", "beta", "gamma"])
    if width < 600:
        page.get_by_role("button", name="Search skills", exact=True).click()
    field = page.get_by_role("searchbox")
    field.fill("review")
    page.get_by_role("checkbox", name="Starred only").check()
    expect(page.get_by_role("status")).to_have_text(
        "3 matching starred skills across 3 repositories"
    )
    sort.click()
    expect_sort(page, "none")
    sort.click()
    expect_sort(page, "ascending")
    expect_order(page, ["beta", "gamma", "alpha"])
    remove = page.get_by_role("button", name="Remove acme/alpha from catalog")
    remove.click()
    dialog = page.get_by_role("dialog", name="Remove repository?")
    expect(dialog.get_by_text("acme/alpha", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Cancel", exact=True)).to_be_focused()
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(remove).to_be_focused()
    expect_order(page, ["beta", "gamma", "alpha"])
    assert len(state.catalog.skills(Repository("acme", "alpha"))) == 3

    remove.press("Enter")
    expect(dialog).to_contain_text("local stars")
    expect(dialog).to_contain_text("GitHub stays untouched")
    dialog.get_by_role("button", name="Remove repository", exact=True).press("Enter")
    expect(dialog).to_be_hidden()
    expect_order(page, ["beta", "gamma"])
    expect(page.get_by_role("heading", name="Repositories 2")).to_be_visible()
    expect(page.get_by_role("status")).to_have_text(
        "2 matching starred skills across 2 repositories"
    )
    expect(sort).to_be_focused()
    expect_sort(page, "ascending")
    assert not state.catalog.skills(Repository("acme", "alpha"))
    assert all(skill.starred for skill in state.catalog.skills())
    page.reload()
    expect_order(page, ["beta", "gamma"])
    sort.click()
    expect_sort(page, "descending")
    sort.click()
    expect_sort(page, "none")
    assert "sort" not in parse_qs(urlsplit(page.url).query)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert state.requests == []


def test_removal_failure_retry_and_last_repository(browser_page, web_environment, scan_result):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    page.goto(page.base_url)
    remove = page.get_by_role("button", name="Remove Acme/skills from catalog")
    page.route(
        "**/repositories/remove",
        lambda route: route.fulfill(
            status=500, body='<div role="alert">Could not remove the repository.</div>'
        ),
    )
    remove.click()
    dialog = page.get_by_role("dialog", name="Remove repository?")
    confirm = dialog.get_by_role("button", name="Remove repository", exact=True)
    confirm.click()
    expect(dialog.get_by_text("Could not remove the repository.")).to_be_visible()
    expect(confirm).to_be_enabled()
    expect(page.locator("#scan-feedback")).to_be_empty()
    expect(page.locator(".repository-row")).to_have_count(1)
    expect(remove).to_be_enabled()
    assert state.catalog.skills() == scan_result.skills
    page.unroute("**/repositories/remove")
    confirm.click()
    expect(page.get_by_role("heading", name="Repositories 0")).to_be_visible()
    expect(page.get_by_text("No repositories in your catalog yet.", exact=False)).to_be_visible()
    expect(page.get_by_role("dialog")).not_to_be_visible()
    expect(page.get_by_role("button", name="Sort by skills", exact=True)).to_be_focused()
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
    sort = page.get_by_role("button", name="Sort by skills", exact=True)
    with page.expect_request("**/fragments/repositories?*sort=asc*"):
        sort.click()
    expect(page.locator("#repositories")).to_have_attribute("aria-busy", "true")
    page.get_by_role("button", name="Remove acme/alpha from catalog").click()
    page.get_by_role("dialog", name="Remove repository?").get_by_role(
        "button", name="Remove repository", exact=True
    ).click()
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
    expect_sort(page, "descending")
    assert parse_qs(urlsplit(page.url).query)["sort"] == ["desc"]


@pytest.mark.parametrize("populated", [False, True], ids=["empty-catalog", "no-matches"])
def test_sort_header_stays_available_in_empty_results(
    browser_page, web_environment, scan_result, populated
):
    page, state = browser_page, web_environment
    if populated:
        seed(state, scan_result)
    page.goto(page.base_url + "/?q=missing&sort=desc")
    sort = page.get_by_role("button", name="Sort by skills", exact=True)
    expect(page.get_by_role("table", name="Repositories")).to_be_visible()
    expect_sort(page, "descending")
    expect(page.locator(".repository-row")).to_have_count(0)
    sort.press("Space")
    expect_sort(page, "none")
    expect(sort).to_be_focused()
    sort.press("Enter")
    expect_sort(page, "ascending")
    expect(sort).to_be_focused()
    page.get_by_role("searchbox").press("Escape")
    expect_sort(page, "ascending")
    if populated:
        expect_order(page, ["beta", "gamma", "alpha"])
    else:
        expect(
            page.get_by_text("No repositories in your catalog yet.", exact=False)
        ).to_be_visible()
    expect(page.get_by_role("searchbox")).to_be_focused()
    page.reload()
    expect_sort(page, "ascending")
    assert state.requests == []


def test_sort_failure_preserves_order_and_retry_updates_header(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    page.goto(page.base_url)
    page.route("**/fragments/repositories?*", lambda route: route.fulfill(status=500))
    sort = page.get_by_role("button", name="Sort by skills", exact=True)
    sort.press("Enter")
    expect(page.locator("#filter-error")).to_contain_text("Previous results are still shown")
    expect_order(page, ["alpha", "beta", "gamma"])
    expect_sort(page, "none")
    expect(sort).to_be_focused()
    page.unroute("**/fragments/repositories?*")
    page.get_by_role("button", name="Retry", exact=True).click()
    expect_order(page, ["beta", "gamma", "alpha"])
    expect_sort(page, "ascending")
    expect(page.locator("#filter-error")).to_be_empty()
    assert state.requests == []


def test_late_sort_cannot_replace_newer_header_or_steal_focus(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    page.goto(page.base_url)
    held = []

    def hold(route):
        held.append((route, route.fetch()))

    page.route("**/fragments/repositories?*sort=asc*", hold, times=1)
    sort = page.get_by_role("button", name="Sort by skills", exact=True)
    with page.expect_request("**/fragments/repositories?*sort=asc*"):
        sort.click()
    expect(page.locator("#repositories")).to_have_attribute("aria-busy", "true")
    sort.click()
    expect_sort(page, "descending")
    expect_order(page, ["alpha", "beta", "gamma"])
    field = page.get_by_role("searchbox")
    field.focus()
    assert len(held) == 1
    route, response = held.pop()
    route.fulfill(response=response)
    expect_sort(page, "descending")
    expect_order(page, ["alpha", "beta", "gamma"])
    expect(field).to_be_focused()
    assert state.requests == []


@pytest.mark.parametrize("width", [1360, 390, 320], ids=["desktop", "mobile", "narrow"])
def test_removal_dialog_cancel_focus_and_layout(browser_page, web_environment, scan_result, width):
    page, state = browser_page, web_environment
    # Long names must stay readable without making the mobile dialog overflow.
    repository = Repository("acme", "repository-with-a-long-name-" * 3)
    state.catalog.replace_repository(replace(scan_result, repository=repository))
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(page.base_url)
    row = page.locator(".repository-row").bounding_box()
    opener = page.get_by_role("button", name=f"Remove {repository.full_name} from catalog")
    dialog = page.get_by_role("dialog", name="Remove repository?")
    for dismissal in ("Escape", "Cancel", "Close removal dialog"):
        opener.press("Enter")
        expect(dialog.get_by_role("button", name="Cancel", exact=True)).to_be_focused()
        for key in ("Tab", "Shift+Tab"):
            for _ in range(4):
                page.keyboard.press(key)
                assert page.evaluate("document.activeElement.closest('dialog') !== null")
        expect(dialog.get_by_text(repository.full_name, exact=True)).to_be_visible()
        assert page.locator(".repository-row").bounding_box() == row
        assert dialog.evaluate("el => el.scrollWidth <= el.clientWidth")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        Path("test-results/pr-demo").mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"test-results/pr-demo/removal-dialog-{width}.png", full_page=True)
        if dismissal == "Escape":
            page.keyboard.press("Escape")
        else:
            dialog.get_by_role("button", name=dismissal, exact=True).click()
        expect(dialog).to_be_hidden()
        expect(opener).to_be_focused()
        assert state.catalog.skills(repository)
    assert state.requests == []


@pytest.mark.parametrize("dismiss_pending", [False, True], ids=["open", "dismissed"])
def test_pending_removal_suppresses_duplicates_and_reports_errors(
    browser_page, web_environment, scan_result, dismiss_pending
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    page.goto(page.base_url)
    held = []
    page.route("**/repositories/remove", lambda route: held.append(route))
    page.get_by_role("button", name="Remove Acme/skills from catalog").click()
    dialog = page.get_by_role("dialog", name="Remove repository?")
    dialog.get_by_role("button", name="Remove repository", exact=True).click()
    expect(dialog.get_by_role("button", name="Removing…")).to_be_disabled()
    expect(dialog.get_by_role("button", name="Close", exact=True)).to_be_visible()
    # A second form submission while the response is pending cannot send a second write.
    page.locator("#repository-remove-form").evaluate("form => form.requestSubmit()")
    assert len(held) == 1
    if dismiss_pending:
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
    held[0].abort()
    feedback = page.locator("#scan-feedback" if dismiss_pending else "#repository-remove-feedback")
    expect(feedback).to_contain_text("Could not confirm removal")
    assert state.catalog.skills() == scan_result.skills
    if not dismiss_pending:
        expect(dialog.get_by_role("button", name="Remove repository", exact=True)).to_be_enabled()
    assert state.requests == []


def test_removal_dialog_keeps_identity_and_restores_focus_after_scan_refresh(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    page.goto(page.base_url)
    state.scan_gate.clear()
    page.locator("#scan-github").click()
    page.get_by_role("textbox", name="GitHub URL").fill(scan_result.repository.url)
    page.get_by_role("button", name="Scan repository", exact=True).click()
    expect(page.locator('.job[data-state="running"]')).to_be_visible()
    page.get_by_role("button", name="Remove acme/alpha from catalog").click()
    dialog = page.get_by_role("dialog", name="Remove repository?")
    state.scan_gate.set()
    expect(page.get_by_role("heading", name="Repositories 4")).to_be_visible()
    expect(dialog.get_by_text("acme/alpha", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Remove acme/alpha from catalog")).to_be_focused()
    page.get_by_role("button", name="Remove acme/beta from catalog").click()
    expect(dialog.get_by_text("acme/beta", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Remove repository", exact=True).click()
    expect(dialog).to_be_hidden()
    assert not state.catalog.skills(Repository("acme", "beta"))
    assert state.catalog.skills(Repository("acme", "alpha"))


def test_successful_removal_with_failed_list_refresh_explains_result(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    page.goto(page.base_url)
    page.route("**/fragments/repositories?*", lambda route: route.fulfill(status=500))
    page.get_by_role("button", name="Remove Acme/skills from catalog").click()
    dialog = page.get_by_role("dialog", name="Remove repository?")
    dialog.get_by_role("button", name="Remove repository", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(page.locator("#scan-feedback")).to_contain_text("Acme/skills was removed")
    expect(page.locator("#filter-error")).to_contain_text("Previous results are still shown")
    assert state.catalog.repositories() == ()
    page.unroute("**/fragments/repositories?*")
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_role("heading", name="Repositories 0")).to_be_visible()
    assert state.requests == []
