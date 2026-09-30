"""Catalog pages, HTMX fragments, and HTTP error adaptation."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from skill_atlas.application.documents import Documents, MissingSkill, StaleSkill
from skill_atlas.application.scan_jobs import QueueFull, ScanJobs
from skill_atlas.errors import CatalogError, RepositoryError
from skill_atlas.models import Repository
from skill_atlas.ports import CatalogReader
from skill_atlas.web.rendering import render


def url(path: str, **query: str) -> str:
    return path + ("?" + urlencode(query) if query else "")


def register_routes(
    app: FastAPI,
    catalog: CatalogReader,
    jobs: ScanJobs,
    documents: Callable[[], AbstractContextManager[Documents]],
    templates: Jinja2Templates,
) -> None:
    def page(request: Request, template: str, status: int = 200, **context: Any) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request, name=template, context=context, status_code=status
        )

    def error(request: Request, message: str, status: int, code: str) -> HTMLResponse:
        response = page(
            request,
            "fragments/error.html"
            if request.headers.get("HX-Request")
            else "pages/error-page.html",
            status,
            message=message,
            code=code,
        )
        response.headers["X-Error-Code"] = code
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        return error(
            request, "Required request parameters are missing or invalid.", 400, "invalid_input"
        )

    @app.exception_handler(ValueError)
    async def invalid_url(request: Request, exc: ValueError) -> Response:
        return error(
            request,
            "Use a repository URL like https://github.com/owner/repository.",
            400,
            "invalid_input",
        )

    @app.exception_handler(CatalogError)
    async def catalog_error(request: Request, exc: CatalogError) -> Response:
        return error(request, str(exc), 500, "catalog_error")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> Response:
        return page(
            request, "pages/home.html", repositories=catalog.repositories(), jobs=jobs.recent()
        )

    def repository_context(repository_url: str, skill_path: str) -> dict[str, Any]:
        repository = Repository.from_url(repository_url)
        skills = catalog.skills(repository)
        selected = next((skill for skill in skills if skill.path == skill_path), None)
        return {"repository": repository, "skills": skills, "selected": selected}

    @app.get("/repository", response_class=HTMLResponse)
    def repository_page(request: Request, repository_url: str, skill_path: str = "") -> Response:
        return page(
            request,
            "pages/repository.html",
            jobs=jobs.recent(),
            **repository_context(repository_url, skill_path),
        )

    @app.get("/fragments/repositories", response_class=HTMLResponse)
    def repositories_fragment(request: Request) -> Response:
        return page(request, "fragments/repositories.html", repositories=catalog.repositories())

    @app.get("/fragments/repository", response_class=HTMLResponse)
    def repository_fragment(
        request: Request, repository_url: str, skill_path: str = ""
    ) -> Response:
        return page(
            request, "fragments/workspace.html", **repository_context(repository_url, skill_path)
        )

    @app.get("/fragments/document", response_class=HTMLResponse)
    def document(
        request: Request, repository_url: str, skill_path: str, commit_sha: str
    ) -> Response:
        repository = Repository.from_url(repository_url)
        status = 200
        code = ""
        message = ""
        try:
            with documents() as service:
                loaded = service.load(repository, skill_path, commit_sha)
            return page(
                request, "fragments/document.html", document=loaded, rendered=render(loaded)
            )
        except MissingSkill as exc:
            status, code, message = 404, "missing_skill", str(exc)
        except StaleSkill as exc:
            status, code, message = 409, "stale_skill", str(exc)
        except RepositoryError as exc:
            status, code, message = 502, "document_error", str(exc)
        return page(
            request,
            "fragments/document-error.html",
            status,
            message=message,
            code=code,
            retry_url=url(
                "/fragments/document",
                repository_url=repository.url,
                skill_path=skill_path,
                commit_sha=commit_sha,
            ),
        )

    @app.post("/scans", response_class=HTMLResponse)
    async def submit_scan(request: Request) -> Response:
        body = await request.body()
        if len(body) > 8192:
            return error(request, "The scan request is too large.", 400, "invalid_input")
        form = parse_qs(body.decode("utf-8"), max_num_fields=8)
        repository = Repository.from_url(form.get("repository_url", [""])[0])
        try:
            job = jobs.submit(repository)
        except QueueFull as exc:
            return error(request, str(exc), 503, "queue_full")
        response = page(request, "fragments/jobs.html", 202, jobs=jobs.recent())
        response.headers["Location"] = f"/scans/{job.id}"
        return response

    @app.get("/scans/{job_id}", response_class=HTMLResponse)
    def scan_status(request: Request, job_id: str) -> Response:
        job = jobs.get(job_id)
        if job is None:
            return error(
                request,
                "Scan status is no longer available; refresh the catalog.",
                404,
                "missing_job",
            )
        return page(request, "fragments/job.html", job=job)
