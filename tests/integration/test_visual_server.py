"""Exercise the standalone Playwright fixture against the real Web application."""

import json
import os
import selectors
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])
ROOT = Path(__file__).resolve().parents[2]


def reply(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=15), "Visual fixture did not respond"
    line = process.stdout.readline()
    assert line, "Visual fixture exited before responding"
    return json.loads(line)


@pytest.mark.parametrize("shutdown", ["command", "eof"])
def test_visual_server_isolates_catalog_and_credentials_and_cleans_up(tmp_path, shutdown):
    developer_catalog = tmp_path / "developer.sqlite3"
    developer_catalog.write_text("Do not touch the inherited catalog")
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.browser.visual.server"],
        cwd=ROOT,
        env={
            **os.environ,
            "SKILL_ATLAS_DB": str(developer_catalog),
            "GH_TOKEN": "unused-test-canary",
            "GITHUB_TOKEN": "unused-test-canary",
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready = reply(process)
        catalog = Path(ready["catalogPath"])
        assert catalog != developer_catalog and catalog.is_file()
        with httpx.Client(base_url=ready["baseURL"], trust_env=False) as client:
            home = client.get("/")
            assert home.status_code == 200
            assert "Acme/skills" in home.text and "other/tools" in home.text
            assert (
                client.post(
                    "/__test__/scan",
                    headers={"Origin": ready["baseURL"], "X-Atlas-Request": "1"},
                ).status_code
                == 404
            )
            process.stdin.write('{"command":"requests"}\n')
            process.stdin.flush()
            assert reply(process) == {"paths": []}
            process.stdin.write('{"command":"scan","status":200,"blocked":true}\n')
            process.stdin.flush()
            assert reply(process) == {"ok": True}
            response = client.post(
                "/scans",
                data={"repository_url": "https://github.com/acme/skills"},
                headers={"Origin": ready["baseURL"], "X-Atlas-Request": "1"},
            )
            assert response.status_code == 202
            # Stopping while a real scan is held must release it before worker shutdown.
            if shutdown == "command":
                process.stdin.write('{"command":"stop"}\n')
                process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=15)
        assert process.returncode == 0, process.stderr.read()
        assert not catalog.parent.exists()
        assert developer_catalog.read_text() == "Do not touch the inherited catalog"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()
