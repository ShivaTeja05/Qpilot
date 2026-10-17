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
