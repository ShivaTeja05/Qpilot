"""Task 8 gate: run_study wires the engine into the core and reproduces every planned number.

Task 8b gate: card 1 carries the group-effect check.
"""

import json

import numpy as np
import pandas as pd
import pytest

from qpilot.cli import main
from qpilot.core.facts import render_fact
from qpilot.qpcr.study import StudySettings, run_study, study_from_curves, write_outputs
from qpilot.schemas import DecisionCard, StudyResult

REFSET_EXTRA_FACTS = [
    "f_ref_pair_top",
    "f_ref_ratio_top",
    "f_ref_ratio_top_p",
    "f_n_ref_pairs_flagged",
    "f_n_ref_pairs",
    "f_ref_flag_fold",
]

# ---------- a small synthetic study (runs in CI) ----------

TOY = StudySettings(candidates=("R1", "R2", "R3"), marker="M(1)", group_var="M_high",
                    headline=("UP", "FLAT"))  # fmt: skip


@pytest.fixture(scope="module")
def toy_curves():
    rng = np.random.default_rng(11)
    n = 80
    base = rng.normal(10, 1.5, n)
    marker = rng.normal(0, 1, n)
    log2 = {
        "R1": base + rng.normal(0, 0.3, n),
        "R2": base + rng.normal(0, 0.4, n),
        "R3": base + rng.normal(0, 0.9, n),
        "M(1)": base + marker * 2,
        "UP": base + marker * 2.5 + rng.normal(0, 0.4, n),
        "DOWN": base - marker * 2.5 + rng.normal(0, 0.4, n),
        "FLAT": base + rng.normal(0, 0.5, n),
    }
    rows = []
    for plate, (gene, values) in enumerate(log2.items()):
        for i, value in enumerate(values):
            n0 = float("nan") if (gene, i) == ("FLAT", 3) else 2.0**value
            rows.append(
                {
                    "run_id": f"p{plate}",
                    "well": f"A{i}",
                    "sample": f"s{i:02d}",
                    "sample_type": "unkn",
                    "target": gene,
                    "n0": n0,
                    "eff_target": 1.9,
                }
            )
        rows.append(
            {
                "run_id": f"p{plate}",
                "well": "Z1",
                "sample": "STD_15",
                "sample_type": "std",
                "target": gene,
                "n0": 15.0,
                "eff_target": 1.9,
            }
        )
    return pd.DataFrame(rows)  # fmt: skip


@pytest.fixture(scope="module")
def toy(toy_curves):
    return study_from_curves(toy_curves, "ab" * 32, TOY)


def test_toy_study_shape(toy):
    result, cards, grid = toy
    assert result.study_id == "ab" * 6
    assert (result.n_plates, result.n_samples) == (7, 80)
    assert set(result.contrasts) == set(result.robustness) == set(result.confidence)
    assert set(result.contrasts) == {"UP", "DOWN", "FLAT"}  # not the controls or the marker
    assert len(grid) == 7 * 3 * 2 * 3  # 7 control-gene subsets x 3 cuts x 2 rules x 3 genes
    assert result.contrasts["UP"].conclusion == "up"
    assert result.contrasts["DOWN"].conclusion == "down"


def test_toy_cards_and_escalation(toy):
    _, cards, _ = toy
    assert {c.id for c in cards} == {"card_refset", "card_cutoff", "card_undetermined"}
    assert sorted(c.rank for c in cards) == [1, 2, 3]
    flipped = [c.impact["n_genes_flipped"] for c in sorted(cards, key=lambda c: c.rank)]
    assert flipped == sorted(flipped, reverse=True)
    for card in cards:
        assert card.recommended in {o.id for o in card.options}
        assert all(set(o.per_gene) == {"UP", "FLAT"} for o in card.options)
        if card.impact["flips"]:
            assert card.status == "open"  # a choice that can flip a conclusion waits for a human
        else:
            assert card.status == "auto_decided" and card.decided_by == "system"
    cutoff = next(c for c in cards if c.id == "card_cutoff")
    assert [o.label for o in cutoff.options][0] == "Top 10 % by M expression"


def test_toy_every_cited_fact_exists(toy):
    result, cards, _ = toy
    for card in cards:
        assert not [f for f in card.facts if f not in result.facts], card.id
    for gene, graded in result.confidence.items():
        for check in graded.checks:
            assert not [f for f in check.fact_ids if f not in result.facts], (gene, check.id)
    assert result.facts["f_fc_up_recommended"].value == result.contrasts["UP"].fc
    assert result.facts["f_n_undetermined"].value == 1


