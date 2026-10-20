"""Print the API's OpenAPI schema (``python -m qpilot.web.openapi``), for the page's types.

``npm run gen:api`` in ``frontend/`` turns it into ``src/api/schema.d.ts``; ``npm run check:api``
and ``tests/web/test_contract.py`` fail when the two have drifted apart.
"""

from __future__ import annotations

import json
import sys
import tempfile


def schema() -> dict:
    """The OpenAPI schema of the one server (built without starting it or watching the store)."""
    from qpilot.core.store import StudyStore
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app

    with tempfile.TemporaryDirectory() as tmp:
        ctx = make_context(StudyStore(tmp), token="openapi", watch=False)
        try:
            return create_app(ctx).openapi()
        finally:
            ctx.close()


if __name__ == "__main__":
    json.dump(schema(), sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")
