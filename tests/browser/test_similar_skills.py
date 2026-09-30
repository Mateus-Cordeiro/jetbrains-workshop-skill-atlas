from dataclasses import replace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import expect

from skill_atlas.models import ScanResult

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


def similar_url(page, source, **params):
    return (
        page.base_url
        + "/similar?"
        + urlencode({"repository_url": source.repository.url, "skill_path": source.path, **params})
    )


def test_find_similar_from_metadata_scores_grouping_filter_and_history(
    browser_page, web_environment, similar_catalog
):
    page, state, fixture = browser_page, web_environment, similar_catalog
    state.document_status = 403
    page.goto(
        page.base_url
        + "/repository?"
        + urlencode(
            {"repository_url": fixture.source.repository.url, "skill_path": fixture.source.path}
        )
    )
    expect(page.get_by_role("heading", name="Could not load this skill")).to_be_visible()
    entry = page.locator(".skill-entry").filter(
        has=page.locator('.skill-link[aria-current="true"]')
    )
    entry.get_by_role("link", name="Find similar", exact=False).click()
    expect(page.get_by_role("heading", name="Similar to “code-review”")).to_be_visible()
    expect(page.locator(".similarity-score").first).to_have_text("Similarity: 100/100")
    expect(page.get_by_text("Same metadata · 3 locations")).to_be_visible()
    page.get_by_text("How similarity scores work").click()
    expect(page.get_by_text("They are not probabilities", exact=False)).to_be_visible()
    page.get_by_label("Other repositories only").check()
    page.get_by_role("button", name="Apply filter").click()
    expect(page.get_by_text("Same metadata · 2 locations")).to_be_visible()
    page.get_by_text("Same metadata · 2 locations").click()
    remote = page.locator('.skill-link[data-skill-path="review #?/SKILL.md"]')
    remote.focus()
    state.document_status = 200
    page.keyboard.press("Enter")
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    assert state.requests[-1].url.params["ref"] == fixture.remote.commit_sha
    assert state.requests[-1].url.path.endswith(fixture.remote.path)
    expect(page.get_by_role("heading", name="Similar to “code-review”")).to_be_visible()
    page.get_by_role("button", name="Source", exact=True).click()
    expect(page.locator("#document-source")).to_be_visible()
    page.locator('.skill-link[data-skill-path="alternative/SKILL.md"]').click()
    expect(page.locator(".document-toolbar strong")).to_have_text("patch-audit")
    page.go_back()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    page.reload()
    expect(remote).to_have_attribute("aria-current", "true")
    expect(page.get_by_label("Other repositories only")).to_be_checked()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert (
        page.locator(".skills-pane").bounding_box()["y"]
        < page.locator(".document-pane").bounding_box()["y"]
    )
    assert page.evaluate("localStorage.length") == 0
    page.screenshot(path="test-results/similar-mobile.png", full_page=True)


def test_similar_refresh_stale_commit_and_removed_selection(
    browser_page, web_environment, similar_catalog
):
    page, state, fixture = browser_page, web_environment, similar_catalog
    page.goto(similar_url(page, fixture.source, other_repositories="true"))
    updated = replace(fixture.alternative, commit_sha="d" * 40)
    state.catalog.replace_repository(ScanResult(updated.repository, updated.commit_sha, (updated,)))
    page.locator('.skill-link[data-skill-path="alternative/SKILL.md"]').click()
    expect(page.locator(".document-toolbar strong")).to_have_text("patch-audit")
    expect(page.locator(".document-options code")).to_have_text("dddddddd")
    assert urlsplit(page.url).path == "/similar"
    assert parse_qs(urlsplit(page.url).query)["skill_path"] == [fixture.source.path]
    state.catalog.replace_repository(ScanResult(updated.repository, "e" * 40, ()))
    # Selecting a now-missing candidate refreshes the matches and clears selection.
    page.locator('.skill-link[data-skill-path="alternative/SKILL.md"]').click()
    expect(page.get_by_role("heading", name="No similar skills found")).to_be_visible()
    expect(page.locator(".document-toolbar")).to_have_count(0)
    assert "selected_path" not in parse_qs(urlsplit(page.url).query)
    state.catalog.replace_repository(ScanResult(fixture.source.repository, "f" * 40, ()))
    page.get_by_role("button", name="Refresh results").click()
    expect(page.locator("#scan-feedback")).to_contain_text("starting skill is no longer")
    page.reload()
    expect(page.get_by_text("starting skill is no longer", exact=False)).to_be_visible()


def test_similar_retry_and_late_response_keep_source_and_current_match(
    browser_page, web_environment, similar_catalog
):
    page, state, fixture = browser_page, web_environment, similar_catalog
    page.goto(similar_url(page, fixture.source, other_repositories="true"))
    state.document_status = 403
    page.locator(".skill-link").first.click()
    expect(page.get_by_role("button", name="Retry", exact=True)).to_be_visible()
    state.document_status = 200
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    held = []
    page.route(
        "**/fragments/document?*",
        lambda route: (
            held.append(route) if "nested%2Fcopy" in route.request.url else route.continue_()
        ),
    )
    page.locator(".skill-link").first.click()
    expect(page.get_by_role("heading", name="Loading SKILL.md…")).to_be_visible()
    page.locator('.skill-link[data-skill-path="alternative/SKILL.md"]').click()
    expect(page.locator(".document-toolbar strong")).to_have_text("patch-audit")
    assert len(held) == 1
    held[0].fulfill(status=200, content_type="text/html", body="<h2>Obsolete match</h2>")
    expect(page.locator(".document-toolbar strong")).to_have_text("patch-audit")
    expect(page.get_by_text("Obsolete match")).to_have_count(0)
    expect(page.get_by_role("heading", name="Similar to “code-review”")).to_be_visible()


def test_late_similarity_refresh_does_not_overwrite_selection(browser_page, similar_catalog):
    page, fixture = browser_page, similar_catalog
    page.goto(similar_url(page, fixture.source, other_repositories="true"))
    held = []
    page.route("**/fragments/similar?*", lambda route: held.append(route))
    page.get_by_role("button", name="Refresh results").click()
    page.locator('.skill-link[data-skill-path="alternative/SKILL.md"]').click()
    expect(page.locator(".document-toolbar strong")).to_have_text("patch-audit")
    assert len(held) == 1
    held[0].fulfill(status=200, content_type="text/html", body="<h2>Obsolete results</h2>")
    expect(page.get_by_text("Obsolete results")).to_have_count(0)
    expect(page.locator(".document-toolbar strong")).to_have_text("patch-audit")
    page.screenshot(path="test-results/similar-desktop.png", full_page=True)


def test_similarity_refreshes_after_a_background_scan(
    browser_page, web_environment, similar_catalog
):
    page, state, fixture = browser_page, web_environment, similar_catalog
    state.scan_gate.clear()
    page.goto(similar_url(page, fixture.source, other_repositories="true"))
    response = page.request.post(
        page.base_url + "/scans",
        form={"repository_url": fixture.remote.repository.url},
        headers={"Origin": page.base_url, "X-Atlas-Request": "1"},
    )
    assert response.status == 202
    page.reload()
    expect(page.locator('.job[data-state="running"]')).to_be_visible()
    state.zero = True
    state.scan_gate.set()
    expect(page.get_by_role("heading", name="No similar skills found")).to_be_visible()
    expect(page.locator(".similar-result")).to_have_count(0)
