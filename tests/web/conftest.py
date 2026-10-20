"""Fixtures for the one server: an app over a throwaway store, and a client with the key."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.web.context import make_context
from qpilot.web.server import create_app

TOKEN = "test-token"
BASE = "http://127.0.0.1:7860"


@pytest.fixture
def web_store(tmp_studies_dir) -> StudyStore:
    return StudyStore(tmp_studies_dir)


@pytest.fixture
def web_ctx(web_store):
    ctx = make_context(web_store, token=TOKEN, watch=False)
    yield ctx
    ctx.close()


@pytest.fixture
def raw_client(web_ctx) -> Iterator[TestClient]:
    """A client without the launch key (for the guard's refusals)."""
    with TestClient(create_app(web_ctx), base_url=BASE) as client:
        yield client


@pytest.fixture
def client(web_ctx) -> Iterator[TestClient]:
    """A client that carries the launch key, as the page does after opening the printed link."""
    with TestClient(create_app(web_ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        yield c
