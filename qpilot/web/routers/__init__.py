"""The API's routers, discovered: every module in this package that defines ``router``.

Each area has its own module and owner (``studio``, ``results``, ``audit``, ``files``, ``ops``,
…), so adding routes never means editing a shared list. Routes of different modules never
overlap; they are included in module-name order.
"""

import importlib
import pkgutil

from fastapi import APIRouter


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


ROUTERS = discover()
