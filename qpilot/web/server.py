"""qPilot's one server: the page, the API and live events on 127.0.0.1, one port.

``qpilot app`` (and ``qpilot studio``, ``qsim app``) start it. It serves:

* ``/api/...`` — JSON over the same on-disk store the MCP server writes (``qpilot serve``);
* ``/api/events`` — server-sent events (jobs, decisions, agent requests);
* ``/`` and ``/assets/...`` — the built page (``qpilot/web/static``, built from ``frontend/``).

See :mod:`qpilot.web.security` for what every request must satisfy. A public sandbox
(``QPILOT_HOSTED=1``) also limits each visitor's requests and slow work
(:mod:`qpilot.web.ratelimit`); a person's own computer never does.
"""

from __future__ import annotations

import os
import re
import socket
import sys
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")  # any library that would phone home

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

from qpilot import __version__  # noqa: E402
from qpilot.core.store import StudyStore  # noqa: E402
from qpilot.studio_service import Studio  # noqa: E402
from qpilot.web.cache import ApiCache  # noqa: E402
from qpilot.web.context import AppContext, make_context  # noqa: E402
from qpilot.web.ratelimit import Busy, Limiter, RateLimit, RateLimits  # noqa: E402
from qpilot.web.security import Guard, launch_token  # noqa: E402

