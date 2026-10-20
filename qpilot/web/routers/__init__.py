"""The API's routers, in the order the page's sections follow the workflow."""

from qpilot.web.routers import studio, system, workspaces

ROUTERS = [system.router, workspaces.router, studio.router]
