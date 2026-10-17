import pytest

from qpilot.cli import build_parser, main
from qpilot.core.record import write_record, zip_record


def test_core_commands_registered():
    names = set(build_parser()._subparsers._group_actions[0].choices)
    assert {"verify", "rerun"} <= names


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


@pytest.mark.parametrize("cmd", ["verify", "rerun"])
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
    assert "| none | 6/6 | 0 | 2/2 |" in capsys.readouterr().out
    assert main(["harness", "show"]) == 0  # the only study
    assert "| none |" in capsys.readouterr().out
    assert main(["harness", "run", "--study", study, "--profile", "local"]) == 2
