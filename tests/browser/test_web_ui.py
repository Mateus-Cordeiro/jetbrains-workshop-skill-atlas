from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


def detail_url(page, result, path=""):
    return (
        page.base_url
        + "/repository?"
        + urlencode({"repository_url": result.repository.url, "skill_path": path})
    )


@pytest.mark.parametrize("width", [1360, 390], ids=["desktop", "mobile"])
def test_descriptions_expand_independently_without_selecting_or_fetching(
    browser_page, web_environment, scan_result, width
):
    page, state = browser_page, web_environment
    description = "Review changes carefully for correctness and maintainability. " * 12
    description += "<img src=x onerror=window.pwned=true> Final description text."
    first = replace(scan_result.skills[0], description=description)
    duplicate = replace(first, path="z-copy/SKILL.md")
    short = replace(scan_result.skills[1], description="Short description.")
    state.catalog.replace_repository(replace(scan_result, skills=(first, duplicate, short)))
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(detail_url(page, scan_result))
    cards = page.locator(".skill-item")
    text = cards.nth(0).locator(".skill-description")
    toggle = cards.nth(0).get_by_role("button", name="Show more description for code-review")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(cards.nth(2).get_by_role("button")).to_have_count(0)
    expect(page.locator(".skills-list code, .skills-list img")).to_have_count(0)
    assert first.path not in page.locator(".skills-list").inner_text()
    assert text.evaluate(
        "el => el.clientHeight === 2 * parseFloat(getComputedStyle(el).lineHeight)"
    )
    assert text.evaluate("el => el.scrollHeight > el.clientHeight")
    original_url = page.url
    Path("test-results").mkdir(exist_ok=True)
    page.screenshot(path=f"test-results/descriptions-collapsed-{width}.png", full_page=True)

    toggle.focus()
    page.keyboard.press("Enter")
    toggle = cards.nth(0).get_by_role("button", name="Show less description for code-review")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(text).to_have_text(description)
    assert text.evaluate("el => el.scrollHeight === el.clientHeight")
    expect(cards.nth(1).get_by_role("button")).to_have_attribute("aria-expanded", "false")
    expect(page.get_by_text("Select a skill to view its SKILL.md")).to_be_visible()
    assert page.url == original_url
    assert not state.requests
    assert page.evaluate("window.pwned") is None
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=f"test-results/descriptions-expanded-{width}.png", full_page=True)

    # Space collapses the focused control without navigating or selecting a skill.
    page.keyboard.press("Space")
    expect(cards.nth(0).get_by_role("button")).to_have_attribute("aria-expanded", "false")
    assert text.evaluate("el => el.scrollHeight > el.clientHeight")
    cards.nth(1).locator(".skill-link").click()
    expect(page.locator(".document-toolbar code")).to_have_text(duplicate.path)
    expect(cards.nth(1).locator(".skill-link")).to_have_attribute("aria-current", "true")
    reads = len(state.requests)
    cards.nth(0).get_by_role("button").click()
    expect(cards.nth(1).locator(".skill-link")).to_have_attribute("aria-current", "true")
    assert len(state.requests) == reads