def test_toy_is_deterministic_and_writes_valid_files(toy_curves, toy, tmp_path):
    result, cards, grid = toy
    again = study_from_curves(toy_curves, "ab" * 32, TOY)
    assert again[0].model_dump_json() == result.model_dump_json()
    paths = write_outputs(result, cards, grid, tmp_path)
    assert sorted(paths) == ["cards.json", "facts.json", "grid.csv", "results.json"]
    assert StudyResult.model_validate_json(paths["results.json"].read_text()) == result
    loaded = [DecisionCard.model_validate(c) for c in json.loads(paths["cards.json"].read_text())]
    assert loaded == cards
    assert json.loads(paths["facts.json"].read_text()).keys() == result.facts.keys()


def test_toy_refset_card_extras(toy):
    result, cards, _ = toy
    refset = next(c for c in cards if c.id == "card_refset")
    assert set(refset.impact) == {"flips", "n_genes_flipped", "max_delta_log2fc"}
    evidence = refset.evidence
    assert evidence["genorm_validated"] is False and "pairwise ratios" in evidence["genorm_note"]
    assert evidence["ref_group_effect"]["note"] == "3 pairs, no multiple-testing correction"
    assert json.loads(json.dumps(evidence)) == evidence
    assert [f for f in REFSET_EXTRA_FACTS if f not in refset.facts] == []
    assert result.facts["f_n_ref_pairs"].value == 3
    assert {"f_ref_ratio_r1_r2", "f_ref_ratio_r1_r3_p", "f_ref_ratio_r2_r3"} <= set(result.facts)


def test_marker_label_drops_the_assay_suffix():
    assert StudySettings().marker_label == "MYCN"
    assert StudySettings(marker="GAPDH").marker_label == "GAPDH"


def test_cli_run_reports_a_missing_file(tmp_path, capsys):
    assert main(["run", str(tmp_path / "missing.rdml")]) == 1
    assert "qpilot run" in capsys.readouterr().err


# ---------- the demo study: every number in the plan ----------


@pytest.fixture(scope="module")
def demo(demo_curves):
    from qpilot.io.datasets import VERMEULEN_SHA256

    return study_from_curves(demo_curves, VERMEULEN_SHA256)


def _fc(card: DecisionCard, option: str, gene: str) -> float:
    return next(o for o in card.options if o.id == option).per_gene[gene].fc


@pytest.mark.demo_data
def test_demo_result_numbers(demo):
    result, _, grid = demo
    assert (result.n_plates, result.n_reactions, result.n_samples) == (64, 24576, 366)
    assert (result.design.n_hi, result.design.n_lo) == (53, 294)
    assert len(result.contrasts) == 58 and len(grid) == 186 * 58
    odc1 = result.contrasts["ODC1"]
    assert odc1.fc == pytest.approx(3.59, abs=0.1) and odc1.conclusion == "up"
    assert odc1.ci == pytest.approx((2.42, 5.33), abs=0.1)
    assert result.contrasts["NM23A"].fc == pytest.approx(2.19, abs=0.1)
    holds = {g: r.holds for g, r in result.robustness.items()}
    assert holds["ODC1"] == holds["BIRC5"] == holds["NTRK1"] == 1.0
    assert holds["NM23A"] == pytest.approx(0.645, abs=0.02)
    assert holds["PLAT"] == pytest.approx(0.973, abs=0.02)
    assert sum(h < 0.80 for h in holds.values()) == 17
    m = result.genorm.M_initial
    assert min(m.values()) == pytest.approx(1.64, abs=0.01)
    assert max(m.values()) == pytest.approx(2.03, abs=0.01)


@pytest.mark.demo_data
def test_demo_confidence(demo):
    result, _, _ = demo
    odc1, nm23a = result.confidence["ODC1"], result.confidence["NM23A"]
    assert odc1.level == "Moderate" and len(odc1.reasons) == 1
    assert "M 1.5" in odc1.reasons[0]
    assert nm23a.level == "Very low"


