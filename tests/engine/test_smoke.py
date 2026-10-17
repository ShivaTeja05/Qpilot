"""Dev 1 smoke tests: the package imports, the contract fixtures load, the CLI starts."""

import qpilot
from qpilot.cli import main


def test_version():
    assert qpilot.__version__ == "0.1.0"


def test_results_fixture_matches_locked_numbers(fixture_result):
    r = fixture_result
    assert (r.n_plates, r.n_reactions, r.n_samples) == (64, 24576, 366)
    assert (r.design.n_hi, r.design.n_lo) == (53, 294)
    assert r.genorm.order == ["ALUsq(Eurogentec)", "HPRT1", "HMBS", "SDHA(1)", "UBC(2)"]
    odc1 = r.contrasts["ODC1"]
    assert abs(odc1.fc - 3.59) < 0.1 and odc1.conclusion == "up"
    assert r.robustness["ODC1"].holds == 1.0
    assert abs(r.robustness["NM23A"].holds - 0.645) < 0.02
    assert r.confidence["ODC1"].level == "Moderate"
    assert len(r.confidence["ODC1"].reasons) == 1
    assert r.confidence["NM23A"].level == "Very low"


def test_cli_without_command_prints_help(capsys):
    assert main([]) == 0
    assert "qpilot" in capsys.readouterr().out