def test_description_controls_follow_pane_width_and_refreshed_skill_lists(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    description = (
        "Review code changes for correctness, maintainability, tests, and documentation. " * 2
    ).strip()
    state.catalog.replace_repository(
        replace(scan_result, skills=(replace(scan_result.skills[0], description=description),))
    )
    page.goto(detail_url(page, scan_result))
    toggle = page.locator(".description-toggle").first
    expect(toggle).to_be_visible()
    page.set_viewport_size({"width": 600, "height": 1000})
    expect(toggle).to_be_hidden()
    page.set_viewport_size({"width": 1360, "height": 1000})
    expect(toggle).to_be_visible()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")

    state.source = f"---\nname: refreshed\ndescription: {description}\n---\n# Refreshed\n"
    page.get_by_role("button", name="Rescan repository").click()
    expect(page.locator(".skill-link").first).to_contain_text("refreshed")
    expect(toggle).to_be_visible()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    reads = len(state.requests)
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    assert page.locator(".skill-description").first.evaluate(
        "el => el.scrollHeight === el.clientHeight"
    )
    assert len(state.requests) == reads
    page.reload()
    expect(toggle).to_have_attribute("aria-expanded", "false")


def test_selection_source_keyboard_history_and_mobile(browser_page, web_environment, scan_result):
    page = browser_page
    web_environment.catalog.replace_repository(scan_result)
    page.goto(page.base_url)
    expect(page.get_by_role("link", name="Acme/skills")).to_be_visible()
    page.get_by_role("link", name="Acme/skills").click()
    expect(page.get_by_text("Select a skill to view its SKILL.md")).to_be_visible()
    first = page.locator(".skill-link").first
    first.focus()
    page.keyboard.press("Enter")
    expect(page.locator(".markdown h1")).to_have_text("Review changes")
    expect(first).to_have_attribute("aria-current", "true")
    reads = len(web_environment.requests)
    page.get_by_role("button", name="Source", exact=True).click()
    expect(page.locator("#document-source")).to_contain_text("name: code-review")
    expect(page.locator("#document-preview")).to_be_hidden()
    page.get_by_role("button", name="Preview", exact=True).click()
    assert len(web_environment.requests) == reads
    page.locator(".skill-link").nth(1).click()
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    page.go_back()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    page.reload()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    assert page.evaluate("localStorage.length") == 0
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator(".document-toolbar strong")).to_be_visible()
    assert (
        page.locator(".skills-pane").bounding_box()["y"]
        < page.locator(".document-pane").bounding_box()["y"]
    )


def test_scan_queue_failure_retry_and_zero_results(browser_page, web_environment, scan_result):
    page, state = browser_page, web_environment
    page.goto(page.base_url)
    state.scan_gate.clear()
    page.get_by_role("textbox", name="GitHub repository URL").fill(scan_result.repository.url)
    page.get_by_role("button", name="Scan repository").click()
    expect(page.locator('.job[data-state="running"]')).to_be_visible()
    page.get_by_role("textbox", name="GitHub repository URL").fill("https://github.com/acme/other")
    page.get_by_role("button", name="Scan repository").click()
    expect(page.locator('.job[data-state="queued"]')).to_be_visible()
    state.scan_gate.set()
    expect(page.locator('.job[data-state="succeeded"]')).to_have_count(2)
    expect(page.locator(".repository-row")).to_have_count(2)
    page.goto(detail_url(page, scan_result, scan_result.skills[0].path))
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    state.scan_status = 404
    page.get_by_role("button", name="Rescan repository").click()
    expect(page.locator('.job[data-state="failed"]')).to_be_visible()
    expect(page.locator(".skill-link")).to_have_count(2)
    state.scan_status = 200
    state.zero = True
    page.get_by_role("button", name="Retry scan").click()
    expect(
        page.locator("#workspace").get_by_role("heading", name="No skills found")
    ).to_be_visible()
    expect(page.locator("#document")).to_have_count(0)
    page.get_by_role("link", name="All repositories").click()
    expect(page.locator(".repository-row")).to_have_count(1)


def test_retrieval_error_retry_stale_selection_and_safe_preview(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    state.catalog.replace_repository(scan_result)
    state.document_status = 403
    page.goto(detail_url(page, scan_result, scan_result.skills[0].path))
    expect(page.get_by_role("heading", name="Could not load this skill")).to_be_visible()
    state.document_status = 200
    state.source += "\n<script>window.pwned=true</script>\n![image](https://evil.test/pixel)\n"
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.locator(".markdown h1")).to_have_text("Review changes")
    assert page.evaluate("window.pwned") is None
    expect(page.locator(".markdown img")).to_have_count(0)
    state.catalog.replace_repository(
        replace(
            scan_result,
            commit_sha="d" * 40,
            skills=tuple(replace(skill, commit_sha="d" * 40) for skill in scan_result.skills),
        )
    )
    page.locator(".skill-link").nth(1).click()
    expect(page.locator(".document-options code")).to_have_text("dddddddd")
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")


