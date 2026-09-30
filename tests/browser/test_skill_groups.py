import re
from dataclasses import replace
from urllib.parse import urlencode

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"], allow_unix_socket=True)


def seed_groups(page, state, scan_result):
    state.catalog.replace_repository(scan_result)
    state.grouping_content = {
        "groups": [
            {"title": "Review code", "skill_ids": ["s1"]},
            {"title": "Prepare releases", "skill_ids": ["s1", "s2"]},
        ]
    }
    page.goto(page.base_url + "/groups/capabilities")
    page.get_by_role("button", name="Generate groups", exact=True).click()
    expect(page.get_by_role("heading", name="Review code", exact=True)).to_be_visible()


@pytest.mark.parametrize("width", [1360, 390])
def test_generate_overlapping_groups_select_source_history_and_topics(
    browser_page, web_environment, scan_result, width
):
    page, state = browser_page, web_environment
    page.set_viewport_size({"width": width, "height": 1000})
    state.catalog.replace_repository(scan_result)
    state.grouping_content = {
        "groups": [
            {"title": "Review code", "skill_ids": ["s1"]},
            {"title": "Prepare releases", "skill_ids": ["s1", "s2"]},
        ]
    }
    state.grouping_gate.clear()
    page.goto(page.base_url)
    page.get_by_role("link", name="Capabilities", exact=True).click()
    assert state.grouping_requests == []
    page.get_by_role("button", name="Generate groups", exact=True).focus()
    page.keyboard.press("Enter")
    expect(page.locator("#group-status")).to_contain_text("Generating capabilities")
    expect(page.get_by_role("button", name="Generate groups", exact=True)).to_be_disabled()
    state.grouping_gate.set()
    expect(page.get_by_role("heading", name="Review code", exact=True)).to_be_visible()
    expect(page.locator(".skill-group")).to_have_count(2)
    expect(page.get_by_role("link", name="code-review", exact=True)).to_have_count(2)
    expect(page.get_by_role("button", name="Regenerate groups", exact=True)).to_be_enabled()
    assert len(state.grouping_requests) == 1 and state.requests == []
    ids = page.locator("[id]").evaluate_all("(nodes) => nodes.map(n => n.id)")
    assert len(ids) == len(set(ids))
    page.get_by_role("link", name="code-review", exact=True).last.click()
    expect(page.locator(".markdown h1")).to_have_text("Review changes")
    expect(page.locator('.skill-link[aria-current="true"]')).to_have_count(2)
    page.get_by_role("button", name="Source", exact=True).click()
    expect(page.locator("#document-source")).to_contain_text("name: code-review")
    page.get_by_role("link", name="release-notes", exact=True).click()
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    page.go_back()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    page.reload()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    page.get_by_role("link", name="Similar skills to code-review").first.click()
    expect(page).to_have_url(re.compile("/similar\\?"))
    page.get_by_role("link", name="Back", exact=False).click()
    expect(page).to_have_url(re.compile("/groups/capabilities"))
    page.get_by_role("link", name="Topics", exact=True).click()
    expect(page.get_by_role("heading", name="No topics generated yet")).to_be_visible()
    assert len(state.grouping_requests) == 1
    page.get_by_role("button", name="Generate groups", exact=True).click()
    expect(page.get_by_role("heading", name="Review code", exact=True)).to_be_visible()
    assert len(state.grouping_requests) == 2
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_failure_retry_keeps_existing_groups_and_active_work_survives_navigation(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    seed_groups(page, state, scan_result)
    state.grouping_status = 500
    page.get_by_role("button", name="Regenerate groups", exact=True).click()
    expect(page.get_by_role("button", name="Retry generation")).to_be_visible()
    expect(page.get_by_role("heading", name="Review code", exact=True)).to_be_visible()
    state.grouping_status = 200
    state.grouping_gate.clear()
    page.get_by_role("button", name="Retry generation").click()
    expect(page.locator("#group-status")).to_contain_text("Generating capabilities")
    page.get_by_role("link", name="Repositories", exact=True).click()
    page.get_by_role("link", name="Capabilities", exact=True).click()
    expect(page.locator("#group-status")).to_contain_text("Generating capabilities")
    state.grouping_gate.set()
    expect(page.get_by_role("button", name="Regenerate groups", exact=True)).to_be_enabled()
    expect(page.locator("#group-status")).to_contain_text("Capabilities generated")


def test_catalog_updates_stale_selection_and_late_documents(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    seed_groups(page, state, scan_result)
    # Delay the first document in the browser, leaving the real document endpoint intact.
    held = []
    page.route(
        "**/fragments/document?**",
        lambda route: held.append(route) if "review%2F" in route.request.url else route.continue_(),
    )
    page.get_by_role("link", name="code-review", exact=True).first.click()
    page.get_by_role("link", name="release-notes", exact=True).click()
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    for route in held:
        route.continue_()
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")
    page.unroute("**/fragments/document?**")
    state.catalog.replace_repository(replace(scan_result, skills=scan_result.skills[:1]))
    page.reload()
    expect(page.get_by_text("The catalog has changed.", exact=False)).to_be_visible()
    expect(page.locator("#workspace")).to_have_attribute("data-selected-path", "")
    expect(page.get_by_role("link", name="release-notes", exact=True)).to_have_count(0)
    assert len(state.grouping_requests) == 1
    page.goto(
        page.base_url
        + "/groups/capabilities?"
        + urlencode(
            {
                "selected_repository": scan_result.repository.url,
                "selected_path": scan_result.skills[0].path,
            }
        )
    )
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    state.catalog.replace_repository(replace(scan_result, skills=()))
    page.reload()
    expect(page.get_by_role("heading", name="No saved skills")).to_be_visible()
    expect(page.get_by_role("button", name="Regenerate groups", exact=True)).to_be_disabled()
