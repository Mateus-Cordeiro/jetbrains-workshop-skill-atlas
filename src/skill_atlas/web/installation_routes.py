"""HTTP adaptation for explicit local project and installation management."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from skill_atlas.adapters.projects import project_path
from skill_atlas.application.documents import MissingSkill, StaleSkill
from skill_atlas.application.installations import Installations
from skill_atlas.application.projects import Projects
from skill_atlas.errors import AtlasError, RepositoryError
from skill_atlas.installation import InstallationError
from skill_atlas.installation_ports import BundleReader
from skill_atlas.models import Repository
from skill_atlas.ports import CatalogReader
from skill_atlas.web.routes import form_fields


def register_installation_routes(
    app: FastAPI,
    service: Installations,
    projects: Projects,
    bundles: BundleReader,
    catalog: CatalogReader,
    templates: Jinja2Templates,
) -> None:
    @app.get("/installations", response_class=HTMLResponse)
    def page(
        request: Request, project: str = "", source: str = "", agent: str = "codex", name: str = ""
    ) -> HTMLResponse:
        context: dict[str, Any] = dict(
            project=project,
            source=source,
            agent=agent,
            name=name,
            statuses=(),
            preview=None,
            message="",
            projects=(),
            skills=(),
        )
        status = 200
        try:
            context.update(projects=projects.list(), skills=catalog.skills())
            if project:
                root = projects.select(project_path(project, web=True))
                context["project"] = str(root)
                context["statuses"] = service.list(root)
                if source:
                    repository_url, path = source.split("|", 1)
                    context["preview"] = service.preview(
                        root, Repository.from_url(repository_url), path, agent, name
                    )
        except (AtlasError, ValueError) as error:
            context["message"] = str(error)
            status = 409
        return templates.TemplateResponse(
            request=request, name="pages/installations.html", context=context, status_code=status
        )

    def action(operation: str, fields: dict[str, str]) -> str:
        root = project_path(fields.get("project", ""), web=True)
        if operation == "register":
            projects.register(root)
            return "Project registered. Select it to review a destination."
        projects.select(root)
        repository = Repository.from_url(fields["repository_url"])
        path, agent = fields["skill_path"], fields["agent"]
        if not fields.get("commit_sha"):
            raise InstallationError("Refresh the selection before continuing.")
        if operation == "uninstall":
            return service.uninstall(
                root, repository, path, agent, expected_commit=fields["commit_sha"]
            )
        if operation not in {"install", "update"}:
            raise ValueError("Unknown installation action.")
        if not fields.get("destination"):
            raise InstallationError("Preview the exact destination before installing.")
        return service.install(
            root,
            repository,
            path,
            agent,
            bundles,
            name=fields.get("name", ""),
            commit=fields["commit_sha"],
            expected_destination=fields["destination"],
            update=operation == "update",
        )

    @app.post("/installations/{operation}")
    async def mutate(request: Request, operation: str) -> JSONResponse:
        try:
            values = await form_fields(request)
            if values is None or any(len(v) != 1 for v in values.values()):
                raise ValueError("Invalid form fields.")
            message = await run_in_threadpool(
                action, operation, {k: v[0] for k, v in values.items()}
            )
            return JSONResponse({"message": message})
        except (ValueError, KeyError, UnicodeError) as error:
            return JSONResponse(
                {"message": "Invalid installation request: " + str(error), "code": "invalid_input"},
                status_code=400,
            )
        except AtlasError as error:
            status = (
                404
                if isinstance(error, MissingSkill)
                else 502
                if isinstance(error, RepositoryError)
                else 409
            )
            code = "stale_selection" if isinstance(error, StaleSkill) else "installation_error"
            return JSONResponse({"message": str(error), "code": code}, status_code=status)