def test_late_document_response_cannot_replace_new_selection(
    browser_page, web_environment, scan_result
):
    page = browser_page
    web_environment.catalog.replace_repository(scan_result)
    held = []

    def delay_first(route):
        if "review%2FSKILL.md" in route.request.url:
            held.append(route)
        else:
            route.continue_()

    page.route("**/fragments/document?*", delay_first)
    page.goto(detail_url(page, scan_result))
    page.locator(".skill-link").first.click()
    expect(page.get_by_role("heading", name="Loading SKILL.md…")).to_be_visible()
    page.locator(".skill-link").nth(1).click()
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    assert len(held) == 1
    held[0].fulfill(status=200, content_type="text/html", body="<h2>Obsolete response</h2>")
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    expect(page.get_by_text("Obsolete response")).to_have_count(0)


def test_delayed_workspace_refresh_preserves_new_selection(
    browser_page, web_environment, scan_result
):
    page = browser_page
    web_environment.catalog.replace_repository(scan_result)
    held = []
    page.route("**/fragments/repository?*", lambda route: held.append(route))
    page.goto(detail_url(page, scan_result, scan_result.skills[0].path))
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    page.evaluate("""() => { htmx.ajax('GET', '/fragments/repository?' + location.search.slice(1),
        {target: '#workspace', swap: 'outerHTML'}); }""")
    page.locator(".skill-link").nth(1).click()
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    assert len(held) == 1
    held[0].fulfill(status=200, content_type="text/html", body="<h2>Obsolete workspace</h2>")
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    expect(page.get_by_text("Obsolete workspace")).to_have_count(0)


def submit_repository(page, repository):
    page.get_by_role("textbox", name="GitHub repository URL").fill(repository)
    page.get_by_role("button", name="Scan repository").click()


def test_success_notices_expire_without_hiding_active_scans(browser_page, web_environment):
    page, state = browser_page, web_environment
    page.clock.install()
    page.goto(page.base_url)
    state.scan_gate.clear()
    submit_repository(page, "https://github.com/acme/skills")
    expect(page.locator('.job[data-state="running"]')).to_be_visible()
    page.clock.fast_forward(6000)
    expect(page.locator('.job[data-state="running"]')).to_be_visible()
    expect(page.get_by_role("button", name="Dismiss scan result", exact=False)).to_have_count(0)
    state.scan_gate.set()
    success = page.locator('.job[data-state="succeeded"]')
    expect(success).to_be_visible()
    expect(page.locator(".repository-row")).to_have_count(1)
    page.clock.fast_forward(3000)
    expect(success).to_be_visible()
    state.scan_gate.clear()
    submit_repository(page, "https://github.com/acme/other")
    expect(page.locator('.job[data-state="running"]')).to_be_visible()
    # Replacing the scan panel must not restart a successful notice's timer.
    page.clock.fast_forward(2500)
    expect(success).to_have_count(0)
    expect(page.locator('.job[data-state="running"]')).to_be_visible()
    page.reload()
    expect(success).to_have_count(0)
    expect(page.locator('.job[data-state="running"]')).to_be_visible()
    state.scan_gate.set()
    expect(success).to_have_count(1)
    expect(page.locator(".repository-row")).to_have_count(2)
    page.get_by_role("button", name="Dismiss scan result", exact=False).click()
    expect(success).to_have_count(0)


def test_failed_scan_notices_wait_for_dismissal_and_stay_dismissed(browser_page, web_environment):
    page, state = browser_page, web_environment
    page.clock.install()
    state.scan_status = 404
    page.goto(page.base_url)
    submit_repository(page, "https://github.com/acme/skills")
    failed = page.locator('.job[data-state="failed"]')
    expect(failed).to_be_visible()
    page.clock.fast_forward(10000)
    expect(failed).to_be_visible()
    expect(page.get_by_role("button", name="Retry scan")).to_be_visible()
    page.get_by_role("button", name="Dismiss scan result", exact=False).click()
    expect(failed).to_have_count(0)
    page.reload()
    expect(failed).to_have_count(0)
    state.scan_status = 200
    submit_repository(page, "https://github.com/acme/skills")
    expect(page.locator('.job[data-state="succeeded"]')).to_be_visible()
    expect(failed).to_have_count(0)
