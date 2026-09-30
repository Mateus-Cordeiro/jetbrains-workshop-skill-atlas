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


@pytest.mark.parametrize("entry_page", ["home", "repository"])
def test_similarity_from_filtered_catalog_preserves_return_context(
    browser_page, web_environment, similar_catalog, entry_page
):
    page, fixture = browser_page, similar_catalog
    start = page.base_url
    if entry_page == "repository":
        start += "/repository?" + urlencode({"repository_url": fixture.source.repository.url})
    page.goto(start)
    page.get_by_role("searchbox").fill("code-review")
    expect(page.get_by_role("status")).to_have_text(
        "4 matching skills across 2 repositories" if entry_page == "home" else "2 of 3 skills"
    )
    expect(page.get_by_text("patch-audit", exact=True)).to_have_count(0)
    assert not web_environment.requests
    page.locator('.similar-link[href*="skill_path=review%2FSKILL.md"]').click()
    expect(page.get_by_role("heading", name="Similar to “code-review”")).to_be_visible()
    expect(page.get_by_role("searchbox")).to_have_count(0)
    expect(page.locator(".description-toggle")).to_have_count(0)
    # The catalog query is return context, never a restriction on candidates.
    page.get_by_role("link", name="patch-audit", exact=False).click()
    expect(page.locator(".document-toolbar strong")).to_have_text("patch-audit")
    assert parse_qs(urlsplit(page.url).query)["q"] == ["code-review"]
    page.reload()
    expect(page.locator('.skill-link[aria-current="true"]')).to_contain_text("patch-audit")
    page.get_by_role("link", name="Starting skill", exact=False).click()
    expect(page.get_by_role("searchbox")).to_have_value("code-review")
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    expect(page.get_by_role("status")).to_have_text("2 of 3 skills")
    page.go_back()
    expect(page.get_by_role("heading", name="Similar to “code-review”")).to_be_visible()
    expect(page.locator('.skill-link[aria-current="true"]')).to_contain_text("patch-audit")


def test_similarity_selection_distinguishes_repositories_with_the_same_path(
    browser_page, web_environment, similar_catalog
):
    page, state, fixture = browser_page, web_environment, similar_catalog
    shared_path = ".agents/skills/review/SKILL.md"
    remote = replace(fixture.remote, path=shared_path)
    state.catalog.replace_repository(
        ScanResult(remote.repository, remote.commit_sha, (remote, fixture.alternative))
    )
    page.goto(similar_url(page, fixture.source, q="code-review"))
    page.get_by_text("Same metadata · 2 locations").click()
    link = page.locator(
        f'.skill-link[data-skill-path="{shared_path}"]'
        f'[data-skill-repository="{remote.repository.url}"]'
    )
    link.click()
    expect(page.locator(".document-toolbar strong")).to_have_text("code-review")
    selected = page.locator('.skill-link[aria-current="true"]')
    expect(selected).to_have_count(1)
    expect(selected).to_have_attribute("data-skill-repository", remote.repository.url)
    local = page.locator(
        f'.skill-link[data-skill-path="{shared_path}"]'
        f'[data-skill-repository="{fixture.source.repository.url}"]'
    )
    background = "el => getComputedStyle(el).backgroundColor"
    assert selected.evaluate(background) != local.evaluate(background)
    assert state.requests[-1].url.path.startswith("/repos/other/skills/contents/")
    assert state.requests[-1].url.params["ref"] == remote.commit_sha
    page.reload()
    expect(selected).to_have_count(1)
    expect(selected).to_have_attribute("data-skill-repository", remote.repository.url)
    expect(link).to_be_visible()


def test_similarity_link_keeps_query_while_filter_response_is_pending(
    browser_page, similar_catalog
):
    page, source = browser_page, similar_catalog.source
    page.goto(page.base_url + "/repository?" + urlencode({"repository_url": source.repository.url}))
    held = []
    page.route("**/fragments/skills?*", lambda route: held.append(route))
    with page.expect_request("**/fragments/skills?*"):
        page.get_by_role("searchbox").fill("code-review")
    expect(page.locator("#skill-results")).to_have_attribute("aria-busy", "true")
    page.locator('.similar-link[href*="skill_path=review%2FSKILL.md"]').click()
    expect(page.get_by_role("heading", name="Similar to “code-review”")).to_be_visible()
    assert parse_qs(urlsplit(page.url).query)["q"] == ["code-review"]
    assert len(held) == 1
    page.get_by_role("link", name="Starting skill", exact=False).click()
    expect(page.get_by_role("searchbox")).to_have_value("code-review")
    expect(page.get_by_role("status")).to_have_text("2 of 3 skills")


