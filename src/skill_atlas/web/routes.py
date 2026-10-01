"""Catalog pages, HTMX fragments, and HTTP error adaptation."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from skill_atlas.application.catalog import BrowseCatalog
from skill_atlas.application.documents import Documents, MissingSkill, StaleSkill
from skill_atlas.application.scan_jobs import QueueFull, ScanJobs
from skill_atlas.application.similarity import MissingSimilaritySource, SimilarSkills
from skill_atlas.errors import CatalogError, RepositoryError
from skill_atlas.models import Repository, scan_target
from skill_atlas.web.rendering import render


def url(path: str, **query: str) -> str:
    return path + ("?" + urlencode(query) if query else "")


def register_routes(
    app: FastAPI,
    browse: BrowseCatalog,
    jobs: ScanJobs,
    documents: Callable[[], AbstractContextManager[Documents]],
    similarity: SimilarSkills,
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
    def home(request: Request, q: str = "") -> Response:
        return page(request, "pages/home.html", view=browse.home(q), q=q, jobs=jobs.recent())

    def repository_context(repository_url: str, skill_path: str, q: str) -> dict[str, Any]:
        repository = Repository.from_url(repository_url)
        view = browse.repository(repository, q, skill_path)
        return {
            "repository": repository,
            "skills": view.skills,
            "matches": view.matches,
            "selected": view.selected,
            "q": q,
        }

    @app.get("/repository", response_class=HTMLResponse)
    def repository_page(
        request: Request, repository_url: str, skill_path: str = "", q: str = ""
    ) -> Response:
        return page(
            request,
            "pages/repository.html",
            jobs=jobs.recent(),
            **repository_context(repository_url, skill_path, q),
        )

    @app.get("/fragments/repositories", response_class=HTMLResponse)
    def repositories_fragment(request: Request, q: str = "") -> Response:
        return page(request, "fragments/repositories.html", view=browse.home(q), q=q)

    @app.get("/fragments/repository-skills", response_class=HTMLResponse)
    def repository_skills(request: Request, repository_url: str, q: str = "") -> Response:
        return page(
            request, "fragments/repository-skills.html", **repository_context(repository_url, "", q)
        )

    @app.get("/fragments/skills", response_class=HTMLResponse)
    def skills_fragment(
        request: Request, repository_url: str, q: str = "", skill_path: str = ""
    ) -> Response:
        return page(
            request, "fragments/skills.html", **repository_context(repository_url, skill_path, q)
        )

    @app.get("/fragments/repository", response_class=HTMLResponse)
    def repository_fragment(
        request: Request, repository_url: str, skill_path: str = "", q: str = ""
    ) -> Response:
        return page(
            request, "fragments/workspace.html", **repository_context(repository_url, skill_path, q)
        )

    @app.get("/similar", response_class=HTMLResponse)
    @app.get("/fragments/similar", response_class=HTMLResponse)
    def similar(
        request: Request,
        repository_url: str,
        skill_path: str,
        selected_repository: str = "",
        selected_path: str = "",
        q: str = "",
        return_to: str = "",
    ) -> Response:
        repository = Repository.from_url(repository_url)
        candidate_repository = (
            Repository.from_url(selected_repository) if selected_repository else None
        )
        try:
            result = similarity.search(repository, skill_path)
        except MissingSimilaritySource as exc:
            return error(request, str(exc), 404, "missing_similarity_source")
        # Return navigation is limited to application pages, including nested searches.
        if return_to.partition("?")[0] not in {"/", "/repository", "/similar"} or any(
            ord(char) < 32 or char == "\\" for char in return_to
        ):
            return_to = url(
                "/repository", repository_url=repository.url, skill_path=skill_path, q=q
            )
        selected = next(
            (
                skill
                for match in result.matches
                for skill in match.locations
                if candidate_repository is not None
                and skill.repository.url == candidate_repository.url
                and skill.path == selected_path
            ),
            None,
        )
        return page(
            request,
            "fragments/similar.html"
            if request.url.path.startswith("/fragments/")
            else "pages/similar.html",
            result=result,
            q=q,
            return_to=return_to,
            selected=selected,
            jobs=jobs.recent(),
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
        try:
            target = scan_target(form.get("repository_url", [""])[0])
        except ValueError:
            return error(
                request,
                "Use a repository URL like https://github.com/owner/repository, "
                "or an organization URL like https://github.com/organization.",
                400,
                "invalid_input",
            )
        try:
            job = jobs.submit(target)
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
