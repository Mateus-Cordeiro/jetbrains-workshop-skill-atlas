"""Real loopback server and Chromium; GitHub is always an in-memory transport."""

import socket
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from urllib.parse import urlsplit

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright


@pytest.fixture
def browser_page(web_environment):
    state = web_environment
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(state.app, log_level="warning", timeout_graceful_shutdown=5)
    )
    thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 5
        while not server.started and monotonic() < deadline:
            sleep(0.01)
        assert server.started
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1360, "height": 1000})
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if urlsplit(route.request.url).hostname == "127.0.0.1"
                    else route.abort()
                ),
            )
            page = context.new_page()
            page.base_url = f"http://127.0.0.1:{port}"
            page.errors = []
            page.on("pageerror", lambda error: page.errors.append(str(error)))
            yield page
            Path("test-results").mkdir(exist_ok=True)
            page.screenshot(path="test-results/web-ui.png", full_page=True)
            assert not page.errors
            context.close()
            browser.close()
    finally:
        state.scan_gate.set()
        state.document_gate.set()
        state.grouping_gate.set()
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


@pytest.fixture
def scan_from_home(browser_page, web_environment):
    """Start a real scan, then return to the workspace before it completes."""

    def submit(repository):
        page, state = browser_page, web_environment
        return_url = page.url
        state.scan_gate.clear()
        try:
            page.goto(page.base_url)
            field = page.get_by_role("textbox", name="GitHub repository URL")
            if not field.is_visible():
                page.get_by_role("button", name="Add repository").click()
            field.fill(repository)
            page.get_by_role("button", name="Scan repository").click()
            expect(page.locator('.job[data-state="running"]')).to_be_visible()
            page.goto(return_url)
        finally:
            state.scan_gate.set()

    return submit
