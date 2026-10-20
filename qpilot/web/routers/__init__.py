"""The API's routers, discovered: every module in this package that defines ``router``.

Each area has its own module and owner (``studio``, ``results``, ``audit``, ``files``, ``ops``,
…), so adding routes never means editing a shared list. Routes of different modules never
overlap; they are included in module-name order. A module may also export ``JOB_RESULTS``
(job kind → result model) so its jobs' results are typed in the schema.
"""

import importlib
import pkgutil

from fastapi import APIRouter
from pydantic import BaseModel


def discover() -> list[APIRouter]:
    """Import every router module of this package and return their routers, by module name."""
    found: list[APIRouter] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            found.append(router)
    return found


def job_results() -> dict[str, type[BaseModel]]:
    """Every router module's ``JOB_RESULTS`` (job kind → the model of its result), merged.

    A job's result travels as ``JobView.result`` (any shape); registering its model here puts
    the model in the OpenAPI schema (and so in the page's generated types), and
    ``x-job-results`` maps each job kind to it.
    """
    found: dict[str, type[BaseModel]] = {}
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        for kind, model in (getattr(module, "JOB_RESULTS", None) or {}).items():
            if kind in found and found[kind] is not model:
                raise RuntimeError(f"job kind {kind!r} registered twice")
            found[kind] = model
    return found


ROUTERS = discover()
