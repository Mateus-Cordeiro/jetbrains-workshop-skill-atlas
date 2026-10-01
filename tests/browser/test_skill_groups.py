from dataclasses import replace

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"], allow_unix_socket=True)


def seed(state, scan_result):
    state.catalog.replace_repository(scan_result)
    state.grouping_content_by_perspective = {
        "capabilities": {
            "groups": [
                {"title": "Review code", "skill_ids": ["s1"]},
                {"title": "Prepare releases", "skill_ids": ["s1", "s2"]},
            ]
        },
        "topics": {"groups": [{"title": "Software engineering", "skill_ids": ["s1", "s2"]}]},
    }


def generate(page):
    page.goto(page.base_url + "/explore")
    page.get_by_role("button", name="Generate groups", exact=True).click()
    expect(page.get_by_role("button", name="Review code, 1 skill")).to_be_visible()
    expect(page.locator("#skill-graph")).to_have_attribute("data-ready", "true")


@pytest.mark.parametrize("width", [1360, 390])
def test_graph_generation_toggle_overlap_keyboard_and_skill_navigation(
    browser_page, web_environment, scan_result, width
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    page.set_viewport_size({"width": width, "height": 1000})
    state.grouping_gate.clear()
    page.goto(page.base_url)

    def page_colors():
        return page.evaluate("""() => ['html', 'body', '.topbar', '.brand', '.brand-icon',
            '.local-label', 'footer'].map(selector => {
                const style = getComputedStyle(document.querySelector(selector));
                return [style.backgroundColor, style.color, style.borderBottomColor];
            })""")

    catalog_colors = page_colors()
    page.get_by_role("link", name="Explore", exact=True).click()
    page.wait_for_url(page.base_url + "/explore", wait_until="domcontentloaded")
    assert page_colors() == catalog_colors
    assert not state.grouping_requests
    button = page.get_by_role("button", name="Generate groups", exact=True)
    button.focus()
    expect(button).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("#group-status")).to_contain_text("Generating topics and capabilities")
    expect(button).to_be_disabled()
    state.grouping_gate.set()
    review = page.get_by_role("button", name="Review code, 1 skill")
    expect(review).to_be_visible()
    expect(page.locator("#skill-graph")).to_have_attribute("data-ready", "true")
    expect(page.locator("#skill-graph canvas").first).to_be_visible()
    review.focus()
    page.keyboard.press("Enter")
    expect(review).to_have_attribute("aria-expanded", "true")
    page.get_by_role("button", name="Prepare releases, 2 skills").click()
    expect(page.locator("#graph-count")).to_have_text("2 groups · 2 visible skills")
    # One graph skill connects to both groups, while both directory entries are usable.
    links = page.get_by_role("link", name="code-review Acme/skills", exact=True)
    expect(links).to_have_count(2)
    links.last.click()
    expect(page.locator(".markdown h1")).to_have_text("Review changes")
    assert page_colors() == catalog_colors
    page.get_by_role("button", name="Source", exact=True).click()
    expect(page.locator("#document-source")).to_contain_text("name: code-review")
    page.reload()
    page.get_by_role("link", name="Back to Explore", exact=False).click()
    expect(page.get_by_role("button", name="Review code, 1 skill")).to_have_attribute(
        "aria-expanded", "true"
    )
    page.get_by_role("button", name="Topics", exact=True).click()
    expect(page.get_by_role("button", name="Software engineering, 2 skills")).to_be_visible()
    page.get_by_role("button", name="Software engineering, 2 skills").click()
    expect(page.locator("#graph-count")).to_have_text("1 group · 2 visible skills")
    page.reload()
    expect(page.get_by_role("button", name="Topics", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(page.get_by_role("button", name="Software engineering, 2 skills")).to_have_attribute(
        "aria-expanded", "true"
    )
    assert page_colors() == catalog_colors
    page.go_back()
    expect(page.get_by_role("button", name="Capabilities", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    assert len(state.grouping_requests) == 2
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.get_by_role("link", name="Topics", exact=True).count() == 0


def test_canvas_pointer_hover_drag_expand_and_skill_link(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    # A single group is centered, so interaction exercises the real G6 canvas.
    state.grouping_content_by_perspective["capabilities"] = state.grouping_content_by_perspective[
        "topics"
    ]
    page.goto(page.base_url + "/explore")
    page.get_by_role("button", name="Generate groups", exact=True).click()
    group = page.get_by_role("button", name="Software engineering, 2 skills")
    expect(group).to_be_visible()
    expect(page.locator("#skill-graph")).to_have_attribute("data-ready", "true")
    box = page.locator("#skill-graph").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2 - 20
    page.mouse.move(x, y)
    expect(page.get_by_role("tooltip")).to_contain_text("Software engineering")
    page.mouse.down()
    page.mouse.move(x + 50, y - 45, steps=12)
    page.mouse.up()
    expect(group).to_have_attribute("aria-expanded", "false")
    # Moving away and back verifies the node's new position without invoking graph internals.
    page.mouse.move(box["x"] + 15, box["y"] + 80)
    expect(page.get_by_role("tooltip")).to_be_hidden()
    page.mouse.move(x + 50, y - 45)
    expect(page.get_by_role("tooltip")).to_contain_text("Software engineering")
    page.mouse.click(x + 50, y - 45)
    expect(group).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#graph-count")).to_have_text("1 group · 2 visible skills")
    page.get_by_role("button", name="Zoom in", exact=True).click()
    page.get_by_role("button", name="Zoom out", exact=True).click()
    page.get_by_role("button", name="Fit graph", exact=True).click()
    page.get_by_role("button", name="Reset layout", exact=True).click()
    page.get_by_role("link", name="release-notes Acme/skills", exact=True).click()
    expect(page.locator(".document-toolbar strong")).to_have_text("release-notes")


def test_failure_retry_retains_both_views_and_navigation_resumes_work(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    generate(page)
    state.grouping_content_by_perspective["capabilities"] = {
        "groups": [{"title": "Review code", "skill_ids": ["s1"]}]
    }
    page.get_by_role("button", name="Regenerate groups", exact=True).click()
    expect(page.get_by_role("button", name="Retry generation")).to_be_visible()
    expect(page.locator("#group-status")).to_contain_text("Capabilities generation failed")
    expect(page.locator("#group-status")).to_contain_text("missing 1 of 2 skills")
    expect(page.get_by_role("button", name="Review code, 1 skill")).to_be_visible()
    page.get_by_role("button", name="Topics", exact=True).click()
    expect(page.get_by_role("button", name="Software engineering, 2 skills")).to_be_visible()
    seed(state, scan_result)
    state.grouping_gate.clear()
    page.get_by_role("button", name="Retry generation").click()
    expect(page.locator("#group-status")).to_contain_text("Generating topics and capabilities")
    page.get_by_role("link", name="Repositories", exact=True).click()
    page.get_by_role("link", name="Explore", exact=True).click()
    expect(page.locator("#group-status")).to_contain_text("Generating topics and capabilities")
    state.grouping_gate.set()
    expect(page.get_by_role("button", name="Regenerate groups", exact=True)).to_be_enabled()
    expect(page.locator("#group-status")).to_contain_text("Topics and capabilities generated")


def test_catalog_changes_refresh_graph_and_empty_state(browser_page, web_environment, scan_result):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    generate(page)
    state.catalog.replace_repository(replace(scan_result, skills=scan_result.skills[:1]))
    page.reload()
    expect(page.locator("#graph-stale")).to_be_visible()
    page.get_by_role("button", name="Prepare releases, 1 skill").click()
    expect(page.get_by_role("link", name="release-notes", exact=False)).to_have_count(0)
    page.get_by_role("button", name="Topics", exact=True).click()
    expect(page.locator("#graph-stale")).to_be_visible()
    assert len(state.grouping_requests) == 2
    state.catalog.replace_repository(replace(scan_result, skills=()))
    page.reload()
    expect(page.get_by_role("heading", name="No saved skills")).to_be_visible()
    expect(page.get_by_role("button", name="Regenerate groups", exact=True)).to_be_disabled()


def test_reduced_motion_safe_metadata_and_unavailable_storage(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    attack = "<img src=x onerror=alert(1)>"
    state.grouping_content_by_perspective["capabilities"]["groups"][0]["title"] = attack
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script("Storage.prototype.setItem = () => { throw new Error('unavailable'); };")
    csp_errors = []
    page.on(
        "console",
        lambda message: (
            csp_errors.append(message.text) if "Content Security Policy" in message.text else None
        ),
    )
    page.goto(page.base_url + "/explore")
    page.get_by_role("button", name="Generate groups", exact=True).click()
    group = page.get_by_role("button", name=attack + ", 1 skill")
    expect(group).to_be_visible()
    expect(page.locator("#skill-graph")).to_have_attribute("data-ready", "true")
    group.click()
    expect(page.locator("#skill-graph")).to_have_attribute("data-ready", "true")
    expect(page.get_by_role("link", name="code-review Acme/skills", exact=True)).to_be_visible()
    assert page.locator("img").count() == 0
    assert page.locator('#skill-graph canvas[tabindex="1"]').count() == 0
    assert csp_errors == []
    for _ in range(3):
        page.get_by_role("button", name="Topics", exact=True).click()
        page.get_by_role("button", name="Capabilities", exact=True).click()
    expect(page.locator("#skill-graph")).to_have_attribute("data-ready", "true")
    expect(group).to_have_attribute("aria-expanded", "true")
    assert len(state.grouping_requests) == 2


def test_graph_library_failure_keeps_groups_and_skill_links_usable(
    browser_page, web_environment, scan_result
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    generate(page)
    page.route("**/static/g6.min.js", lambda route: route.abort())
    page.reload()
    expect(page.get_by_role("heading", name="Graph unavailable")).to_be_visible()
    group = page.get_by_role("button", name="Review code, 1 skill")
    group.click()
    page.get_by_role("link", name="code-review Acme/skills", exact=True).click()
    expect(page.locator(".markdown h1")).to_have_text("Review changes")


def test_web_scan_refreshes_both_graph_views(
    browser_page, web_environment, scan_result, scan_from_home
):
    page, state = browser_page, web_environment
    seed(state, scan_result)
    generate(page)
    state.zero = True
    scan_from_home(scan_result.repository.url)
    expect(page.get_by_role("heading", name="No saved skills")).to_be_visible()
    expect(page.get_by_role("button", name="Regenerate groups", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Topics", exact=True).click()
    expect(page.locator("#graph-count")).to_have_text("0 groups · 0 visible skills")
    assert len(state.grouping_requests) == 2
