import pytest

from qpilot.core import robustness as rb
from qpilot.core.confidence import LEVELS, grade
from qpilot.qpcr.confidence_checks import (
    START_LEVEL,
    checks_for,
    mde_fold,
    normalisation_passes,
    precision_passes,
    upgrade_rule,
)
from qpilot.schemas import Check, ContrastResult
from tests.core.toy_space import ToySpace


def chk(cid, passed):
    return Check(id=cid, passed=passed, note=f"{cid} {'ok' if passed else 'failed'}")


def test_two_failed_checks_drop_two_levels():
    g = grade("High", [chk("precision", False), chk("robustness", False), chk("assay", True)])
    assert g.level == "Low"
    assert g.reasons == ["precision failed", "robustness failed"]


def test_reported_checks_never_downgrade():
    g = grade("High", [chk("fragility", False), chk("assay", False), chk("reporting", False)])
    assert g.level == "High" and g.reasons == []


def test_floor_and_upgrade():
    all_bad = [chk("precision", False), chk("robustness", False), chk("normalisation", False)]
    assert grade("Moderate", all_bad).level == "Very low"
    assert grade("Moderate", [chk("normalisation", True)], lambda c: True).level == "High"
    assert grade("High", [chk("normalisation", True)], lambda c: True).level == "High"


def test_upgrade_never_fires_if_normalisation_failed():
    checks = [chk("precision", True), chk("normalisation", False)]
    assert grade("Moderate", checks, lambda c: True).level == "Low"


def test_levels_are_ordinal_labels():
    assert LEVELS == ("High", "Moderate", "Low", "Very low")


@pytest.fixture
def frag(fixture_result):
    return {g: c.min_flip_changes for g, c in fixture_result.confidence.items()}


def _grade(gene, result, frag):
    checks = checks_for(gene, result, frag)
    rule = upgrade_rule(result.contrasts[gene], result.robustness[gene].holds)
    return grade(START_LEVEL, checks, rule, min_flip_changes=frag[gene])


def test_odc1_moderate_one_reason(fixture_result, frag):
    g = _grade("ODC1", fixture_result, frag)
    assert g.level == "Moderate"
    assert len(g.reasons) == 1 and "control gene" in g.reasons[0]
    assert g.min_flip_changes == 0


def test_nm23a_very_low(fixture_result, frag):
    g = _grade("NM23A", fixture_result, frag)
    assert g.level == "Very low"
    assert g.min_flip_changes == 1
    assert len(g.reasons) == 3


@pytest.mark.parametrize("gene", ["BIRC5", "NTRK1"])
def test_headline_genes_moderate(fixture_result, frag, gene):
    assert _grade(gene, fixture_result, frag).level == "Moderate"


def test_every_fixture_grade_reproduced(fixture_result, frag):
    for gene, expected in fixture_result.confidence.items():
        got = _grade(gene, fixture_result, frag)
        assert got.level == expected.level, gene
        # the fixtures still carry the unscored 'reporting' check (dropped since; Dev 1 regenerates)
        assert [(c.id, c.passed) for c in got.checks] == [
            (c.id, c.passed) for c in expected.checks if c.id != "reporting"
        ], gene
    assert sum(1 for v in frag.values() if v == 1) == 31


def test_check_fact_ids_exist(fixture_result, frag):
    for gene in fixture_result.contrasts:
        for check in checks_for(gene, fixture_result, frag):
            missing = [f for f in check.fact_ids if f not in fixture_result.facts]
            assert not missing, (gene, check.id, missing)


def test_mde_matches_fixture(fixture_result):
    for gene, contrast in fixture_result.contrasts.items():
        fid = "f_mde_fold_" + gene.lower().replace("(", "_").replace(")", "")
        if fid in fixture_result.facts:
            assert mde_fold(contrast) == pytest.approx(fixture_result.facts[fid].value, rel=1e-4)


def test_precision_rule():
    def c(lo, hi):
        return ContrastResult(
            target="g", log2fc=0, fc=1, ci=(lo, hi), p=0.5, t=0, n_hi=3, n_lo=3, conclusion="none"
        )

    assert precision_passes(c(2.4, 5.3))
    assert precision_passes(c(0.03, 0.14))
    assert not precision_passes(c(1.05, 2.48))
    assert not precision_passes(c(0.8, 1.2))


def test_normalisation_fails_on_demo(fixture_result):
    assert normalisation_passes(fixture_result) is False


def test_fragility_from_grid():
    space = ToySpace()
    assert rb.fragility(rb.run_grid(space), space) == {"g1": 0, "g2": 1, "g3": 1}


def test_unknown_fragility_reported(fixture_result):
    checks = {c.id: c for c in checks_for("ODC1", fixture_result)}
    assert checks["fragility"].note == "Fragility not computed."


def test_no_unscored_reporting_check(fixture_result, frag):
    assert "reporting" not in {c.id for c in checks_for("ODC1", fixture_result, frag)}
