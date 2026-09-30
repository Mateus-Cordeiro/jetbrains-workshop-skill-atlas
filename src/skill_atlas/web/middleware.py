"""Protect local HTTP requests and set browser response policies."""

import re

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from starlette.middleware.base import RequestResponseEndpoint


async def local_requests(request: Request, call_next: RequestResponseEndpoint) -> Response:
    host = request.headers.get("host", "")
    if not re.fullmatch(r"(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?", host):
        return HTMLResponse("Invalid Host", status_code=400)
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{host}"
    if (origin is not None and origin != expected) or (
        request.method == "POST"
        and (origin != expected or request.headers.get("X-Atlas-Request") != "1")
    ):
        return HTMLResponse("Cross-origin request rejected", status_code=403)
    response = await call_next(request)
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
            "style-src 'self'; "
            "img-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'",
        }
    )
    return response
