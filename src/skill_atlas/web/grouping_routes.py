"""Adapt graph browsing and paired generation to HTTP pages and fragments."""

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from skill_atlas.application.grouping import SkillGroups
from skill_atlas.application.grouping_jobs import GroupingJobs
from skill_atlas.application.scan_jobs import ScanJobs
from skill_atlas.errors import GroupingError
from skill_atlas.grouping import Perspective
from skill_atlas.web.exploration import graph_data
from skill_atlas.web.routes import url


def register_grouping_routes(
    app: FastAPI,
    groups: SkillGroups,
    jobs: GroupingJobs,
    scans: ScanJobs,
    templates: Jinja2Templates,
) -> None:
    @app.get("/explore")
    @app.get("/fragments/explore")
    def browse(request: Request, perspective: Perspective = Perspective.CAPABILITIES) -> Response:
        views = groups.explore()
        return templates.TemplateResponse(
            request=request,
            name="fragments/groups.html"
            if request.url.path.startswith("/fragments/")
            else "pages/groups.html",
            context={
                "perspective": perspective.value,
                "views": views,
                "view": views[perspective],
                "graph_data": graph_data(views),
                "has_groups": any(v.grouping is not None for v in views.values()),
                "group_job": jobs.latest(),
                "q": "",
                "jobs": scans.recent(),
            },
        )

    # Preserve bookmarked group and skill links from the original list UI.
    @app.get("/groups/{perspective}")
    @app.get("/fragments/groups/{perspective}")
    def legacy(
        perspective: Perspective, selected_repository: str = "", selected_path: str = ""
    ) -> Response:
        if selected_repository:
            from skill_atlas.models import Repository

            return RedirectResponse(
                url(
                    "/repository",
                    repository_url=Repository.from_url(selected_repository).url,
                    skill_path=selected_path,
                    from_explore=perspective.value,
                ),
                status_code=307,
            )
        return RedirectResponse(url("/explore", perspective=perspective.value), status_code=307)

    @app.post("/explore/generate")
    def generate(request: Request) -> Response:
        try:
            job = jobs.submit()
        except GroupingError as error:
            return templates.TemplateResponse(
                request=request,
                name="fragments/error.html",
                status_code=503,
                context={"message": str(error), "code": "grouping_unavailable"},
            )
        return templates.TemplateResponse(
            request=request,
            name="fragments/group-status.html",
            status_code=202,
            headers={"Location": "/explore/status"},
            context={"group_job": job},
        )

    @app.get("/explore/status")
    def status(request: Request) -> Response:
        return templates.TemplateResponse(
            request=request,
            name="fragments/group-status.html",
            context={"group_job": jobs.latest()},
        )
