"""Run with an installed wheel's Python from outside the source checkout."""

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

import skill_atlas
from skill_atlas.config import Settings
from skill_atlas.runtime import create_web_app

assert "site-packages" in str(Path(skill_atlas.__file__).resolve())
with TemporaryDirectory() as directory:
    with TestClient(
        create_web_app(Settings(Path(directory) / "catalog.sqlite3")),
        base_url="http://127.0.0.1",
    ) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Your skill library." in page.text
        for asset in ("htmx.min.js", "HTMX-LICENSE.txt", "app.js", "app.css"):
            response = client.get(f"/static/{asset}")
            assert response.status_code == 200 and response.content
print("Installed wheel serves its templates and static assets.")
