"""Adapt saved group browsing and explicit generation to HTTP fragments."""

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from skill_atlas.application.grouping import SkillGroups
from skill_atlas.application.grouping_jobs import GroupingJobs
from skill_atlas.application.scan_jobs import ScanJobs
from skill_atlas.errors import GroupingError
from skill_atlas.grouping import Perspective, SkillIdentity
from skill_atlas.models import Repository


def register_grouping_routes(
    app: FastAPI,
    groups: SkillGroups,
    jobs: GroupingJobs,
    scans: ScanJobs,
    templates: Jinja2Templates,
) -> None:
    @app.get("/groups/{perspective}")
    @app.get("/fragments/groups/{perspective}")
    def browse(
        request: Request,
        perspective: Perspective,
        selected_repository: str = "",
        selected_path: str = "",
    ) -> Response:
        identity = (
            SkillIdentity(Repository.from_url(selected_repository).url, selected_path)
            if selected_repository
            else None
        )
        view = groups.browse(perspective, identity)
        return templates.TemplateResponse(
            request=request,
            name="fragments/groups.html"
            if request.url.path.startswith("/fragments/")
            else "pages/groups.html",
            context={
                "perspective": perspective.value,
                "view": view,
                "selected": view.selected,
                "group_job": jobs.latest(perspective),
                "q": "",
                "jobs": scans.recent(),
            },
        )

    @app.post("/groups/{perspective}/generate")
    def generate(request: Request, perspective: Perspective) -> Response:
        try:
            job = jobs.submit(perspective)
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
            headers={"Location": f"/groups/{perspective.value}/status"},
            context={"group_job": job},
        )

    @app.get("/groups/{perspective}/status")
    def status(request: Request, perspective: Perspective) -> Response:
        return templates.TemplateResponse(
            request=request,
            name="fragments/group-status.html",
            context={"group_job": jobs.latest(perspective)},
        )
