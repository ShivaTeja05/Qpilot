"""The commands that open the one page: ``qpilot app``, ``qpilot studio`` and ``qsim app``.

No server is started: :func:`qpilot.web.server.main` is replaced by a recorder, so each test
checks what the command would serve (port, browser, attached audits) and what it prints.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from qpilot.cli import main as qpilot_main

AUDIT_FILES = ("explain.json", "genes.csv", "issues.json", "summary.json", "decisions.csv")


@pytest.fixture
def served(monkeypatch):
    """Record the calls to the one server's ``main`` instead of serving."""
    calls: list[dict] = []

    def fake_main(port=None, **kwargs):
        calls.append({"port": port, **kwargs})

    monkeypatch.setattr("qpilot.web.server.main", fake_main)
    return calls


@pytest.fixture
def run_folder(tmp_path) -> Path:
    """A folder with the files a complete ``qsim run`` writes (names only; nothing is read)."""
    folder = tmp_path / "my-run"
    folder.mkdir()
    for name in AUDIT_FILES:
        (folder / name).write_text("{}", encoding="utf-8")
    return folder


def test_qpilot_studio_opens_the_one_page_and_says_so(served, capsys):
    assert qpilot_main(["studio", "--port", "7998", "--no-open"]) == 0
    assert served == [{"port": 7998, "open_browser": False}]
    assert "Studio is now part of `qpilot app`" in capsys.readouterr().out


def test_qpilot_studio_opens_a_browser_by_default(served):
    assert qpilot_main(["studio"]) == 0
    assert served == [{"port": None, "open_browser": True}]


def test_qpilot_studio_demo_still_needs_check(served, capsys):
    assert qpilot_main(["studio", "demo"]) == 2
    assert "--check" in capsys.readouterr().err
    assert qpilot_main(["studio", "--check"]) == 2  # --check goes with `studio demo`
    assert served == []


def test_qpilot_app_attaches_audit_folders(served, run_folder):
    assert qpilot_main(["app", "--no-open", "--audit", str(run_folder)]) == 0
    (call,) = served
    assert call["audit_dirs"] == {"my-run": run_folder.resolve()}
    assert call["open_browser"] is False and call["fresh_demo"] is False


def test_qsim_app_serves_the_one_page_with_the_run_attached(served, run_folder, capsys):
    from qsim.cli import main as qsim_main

    assert qsim_main(["app", "--results", str(run_folder), "--port", "7997"]) == 0
    assert served == [
        {"port": 7997, "open_browser": False, "audit_dirs": {"my-run": run_folder.resolve()}}
    ]
    assert "part of qPilot's one page" in capsys.readouterr().out


def test_qsim_app_opens_a_browser_only_when_asked(served, run_folder):
    from qsim.cli import main as qsim_main

    assert qsim_main(["app", "--results", str(run_folder), "--open"]) == 0
    assert served[0]["open_browser"] is True and served[0]["port"] is None


def test_qsim_app_without_a_model_answers_by_keywords(served, run_folder, monkeypatch):
    from qsim.cli import main as qsim_main

    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "anthropic")
    assert qsim_main(["app", "--results", str(run_folder), "--no-model"]) == 0
    assert os.environ["QPILOT_MODEL_PROVIDER"] == "none"


def test_qsim_app_says_what_is_missing_from_an_incomplete_run(served, tmp_path, capsys):
    from qsim.cli import main as qsim_main

    empty = tmp_path / "nothing-here"
    empty.mkdir()
    assert qsim_main(["app", "--results", str(empty)]) == 2
    err = capsys.readouterr().err
    assert "has no complete run" in err and "summary.json" in err and "qsim run --out" in err
    assert served == []


def test_help_texts_name_the_one_page(capsys):
    from qpilot.cli import build_parser

    text = " ".join(build_parser().format_help().split())
    assert "Studio is now part of `qpilot app`" in text
    from qsim.cli import main as qsim_main

    with pytest.raises(SystemExit):
        qsim_main(["app", "--help"])
    assert "same as `qpilot app --audit DIR`" in " ".join(capsys.readouterr().out.split())


def test_doctor_describes_the_one_server(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "none")
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))
    qpilot_main(["doctor"])
    out = capsys.readouterr().out
    assert "app: 127.0.0.1 only, this launch's key required, telemetry off" in out
    assert "Gradio" not in out and "pick a model" not in out
