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
    assert "| none | 6/6 | — | 0 | 2/2 |" in capsys.readouterr().out
    assert main(["harness", "show"]) == 0  # the only study
    assert "| none |" in capsys.readouterr().out
    assert main(["harness", "run", "--study", study, "--profile", "local"]) == 2


def test_records_cli_flow(store, study, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)  # a person at a terminal
    assert main(["records", "list"]) == 0
    assert study in capsys.readouterr().out
    assert main(["records", "cards"]) == 0
    assert "card_refset" in capsys.readouterr().out
    assert main(["records", "ask", "What", "is", "the", "fold", "change", "of", "ODC1?"]) == 0
    assert "3.6×" in capsys.readouterr().out
    assert main(["records", "decide", "card_refset", "top2", "--reason", "two most stable"]) == 0
    assert "applied" in capsys.readouterr().out
    assert main(["records", "decide", "card_refset", "nope", "--reason", "x"]) == 2
    assert main(["records", "ask", "Apply", "HMBS", "alone", "for", "the", "control", "genes"]) == 0
    assert "person must decide" in capsys.readouterr().out
    assert main(["records", "pending"]) == 0
    assert "hmbs_alone" in capsys.readouterr().out
    assert main(["records", "reject", "card_refset", "--reason", "not stable"]) == 0
    assert main(["records", "log"]) == 0
    assert "rejected" in capsys.readouterr().out
    out = tmp_path / "rec"
    assert main(["records", "export", "--out", str(out), "--zip"]) == 0
    assert "intact" in capsys.readouterr().out and (tmp_path / "rec.zip").exists()


def test_decide_needs_a_person_at_a_terminal(store, study, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)  # e.g. an agent's shell tool
    assert main(["records", "decide", "card_refset", "top2", "--reason", "x"]) == 2
    assert "interactive terminal" in capsys.readouterr().err
    assert store.card(study, "card_refset").decision is None
    assert main(["records", "reject", "card_refset", "--reason", "x"]) == 2


def test_records_genes_and_open_show_robustness(store, study, capsys):
    assert main(["records", "genes"]) == 0
    out = capsys.readouterr().out
    nm23a = next(line for line in out.splitlines() if line.startswith("NM23A"))
    assert "65%" in nm23a and "Very low" in nm23a and "refs" in nm23a and "cut" in nm23a


def test_export_without_input_and_open_card_warning(store, study, tmp_path, capsys):
    out = tmp_path / "rec"
    assert main(["records", "export", "--out", str(out), "--without-input"]) == 0
    text = capsys.readouterr().out
    assert "not yet decided by a person: card_refset, card_cutoff" in text
    assert "verified but not re-run" in text
    assert not (out / "input.rdml").exists()


def test_rerun_accepts_zip(store, study, tmp_path, capsys):
    from qpilot.core.record import write_record, zip_record

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


def test_require_person_with_closed_stdin(store, study, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", None)
    assert main(["records", "decide", "card_refset", "top2", "--reason", "x"]) == 2
    assert "not a security boundary" in capsys.readouterr().err


def test_export_note_for_human_decided_card_with_new_request(store, study, tmp_path, capsys):
    from qpilot.core.decisions import apply_decision

    apply_decision(store, study, "card_refset", "recommended", "keep", "human")
    apply_decision(store, study, "card_cutoff", "cut_15", "keep", "human")
    apply_decision(store, study, "card_refset", "hmbs_alone", "agent idea", "agent")
    assert main(["records", "export", "--out", str(tmp_path / "r")]) == 0
    out = capsys.readouterr().out
    assert "not yet decided by a person" not in out
    assert "agent requests still waiting on: card_refset" in out


def test_open_errors_are_plain(store, tmp_path, capsys, fixtures_dir):
    assert main(["records", "open", "--rdml", str(tmp_path / "missing.rdml")]) == 2
    err = capsys.readouterr().err
    assert "no such RDML file" in err and "demo study design" not in err
    assert main(["records", "open", "--rdml", str(fixtures_dir / "test_mca_1_raw_data.rdml")]) == 2
    assert "demo study design" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="demo study design"):
        main(["harness", "make", "--rdml", str(fixtures_dir / "test_mca_1_raw_data.rdml")])


@pytest.mark.demo_data
def test_records_open_shows_genorm(capsys, tmp_studies_dir, demo_rdml_path):
    assert main(["records", "open", "--rdml", str(demo_rdml_path)]) == 0
    out = capsys.readouterr().out
    assert "geNorm M (lower = steadier; cut-off 1.5): ALUsq(Eurogentec) 1.68" in out
    assert "geNorm V (want < 0.15): V2/3 0.56" in out
