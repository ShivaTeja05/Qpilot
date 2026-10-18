import pytest

from qpilot.cli import build_parser, main
from qpilot.core.record import write_record, zip_record


def test_core_commands_registered():
    names = set(build_parser()._subparsers._group_actions[0].choices)
    assert {"record", "verify", "rerun"} <= names


def test_verify_cli(store, study, tmp_path, capsys):
    out = tmp_path / "rec"
    write_record(store, study, out)
    assert main(["verify", str(out)]) == 0
    assert "intact" in capsys.readouterr().out
    assert main(["verify", str(zip_record(out, tmp_path / "rec.zip"))]) == 0
    (out / "results.json").write_text("{}")
    assert main(["verify", str(out)]) == 1
    assert "changed: results.json" in capsys.readouterr().out


def test_rerun_cli_without_input(store, study, tmp_path, capsys):
    out = tmp_path / "rec"
    write_record(store, study, out)
    assert main(["rerun", str(out)]) == 2
    assert "cannot be re-run" in capsys.readouterr().err


def test_record_cli_writes_a_record_that_verifies(store, study, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(store.root))
    out = tmp_path / "rec"
    assert main(["record", "--study", study[:12], "--out", str(out)]) == 0
    assert "qpilot verify" in capsys.readouterr().out
    assert main(["verify", str(out)]) == 0
    assert "intact" in capsys.readouterr().out
    # The folder must be new or empty, and an unknown study is a plain error.
    assert main(["record", "--study", study, "--out", str(out)]) == 2
    assert "not empty" in capsys.readouterr().err
    assert main(["record", "--study", "0" * 12, "--out", str(tmp_path / "other")]) == 2
    assert "qpilot record:" in capsys.readouterr().err
    # With one study in the store --study can be left out; with none, the error says so.
    assert main(["record", "--out", str(tmp_path / "only")]) == 0
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(tmp_path / "empty"))
    assert main(["record", "--out", str(tmp_path / "none")]) == 2
    assert "studies here: none" in capsys.readouterr().err


@pytest.mark.parametrize("cmd", ["record", "verify", "rerun"])
def test_help(cmd, capsys):
    with pytest.raises(SystemExit):
        main([cmd, "--help"])


def test_plan_cli(capsys):
    assert main(["plan", "--fc", "2", "--sd", "1.95", "--n", "3"]) == 0
    out = capsys.readouterr().out
    assert "3 per group detects at least 22.0-fold" in out and "61 per group" in out
    assert main(["plan", "--fc", "1"]) == 2
    assert main(["plan", "--json"]) == 0
    assert '"n_needed": null' in capsys.readouterr().out


def test_harness_cli(store, study, capsys):
    assert main(["harness", "make", "--study", study, "--n", "2"]) == 0
    assert len(__import__("json").loads(capsys.readouterr().out)) == 6
    assert main(["harness", "show", "--study", study]) == 1
    assert main(["harness", "run", "--study", study, "--n", "2"]) == 0
    assert "| none | 6/6 | — | 0 | 2/2 |" in capsys.readouterr().out
    assert main(["harness", "show"]) == 0  # the only study
    assert "| none |" in capsys.readouterr().out
    assert main(["harness", "run", "--study", study, "--profile", "local"]) == 2


def test_rerun_accepts_zip(store, study, tmp_path, capsys):
    out = tmp_path / "rec"
    write_record(store, study, out)
    assert main(["rerun", str(zip_record(out, tmp_path / "rec.zip"))]) == 2
    assert "does not include its input" in capsys.readouterr().err


def test_harness_keeps_history(store, study, capsys):
    assert main(["harness", "run", "--study", study, "--n", "1"]) == 0
    assert main(["harness", "run", "--study", study, "--n", "1"]) == 0
    capsys.readouterr()
    assert main(["harness", "show", "--study", study]) == 0
    out = capsys.readouterr().out
    assert "1 earlier runs kept" in out and "none: run 20" in out


def _exit_code(args):
    with pytest.raises(SystemExit) as stop:
        main(args)
    return stop.value.code


def test_open_errors_are_plain(store, tmp_path, capsys, fixtures_dir):
    assert _exit_code(["harness", "make", "--rdml", str(tmp_path / "missing.rdml")]) == 2
    err = capsys.readouterr().err
    assert "no such RDML file" in err and "demo study design" not in err
    assert (
        _exit_code(["harness", "make", "--rdml", str(fixtures_dir / "test_mca_1_raw_data.rdml")])
        == 2
    )
    assert "demo study design" in capsys.readouterr().err
    assert _exit_code(["harness", "make", "--rdml", str(tmp_path)]) == 2
    assert "not a file" in capsys.readouterr().err


def test_no_terminal_decision_commands():
    # People decide in the app; agents ask over MCP. The CLI has no way to decide a card.
    names = set(build_parser()._subparsers._group_actions[0].choices)
    assert "records" not in names
