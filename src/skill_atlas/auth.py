"""Credential lookup. Tokens are returned to the HTTP client, never persisted."""

import os
import subprocess
from collections.abc import Mapping


def github_token(environment: Mapping[str, str] | None = None) -> str | None:
    environment = os.environ if environment is None else environment
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        token = environment.get(name, "").strip()
        if token:
            return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", "github.com"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None
