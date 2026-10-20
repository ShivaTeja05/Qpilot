"""``qpilot doctor`` and the example model profile (kept from the old page's tests)."""

import json
from pathlib import Path

from qpilot.cli import main

REPO = Path(__file__).resolve().parents[2]


def test_doctor_reports_no_outbound_without_a_model(monkeypatch, tmp_path, capsys):
    for var in ("QPILOT_MODEL_PROVIDER", "QPILOT_MODEL_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("QPILOT_API_KEY", "supersecret-123")
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path))  # nothing cached: still no download
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "outbound: none" in out and "provider: none" in out and "OK" in out.splitlines()
    assert "QPILOT_API_KEY: set" in out and "supersecret" not in out
    assert "run `qpilot fetch-demo`" in out
    assert list(tmp_path.iterdir()) == []


def test_doctor_names_the_endpoint_when_a_model_is_set(monkeypatch, capsys):
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "openai_compatible")
    monkeypatch.setenv("QPILOT_MODEL_ENDPOINT", "http://127.0.0.1:11434")
    monkeypatch.setenv("QPILOT_MODEL_NAME", "m")
    assert main(["doctor"]) == 0
    assert "outbound: http://127.0.0.1:11434" in capsys.readouterr().out


def test_example_profile_loads(monkeypatch):
    from qpilot.ai.profile import load_profile

    monkeypatch.setenv("QPILOT_PROFILE", str(REPO / "qpilot_profile.example.yaml"))
    profile = load_profile()
    assert profile.name == "example-lab" and profile.max_fewshots == 3
    assert json.dumps(profile.model_dump())  # plain data only