@pytest.mark.demo_data
def test_demo_cards(demo):
    result, cards, _ = demo
    assert [c.id for c in cards] == ["card_refset", "card_cutoff", "card_undetermined"]
    assert [c.impact["n_genes_flipped"] for c in cards] == [31, 17, 0]
    assert [c.status for c in cards] == ["open", "open", "auto_decided"]
    refset = cards[0]
    assert _fc(refset, "recommended", "ODC1") == pytest.approx(3.59, abs=0.1)
    assert _fc(refset, "hmbs_alone", "ODC1") == pytest.approx(2.66, abs=0.1)
    assert _fc(refset, "ubc_2_alone", "ODC1") == pytest.approx(4.66, abs=0.1)
    assert _fc(refset, "hprt1_alone", "ODC1") == pytest.approx(4.33, abs=0.1)
    hmbs = next(o for o in refset.options if o.id == "hmbs_alone").per_gene["NM23A"]
    assert hmbs.fc == pytest.approx(1.62, abs=0.1) and hmbs.conclusion == "none"
    for card in cards:
        assert not [f for f in card.facts if f not in result.facts], card.id
    assert result.facts["f_n_flipped_refset"].value == 31
    assert result.facts["f_worst_ref"].value == "UBC(2)"


@pytest.mark.demo_data
def test_demo_group_effect_evidence(demo):
    _, cards, _ = demo
    evidence = cards[0].evidence
    assert evidence["genorm_validated"] is False
    assert evidence["genorm_note"] == (
        "geNorm M ranks stability across all samples; it cannot show whether a control gene "
        "differs between the groups. The pairwise ratios below check that."
    )
    effect = evidence["ref_group_effect"]
    assert [p["label"] for p in effect["pairs"][:3]] == effect["flagged"]
    assert effect["flagged"] == ["HMBS:UBC(2)", "HMBS:HPRT1", "SDHA(1):UBC(2)"]
    assert effect["pairs"][0]["diff"] == pytest.approx(0.81, abs=0.03)
    assert effect["raw"]["UBC(2)"]["diff"] == pytest.approx(-0.81, abs=0.03)
    assert effect["note"] == "10 pairs, no multiple-testing correction"
    assert json.loads(json.dumps(evidence)) == evidence


@pytest.mark.demo_data
def test_demo_group_effect_facts(demo):
    result, cards, _ = demo
    facts, refset = result.facts, cards[0]
    assert [f for f in REFSET_EXTRA_FACTS if f not in refset.facts] == []
    assert facts["f_ref_pair_top"].value == "HMBS:UBC(2)"
    assert facts["f_ref_ratio_top"].value == pytest.approx(1.76, abs=0.05)
    assert facts["f_ref_ratio_top_p"].value == pytest.approx(0.058, abs=0.01)
    assert (render_fact(facts["f_ref_ratio_top"]), render_fact(facts["f_ref_ratio_top_p"])) == (
        "1.8×",
        "0.058",
    )
    assert facts["f_ref_ratio_hmbs_ubc_2"].value == facts["f_ref_ratio_top"].value
    assert facts["f_ref_ratio_hmbs_ubc_2_p"].value == facts["f_ref_ratio_top_p"].value
    assert facts["f_ref_ratio_hmbs_hprt1"].value == pytest.approx(2**0.71, abs=0.05)
    assert facts["f_ref_ratio_hmbs_hprt1_p"].value == pytest.approx(0.045, abs=0.01)
    assert facts["f_ref_ratio_sdha_1_ubc_2"].value == pytest.approx(2**0.54, abs=0.05)
    ratio_ids = [f for f in facts if f.startswith("f_ref_ratio_") and "_top" not in f]
    assert len(ratio_ids) == 2 * 10  # every pair: fold and p
    assert all(facts[f].unit == "×" for f in ratio_ids if not f.endswith("_p"))
    assert (facts["f_n_ref_pairs"].value, facts["f_n_ref_pairs_flagged"].value) == (10, 3)
    assert facts["f_ref_flag_fold"].value == pytest.approx(2**0.5)
    assert render_fact(facts["f_ref_flag_fold"]) == "1.4×"
    assert facts["f_genorm_v_min"].value == pytest.approx(0.327, abs=0.01)
    assert render_fact(facts["f_genorm_v_min"]) == "0.33"


@pytest.mark.demo_data
def test_demo_run_study_is_byte_identical(demo_rdml_path, tmp_path):
    first = write_outputs(*run_study(demo_rdml_path), tmp_path / "a")
    second = write_outputs(*run_study(demo_rdml_path), tmp_path / "b")
    for name in first:
        assert first[name].read_bytes() == second[name].read_bytes(), name


@pytest.mark.demo_data
def test_cli_run_writes_the_study(demo_rdml_path, tmp_path, capsys):
    assert main(["run", str(demo_rdml_path), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "MYCN-high 53 vs rest 294" in out
    assert "ODC1: 3.59x [2.42-5.33] up; holds in 100 % of 186 analyses" in out
    assert "1. reference_set: changes 31 of 58 conclusions; needs a human" in out
    assert (tmp_path / "grid.csv").exists()
