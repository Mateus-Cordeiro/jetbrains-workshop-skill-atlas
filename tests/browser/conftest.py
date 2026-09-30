"""Real loopback server and Chromium; GitHub is always an in-memory transport."""

import socket
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from urllib.parse import urlsplit

import pytest
import uvicorn
from playwright.sync_api import sync_playwright


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
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()
