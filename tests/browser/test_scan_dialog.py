from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


@pytest.mark.parametrize("width", [1360, 390, 320], ids=["desktop", "mobile", "narrow"])
def test_scan_dialog_focus_scope_and_catalog_stability(
    browser_page, web_environment, scan_result, width
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(page.base_url)
    row = page.locator(".repository-row").bounding_box()
    opener = page.locator("#scan-github")
    opener.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Scan repository or organization")
    field = dialog.get_by_role("textbox", name="GitHub URL")
    expect(field).to_be_focused()
    expect(dialog.get_by_role("button", name="Start scan")).to_be_visible()
    expect(dialog.get_by_text("https://github.com/organization", exact=True)).to_be_visible()
    assert page.locator(".repository-row").bounding_box() == row
    for _ in range(6):
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.closest('dialog') !== null")
    field.fill("https://github.com/Acme/")
    expect(dialog.get_by_role("button", name="Scan organization", exact=True)).to_be_visible()
    expect(dialog.locator("#scan-scope")).to_contain_text("excluding forks and archived")
    assert dialog.evaluate("el => el.scrollWidth <= el.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    Path("test-results").mkdir(exist_ok=True)
    page.screenshot(path=f"test-results/scan-dialog-{width}.png", full_page=True)
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(opener).to_be_focused()
    opener.click()
    expect(field).to_have_value("https://github.com/Acme/")
    field.fill("https://github.com/Acme/skills.git")
    expect(dialog.get_by_role("button", name="Scan repository", exact=True)).to_be_visible()
    expect(dialog.locator("#scan-scope")).to_be_hidden()
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(opener).to_be_focused()
    assert not state.requests


def test_invalid_url_stays_in_dialog_then_accepted_scan_closes_it(browser_page, web_environment):
    page, state = browser_page, web_environment
    page.goto(page.base_url)
    page.locator("#scan-github").click()
    dialog = page.get_by_role("dialog")
    field = dialog.get_by_role("textbox", name="GitHub URL")
    field.fill("https://example.com/owner/repository")
    dialog.get_by_role("button", name="Start scan").click()
    expect(dialog.locator("#scan-dialog-feedback")).to_contain_text("Use a repository URL")
    expect(field).to_have_attribute("aria-invalid", "true")
    expect(field).to_have_value("https://example.com/owner/repository")
    expect(page.locator("#scan-feedback")).to_be_empty()
    assert not state.requests
    field.fill("https://github.com/acme/skills")
    expect(dialog.locator("#scan-dialog-feedback")).to_be_empty()
    expect(field).not_to_have_attribute("aria-invalid", "true")
    state.scan_gate.clear()
    field.press("Enter")
    expect(dialog).to_be_hidden()
    expect(page.locator("#scan-github")).to_be_focused()
    expect(page.locator('.job[data-state="running"]')).to_be_visible()
    # An empty catalog refresh must not reopen the dismissed modal.
    state.zero = True
    state.scan_gate.set()
    expect(page.locator('.job[data-state="succeeded"]')).to_contain_text("No skills found")
    expect(dialog).to_be_hidden()
    page.reload()
    expect(dialog).to_be_hidden()


@pytest.mark.parametrize("failure", ["connection", "queue"])
def test_scan_submission_failures_can_be_retried_inside_dialog(
    browser_page, web_environment, failure
):
    page = browser_page
    page.goto(page.base_url)
    page.locator("#scan-github").click()
    dialog = page.get_by_role("dialog")
    field = dialog.get_by_role("textbox", name="GitHub URL")
    field.fill("https://github.com/acme/skills")

    def fail(route):
        if failure == "connection":
            route.abort()
        else:
            route.fulfill(
                status=503,
                content_type="text/html",
                body='<div class="error">The scan queue is full. Try again shortly.</div>',
            )

    page.route("**/scans", fail)
    dialog.get_by_role("button", name="Scan repository", exact=True).click()
    message = "Could not reach the server" if failure == "connection" else "queue is full"
    expect(dialog.locator("#scan-dialog-feedback")).to_contain_text(message)
    expect(page.locator("#scan-feedback")).to_be_empty()
    expect(dialog.get_by_role("button", name="Scan repository", exact=True)).to_be_enabled()
    expect(field).to_have_value("https://github.com/acme/skills")
    page.unroute("**/scans", fail)
    dialog.get_by_role("button", name="Scan repository", exact=True).click()
    expect(dialog).to_be_hidden()
    expect(page.locator('.job[data-state="succeeded"]')).to_be_visible()


def test_error_after_dismissing_pending_submission_is_visible(browser_page):
    page = browser_page
    held = []
    page.route("**/scans", lambda route: held.append(route))
    page.goto(page.base_url)
    page.locator("#scan-github").click()
    page.get_by_role("textbox", name="GitHub URL").fill("https://example.com/repo")
    page.get_by_role("button", name="Start scan").click()
    expect(page.locator("#repository-form")).to_have_attribute("aria-busy", "true")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_be_hidden()
    assert len(held) == 1
    held[0].continue_()
    expect(page.locator("#scan-feedback")).to_contain_text("Use a repository URL")
