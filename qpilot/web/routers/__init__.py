"""The API's routers, in the order the page's sections follow the workflow."""

from qpilot.web.routers import system, workspaces

ROUTERS = [system.router, workspaces.router]