def test_find_similar_from_metadata_score_bars_grouping_and_history(
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
    entry = page.locator(".skill-item").filter(has=page.locator('.skill-link[aria-current="true"]'))
    entry.get_by_role("link", name="Find similar", exact=False).click()
    expect(page.get_by_role("heading", name="Similar to “code-review”")).to_be_visible()
    expect(page.get_by_role("meter").first).to_have_attribute("value", "100")
    expect(page.get_by_role("meter").first).to_have_attribute("aria-valuetext", "100% similarity")
    expect(page.locator(".score-value").first).to_have_text("100%")
    expect(page.get_by_text(fixture.source.description, exact=True)).to_have_count(0)
    expect(page.get_by_text("Shared terms:", exact=False)).to_have_count(0)
    for removed in ("Refresh results", "Apply filter"):
        expect(page.get_by_role("button", name=removed)).to_have_count(0)
    expect(page.get_by_label("Other repositories only")).to_have_count(0)
    expect(page.get_by_text("Same metadata · 3 locations")).to_be_visible()
    page.get_by_text("How similarity scores work").click()
    expect(page.get_by_text("They are not probabilities", exact=False)).to_be_visible()
    page.get_by_text("Same metadata · 3 locations").click()
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
    assert "other_repositories" not in page.url
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
    state.catalog.replace_repository(
        ScanResult(fixture.source.repository, fixture.source.commit_sha, (fixture.source,))
    )
    page.goto(similar_url(page, fixture.source, q="code-review"))
    updated = replace(fixture.alternative, commit_sha="d" * 40)
    state.catalog.replace_repository(ScanResult(updated.repository, updated.commit_sha, (updated,)))
    page.locator('.skill-link[data-skill-path="alternative/SKILL.md"]').click()
    expect(page.locator(".document-toolbar strong")).to_have_text("patch-audit")
    expect(page.locator(".document-options code")).to_have_text("dddddddd")
    assert urlsplit(page.url).path == "/similar"
    assert parse_qs(urlsplit(page.url).query)["skill_path"] == [fixture.source.path]
    assert parse_qs(urlsplit(page.url).query)["q"] == ["code-review"]
    state.catalog.replace_repository(ScanResult(updated.repository, "e" * 40, ()))
    # Selecting a now-missing candidate refreshes the matches and clears selection.
    page.locator('.skill-link[data-skill-path="alternative/SKILL.md"]').click()
    expect(page.get_by_role("heading", name="No similar skills found")).to_be_visible()
    expect(page.locator(".document-toolbar")).to_have_count(0)
    assert "selected_path" not in parse_qs(urlsplit(page.url).query)
    copy = replace(fixture.source, path="copy/SKILL.md")
    state.catalog.replace_repository(
        ScanResult(copy.repository, copy.commit_sha, (fixture.source, copy))
    )
    page.reload()
    state.catalog.replace_repository(ScanResult(fixture.source.repository, "f" * 40, ()))
    page.locator('.skill-link[data-skill-path="copy/SKILL.md"]').click()
    expect(page.locator("#scan-feedback")).to_contain_text("starting skill is no longer")
    page.reload()
    expect(page.get_by_text("starting skill is no longer", exact=False)).to_be_visible()


def test_similar_retry_and_late_response_keep_source_and_current_match(
    browser_page, web_environment, similar_catalog
):
    page, state, fixture = browser_page, web_environment, similar_catalog
    page.goto(similar_url(page, fixture.source))
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
            held.append(route) if ".agents%2Fskills" in route.request.url else route.continue_()
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


def test_late_similarity_refresh_does_not_overwrite_selection(
    browser_page, web_environment, similar_catalog
):
    page, fixture = browser_page, similar_catalog
    page.goto(similar_url(page, fixture.source))
    held = []
    page.route("**/fragments/similar?*", lambda route: held.append(route))
    updated = tuple(
        replace(skill, commit_sha="d" * 40)
        for skill in web_environment.catalog.skills(fixture.source.repository)
    )
    web_environment.catalog.replace_repository(
        ScanResult(fixture.source.repository, "d" * 40, updated)
    )
    with page.expect_request("**/fragments/similar?*"):
        page.locator(".skill-link").first.click()
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
    page.goto(similar_url(page, fixture.source, q="code-review"))
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
    expect(page.locator(".similar-result")).to_have_count(1)
    expect(page.get_by_text("other/skills", exact=True)).to_have_count(0)
    expect(page.locator(".result-repository")).to_have_text("Acme/skills")
    assert urlsplit(page.url).path == "/similar"
    assert parse_qs(urlsplit(page.url).query)["q"] == ["code-review"]


def test_similarity_bars_show_low_medium_and_high_scores(
    browser_page, web_environment, similar_catalog
):
    page, state, fixture = browser_page, web_environment, similar_catalog
    medium = replace(
        fixture.alternative,
        path="medium/SKILL.md",
        name="patch-review",
        description="Review code patches for correctness, bugs, and maintainability.",
    )
    low = replace(fixture.remote, path="low/SKILL.md", description="Bake sourdough bread.")
    state.catalog.replace_repository(
        ScanResult(
            fixture.remote.repository,
            fixture.remote.commit_sha,
            (*state.catalog.skills(fixture.remote.repository), medium, low),
        )
    )
    page.goto(similar_url(page, fixture.source))
    for skill, minimum, maximum, colour in (
        (low, 0, 39, "#a34332"),
        (medium, 40, 69, "#946200"),
        (fixture.alternative, 70, 100, "#29634e"),
    ):
        card = page.locator(".similar-result").filter(
            has=page.locator(f'.skill-link[data-skill-path="{skill.path}"]')
        )
        meter = card.get_by_role("meter")
        score = int(meter.get_attribute("value"))
        assert minimum <= score <= maximum
        expect(meter).to_have_attribute("min", "0")
        expect(meter).to_have_attribute("max", "100")
        expect(card.locator(".score-value")).to_have_text(f"{score}%")
        assert (
            meter.evaluate("el => getComputedStyle(el).getPropertyValue('--score-color')") == colour
        )
        expect(card.get_by_text(skill.description, exact=True)).to_have_count(0)
        # The percentage sits inside the meter, including when the fill is short.
        track = card.locator(".score-track").bounding_box()
        label = card.locator(".score-value span").bounding_box()
        assert track["x"] <= label["x"] < label["x"] + label["width"] <= track["x"] + track["width"]
    page.set_viewport_size({"width": 1360, "height": 1400})
    page.screenshot(path="test-results/similar-colours.png", full_page=True)
