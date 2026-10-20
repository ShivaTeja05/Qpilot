"""The model's status: a remote model is never contacted to render a page, only on a click."""

from __future__ import annotations

from fastapi.testclient import TestClient

from qpilot.ai.client import ModelClient
from qpilot.studio_service import Studio
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN


class RemoteBackend:
    """A remote endpoint that counts every request it is sent."""

    name = "anthropic"
    model = "remote-model"
    url = "https://api.example.com/v1"

    def __init__(self) -> None:
        self.sent: list[str] = []  # shared with the copy the ping makes

    @property
    def calls(self) -> int:
        return len(self.sent)

    def complete(self, system, messages, max_tokens, temperature) -> str:
        self.sent.append(system)
        return "OK"


def _client(store, backend):
    ctx = make_context(store, Studio(store, client=ModelClient(backend=backend)), token=TOKEN,
                       watch=False)  # fmt: skip
    client = TestClient(create_app(ctx), base_url=BASE)
    client.headers["x-qpilot-token"] = TOKEN
    client.headers["origin"] = BASE
    return ctx, client


def test_reading_the_status_never_contacts_a_remote_model(web_store):
    backend = RemoteBackend()
    ctx, client = _client(web_store, backend)
    with client:
        for path in ("/api/model", "/api/system", "/api/model", "/api/system"):
            assert client.get(path).status_code == 200
        status = client.get("/api/model").json()
        assert backend.calls == 0
        assert not status["local"] and status["configured"] and not status["available"]
        assert status["answers"] is None and "Check connection" in status["reason"]
        checked = client.post("/api/model/check").json()
        assert backend.calls == 1 and checked["available"] and checked["answers"] is True
        again = client.get("/api/model").json()
        assert backend.calls == 1 and again["available"], "the answer is remembered, not re-asked"
    ctx.close()


def test_no_model_says_so(client):
    status = client.get("/api/model").json()
    assert status["provider"] == "none" and status["local"] and not status["available"]
    assert client.post("/api/model/check", headers={"origin": BASE}).json()["provider"] == "none"