STATIC = Path(__file__).parent / "static"
HOST = "127.0.0.1"
DEFAULT_PORT = 7860
GZIP_MIN_BYTES = 4096  # small answers are sent as they are
GZIP_LEVEL = 5  # an 800 KB view in a few milliseconds, about a tenth of its size
NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>qPilot</title>
<body style="font:16px system-ui;margin:3rem;max-width:40rem">
<h1>qPilot</h1><p>The page has not been built in this checkout.</p>
<p>Run <code>npm ci &amp;&amp; npm run build</code> in <code>frontend/</code>, or install a
released qPilot. The API is running.</p></body>"""


def create_app(ctx: AppContext) -> FastAPI:
    """The FastAPI application over one :class:`AppContext` (tests build it directly)."""
    from qpilot.web.routers import ROUTERS

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        yield
        ctx.close()

    app = FastAPI(
        title="qPilot",
        version=__version__,
        description="qPilot's local API. Research use only. Not for clinical or diagnostic use.",
        docs_url=None,  # no third-party docs page (it would load scripts from a CDN)
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        # Operation ids are the handlers' names (unique across routers): the page's typed client
        # and the generated schema read like the Python code.
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.ctx = ctx
    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    _type_job_results(app)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            body = {"error": {"details": {}, **detail}}
        else:
            body = {"error": {"code": "http_" + str(exc.status_code), "message": str(detail)}}
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Busy)
    async def sandbox_busy(_: Request, exc: Busy) -> JSONResponse:
        # A job refused while a route ran (the visitor has too much running): in words.
        return JSONResponse(
            exc.body(), status_code=exc.status, headers={"Retry-After": str(exc.retry_after)}
        )

    @app.exception_handler(RequestValidationError)
    async def bad_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {"where": ".".join(str(p) for p in e.get("loc", ())), "problem": e.get("msg", "")}
            for e in exc.errors()
        ][:20]
        body = {
            "error": {
                "code": "bad_request",
                "message": "Some fields of this request are not valid.",
                "details": {"problems": problems},
            }
        }
        return JSONResponse(body, status_code=422)

    @app.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def api_not_found(rest: str) -> JSONResponse:
        body = {"error": {"code": "not_found", "message": "No such API route.", "details": {}}}
        return JSONResponse(body, status_code=404)

    @app.get("/assets/{name:path}", include_in_schema=False)
    async def asset(name: str) -> Response:
        path = _static_file(Path("assets") / name)
        if path is None:
            return Response(status_code=404)
        return FileResponse(path, headers={"cache-control": "public, max-age=31536000, immutable"})

    @app.api_route("/{name:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def page(name: str) -> Response:
        # Files at the root of the build (favicon, fonts manifest); everything else is the page,
        # whose hash router shows the right section. A NUL is no name of anything.
        if "\x00" in name:
            return Response(status_code=404)
        if name and "/" not in name:
            path = _static_file(Path(name))
            if path is not None:
                return FileResponse(path, headers={"cache-control": "no-cache"})
        index = STATIC / "index.html"
        if not index.is_file():
            return Response(NOT_BUILT, media_type="text/html")
        return FileResponse(index, headers={"cache-control": "no-cache"})

    # Innermost first: tags and 304s on the route's own bytes, then compression, then (on a
    # public sandbox only) the visitor's limit, then the guard.
    app.add_middleware(ApiCache, bus=ctx.bus)
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL)
    limits = RateLimits.from_env()
    if limits is not None:
        limiter = Limiter(limits)
        app.state.limiter = limiter
        ctx.jobs.admission = limiter.admit_job
        app.add_middleware(RateLimit, limiter=limiter, jobs=ctx.jobs, heavy=job_starting_paths())
    app.add_middleware(Guard, token=ctx.token)
    return app


def job_starting_paths() -> list[re.Pattern[str]]:
    """The paths of the ``POST`` routes that answer ``202`` with a job (they start slow work)."""
    from fastapi.routing import APIRoute
    from starlette.routing import compile_path

    from qpilot.web.routers import ROUTERS

    return [
        compile_path("/api" + route.path)[0]
        for router in ROUTERS
        for route in router.routes
        if isinstance(route, APIRoute)
        and "POST" in (route.methods or ())
        and route.status_code == 202
    ]


def _type_job_results(app: FastAPI) -> None:
    """Add every registered job-result model to the schema; ``x-job-results`` maps the kinds."""
    from qpilot.web.jobs import RESULT_TYPES
    from qpilot.web.routers import job_results

    RESULT_TYPES.update({kind: model.__name__ for kind, model in job_results().items()})
    plain = app.openapi
    done = False

    def openapi() -> dict[str, Any]:
        nonlocal done
        schema = plain()
        if done:
            return schema
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        mapping: dict[str, str] = {}
        for kind, model in sorted(job_results().items()):
            body = model.model_json_schema(
                ref_template="#/components/schemas/{model}", mode="serialization"
            )
            for name, sub in body.pop("$defs", {}).items():
                components.setdefault(name, sub)
            components.setdefault(model.__name__, body)
            mapping[kind] = model.__name__
        schema["x-job-results"] = mapping
        done = True
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


def _static_file(relative: Path) -> Path | None:
    """A file inside ``static/`` (never outside it, never a dotfile), or None."""
    if any(part.startswith(".") or part == ".." for part in relative.parts):
        return None
    try:
        root = STATIC.resolve()
        path = (STATIC / relative).resolve()
        if not path.is_file() or root not in path.parents:
            return None
    except (OSError, ValueError):  # a NUL or an over-long name is no file of the build
        return None
    return path


FACTS_WAIT_S = 0.25  # a request waits this long for a cold file, then answers "warming"


def free_port(start: int = DEFAULT_PORT, tries: int = 50) -> int:
    """The first port from ``start`` that 127.0.0.1 can bind."""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise OSError(f"no free port in {start}–{start + tries - 1}")


def main(
    port: int | None = None,
    *,
    open_browser: bool = True,
    fresh_demo: bool = False,
    audit_dirs: dict[str, Path] | None = None,
    section: str = "",
    store: StudyStore | None = None,
) -> None:
    """Serve the page on 127.0.0.1 and print the link (with this launch's key)."""
    import uvicorn

    store = store or StudyStore()
    if fresh_demo:
        from qpilot.web.views import archive_demo

        for moved in archive_demo(store):
            print(f"Earlier demo work moved to {moved} (kept, never deleted)")
    token = launch_token()
    ctx = make_context(store, Studio(store), token=token, audit_dirs=audit_dirs)
    ctx.facts_wait = FACTS_WAIT_S
    from qpilot.web.warm import warm_all

    app = create_app(ctx)
    # Imports, then every session's file, then the views a person opens next (all in the
    # background; the page answers meanwhile).
    warm_all(ctx, app)
    port = port or free_port()
    url = f"http://{HOST}:{port}/?token={token}" + (f"#/{section}" if section else "")
    print(f"qPilot {__version__} — research use only, not for clinical or diagnostic use.")
    print(f"Open this link (it carries this launch's key): {url}")
    print("This computer only. Ctrl-C to stop.", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # no browser on this machine: the link above is enough
            pass
    config: dict[str, Any] = {
        "host": HOST,
        "port": port,
        "log_level": "warning",
        "access_log": False,
        "server_header": False,
        "date_header": False,
        "timeout_graceful_shutdown": 3,
    }
    try:
        uvicorn.run(app, **config)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        sys.exit(0)
