"""qPilot's one server: the page, the API and live events on 127.0.0.1, one port.

``qpilot app`` (and ``qpilot studio``, ``qsim app``) start it. It serves:

* ``/api/...`` — JSON over the same on-disk store the MCP server writes (``qpilot serve``);
* ``/api/events`` — server-sent events (jobs, decisions, agent requests);
* ``/`` and ``/assets/...`` — the built page (``qpilot/web/static``, built from ``frontend/``).

See :mod:`qpilot.web.security` for what every request must satisfy.
"""

from __future__ import annotations

import os
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

from qpilot import __version__  # noqa: E402
from qpilot.core.store import StudyStore  # noqa: E402
from qpilot.studio_service import Studio  # noqa: E402
from qpilot.web.context import AppContext, make_context  # noqa: E402
from qpilot.web.security import Guard, launch_token  # noqa: E402

STATIC = Path(__file__).parent / "static"
HOST = "127.0.0.1"
DEFAULT_PORT = 7860
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

    @app.get("/{name:path}", include_in_schema=False)
    async def page(name: str) -> Response:
        # Files at the root of the build (favicon, fonts manifest); everything else is the page,
        # whose hash router shows the right section.
        if name and "/" not in name:
            path = _static_file(Path(name))
            if path is not None:
                return FileResponse(path, headers={"cache-control": "no-cache"})
        index = STATIC / "index.html"
        if not index.is_file():
            return Response(NOT_BUILT, media_type="text/html")
        return FileResponse(index, headers={"cache-control": "no-cache"})

    app.add_middleware(Guard, token=ctx.token)
    return app


def _type_job_results(app: FastAPI) -> None:
    """Add every registered job-result model to the schema; ``x-job-results`` maps the kinds."""
    from qpilot.web.routers import job_results

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
    root = STATIC.resolve()
    path = (STATIC / relative).resolve()
    if not path.is_file() or root not in path.parents:
        return None
    return path


WARM = (
    "qpilot.qpcr.curves",
    "qpilot.qpcr.study",
    "qpilot.explain.templates",
    "qpilot.app_state",
    "qpilot.studio_state",
    "qsim.app",
)


def _warm_imports() -> None:
    """Import the analysis modules in the background, so the first page view is not the wait."""
    import importlib
    import threading

    def run() -> None:
        for name in WARM:
            try:
                importlib.import_module(name)
            except Exception:  # an optional part (the simulator) may be missing
                continue

    threading.Thread(target=run, name="qpilot-warm-imports", daemon=True).start()


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
    _warm_imports()
    app = create_app(ctx)
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
