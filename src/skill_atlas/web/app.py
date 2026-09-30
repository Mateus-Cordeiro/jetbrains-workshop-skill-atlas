"""Assemble the Web interface and own its scan worker lifespan."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from skill_atlas.application.catalog import BrowseCatalog
from skill_atlas.application.documents import Documents
from skill_atlas.application.scan_jobs import ScanJobs
from skill_atlas.ports import CatalogReader
from skill_atlas.web.middleware import local_requests
from skill_atlas.web.routes import register_routes, url

ASSETS = Path(__file__).parent


def create_app(
    catalog: CatalogReader,
    jobs: ScanJobs,
    documents: Callable[[], AbstractContextManager[Documents]],
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        jobs.start()
        try:
            yield
        finally:
            await run_in_threadpool(jobs.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=ASSETS / "templates")
    templates.env.globals["url"] = url
    app.mount("/static", StaticFiles(directory=ASSETS / "static"), name="static")

    app.middleware("http")(local_requests)
    register_routes(app, BrowseCatalog(catalog), jobs, documents, templates)
    return app
