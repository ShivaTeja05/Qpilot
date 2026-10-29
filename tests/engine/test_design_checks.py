"""Refute-only design checks and hard bans: synthetic pass/fail/cannot-check cases and oracles."""

import math

import numpy as np
import pandas as pd
import pytest

from qpilot.core.store import StudyStore
from qpilot.qpcr import design_checks as dc
from qpilot.qpcr import inspect as qinspect
from qpilot.qpcr.design_checks import (
    DeclaredDesign,
    assemble_roles,
    check_proposal,
    check_with_facts,
    coverage_check,
    hard_ban,
    nguard_check,
    ntc_check,
    register_declared,
    replicate_check,
    replicate_tolerance,
    series_check,
    standard_role_check,
    symbol_check,
)
from qpilot.qpcr.inspect import file_facts
from qpilot.schemas_studio import MadeBy, Proposal
from tests.fixtures.studio.studio_mini import INJECTION, write_studio_mini

CHECKS = []  # every ProposalCheck made in this module, for the no-digits-in-notes test


def kept(check):
    CHECKS.append(check)
    return check


def wells(*groups):
    """Rows of a curve table from (sample, cqs, options) groups; ``None`` in cqs = no Cq."""
    rows = []
    n = 0
    for sample, cqs, *rest in groups:
        opts = rest[0] if rest else {}
        for i, cq in enumerate(cqs):
            n += 1
            amp = opts.get("amp", cq is not None)
            amp = amp[i] if isinstance(amp, list) else amp
            rows.append(
                {
                    "experiment_id": "exp",
                    "run_id": opts.get("run", "P1"),
                    "well": f"W{n}",
                    "sample": sample,
                    "sample_type": opts.get("type", "unkn"),
                    "target": opts.get("target", "T"),
                    "cq": np.nan if cq is None else float(cq),
                    "amplification": bool(amp),
                    "eff_target": opts.get("eff", 1.9),
                    "eff_indiv": opts.get("eff", 1.9),
                }
            )
    columns = ["experiment_id", "run_id", "well", "sample", "sample_type", "target", "cq"]
    columns += ["amplification", "eff_target", "eff_indiv"]
    return pd.DataFrame(rows, columns=columns)


def line(quantities, efficiency=2.0, intercept=35.0, noise=None):
    slope = -1.0 / math.log10(efficiency)
    noise = noise or [0.0] * len(quantities)
    return [intercept + slope * math.log10(q) + e for q, e in zip(quantities, noise, strict=True)]


# ---- D-SERIES -----------------------------------------------------------------------------


QTY = {"L1": 1.0, "L2": 10.0, "L3": 100.0, "L4": 1000.0}


def series_wells(efficiency=2.0, scramble=False, top_amplifies=True):
    groups = []
    cqs = dict(zip(QTY, line(list(QTY.values()), efficiency), strict=True))
    if scramble:
        cqs = {"L1": 25.0, "L2": 31.0, "L3": 22.0, "L4": 30.0}
    for sample, cq in cqs.items():
        amp = top_amplifies or sample != "L4"
        groups.append((sample, [cq - 0.05, cq, cq + 0.05], {"amp": amp}))
    return wells(*groups)


def test_series_on_a_line_is_consistent():
    check = kept(series_check(series_wells(), QTY))
    assert check.status == "consistent" and check.rule_ids == ["D-SERIES"]
    assert check.details["r2"] > 0.99
    assert check.details["amplification_factor"] == pytest.approx(2.0, abs=0.01)
    assert check.details["efficiency_warning"] is False


def test_series_off_the_line_is_contradicted():
    check = kept(series_check(series_wells(scramble=True), QTY))
    assert check.status == "contradicted" and check.details["r2"] < 0.98


def test_low_efficiency_is_a_warning_not_a_contradiction():
    check = kept(series_check(series_wells(efficiency=1.6), QTY))
    assert check.status == "consistent"
    assert check.details["efficiency_warning"] is True
    assert check.details["efficiency"] == pytest.approx(0.6, abs=0.01)
    assert "warning" in check.note


def test_levels_without_amplification_are_left_out_with_their_late_cqs():
    table = series_wells(top_amplifies=False)
    table.loc[table["sample"] == "L4", "cq"] = 41.0  # late artefacts, not amplified
    check = kept(series_check(table, QTY))
    assert check.status == "consistent"
    assert check.details["levels_without_amplification"] == [1000.0]
    assert check.details["fits"][0]["n_late_cq_not_counted"] == 3


def test_a_level_counts_when_a_sibling_series_amplified_there():
    own = series_wells(top_amplifies=False)
    sibling = series_wells().assign(sample=lambda t: "S_" + t["sample"])
    pool = pd.concat([own, sibling], ignore_index=True)
    sib_qty = {f"S_{k}": v for k, v in QTY.items()}
    check = kept(series_check(own, QTY, pool=pool, pool_quantities=sib_qty))
    assert check.details["levels_without_amplification"] == []
    assert check.details["levels_used"] == [1.0, 10.0, 100.0, 1000.0]


def test_series_with_two_levels_cannot_be_checked():
    check = kept(series_check(series_wells(), {"L1": 1.0, "L2": 10.0}))
    assert check.status == "cannot_check"


def test_series_naming_absent_samples_is_contradicted():
    check = kept(series_check(series_wells(), {**QTY, "ghost": 5.0}))
    assert check.status == "contradicted" and check.details["missing_samples"] == ["ghost"]


def test_standard_role_needs_amplification():
    good = kept(standard_role_check(wells(("S", [20.0, 20.1]))))
    assert good.status == "consistent"
    late = wells(("S", [41.0, None], {"amp": False}))
    bad = kept(standard_role_check(late))
    assert bad.status == "contradicted" and bad.details["n_with_cq"] == 1
    level = wells(("S2", [22.0]))
    rescued = kept(standard_role_check(late, level_wells=level))
    assert rescued.status == "consistent"
    assert kept(standard_role_check(wells())).status == "cannot_check"


# ---- D-NTC -------------------------------------------------------------------------------

PLATE = [("U1", [20.0, 20.2]), ("U2", [22.0, 22.4])]  # unknown median 21.1


def test_ntc_amplifying_like_a_sample_is_contradicted():
    control = wells(("N", [23.0, None], {"type": "ntc"}))
    check = kept(ntc_check(control, pd.concat([wells(*PLATE), control])))
    assert check.status == "contradicted" and check.rule_ids == ["D-NTC"]
    assert check.details["n_like_sample"] == 1
    assert check.details["min_gap_cycles"] == pytest.approx(1.9)


def test_late_ntc_is_consistent_with_a_note():
    control = wells(("N", [33.0, None], {"type": "ntc"}))
    check = kept(ntc_check(control, pd.concat([wells(*PLATE), control])))
    assert check.status == "consistent" and check.details["n_late"] == 1
    assert "primer-dimer" in check.note


def test_quiet_ntc_is_consistent():
    control = wells(("N", [None, None], {"type": "ntc"}))
    check = kept(ntc_check(control, pd.concat([wells(*PLATE), control])))
    assert check.status == "consistent" and check.details["n_clean"] == 2


def test_cq_without_amplification_call_is_consistent():
    control = wells(("N", [39.0], {"type": "ntc", "amp": False}))
    check = kept(ntc_check(control, pd.concat([wells(*PLATE), control])))
    assert check.status == "consistent"
    assert check.details["n_cq_without_amplification_call"] == 1


def test_ntc_without_unknowns_to_compare_cannot_be_checked():
    control = wells(("N", [23.0], {"type": "ntc"}))
    standards = wells(("S", [20.0], {"type": "std"}))
    check = kept(ntc_check(control, pd.concat([standards, control])))
    assert check.status == "cannot_check"


def test_ntc_uses_the_design_roles_not_only_declared_types():
    control = wells(("N", [23.0], {"type": "ntc"}))
    plate = pd.concat([wells(*PLATE), control])
    retyped = {"U1": "std", "U2": "std"}  # the person accepted them as standards
    assert kept(ntc_check(control, plate, retyped)).status == "cannot_check"


# ---- D-REP -------------------------------------------------------------------------------


def test_replicate_tolerance_matches_the_source():
    assert replicate_tolerance(1.9) == pytest.approx(0.49, abs=0.01)  # the 0.5-cycle rule
    assert replicate_tolerance(1.9, 3) == pytest.approx(1.95, abs=0.01)  # ~2 cycles near 3 copies
    assert replicate_tolerance(1.9, 32) == pytest.approx(0.76, abs=0.01)  # the spec's example
    with pytest.raises(ValueError):
        replicate_tolerance(1.0)


def test_replicates_within_tolerance_are_consistent():
    check = kept(replicate_check(wells(("S", [25.0, 25.2, 25.1]))))
    assert check.status == "consistent" and check.details["n_over_tolerance"] == 0


def test_replicate_spread_at_known_copies_is_contradicted():
    table = wells(("S", [25.0, 26.2, 25.1]))
    check = kept(replicate_check(table, {"S": 1000.0}))
    assert check.status == "contradicted"
    assert check.details["over_tolerance"][0]["tolerance"] < 1.2


def test_replicate_spread_without_copies_is_only_a_warning():
    check = kept(replicate_check(wells(("S", [25.0, 26.2, 25.1]))))
    assert check.status == "consistent" and check.details["warning"] is True
    assert "warning" in check.note


def test_a_few_excursions_among_many_plates_are_a_warning():
    groups = [("S", [25.0, 25.1, 25.2], {"run": f"P{i}"}) for i in range(9)]
    groups.append(("S", [25.0, 27.0, 25.1], {"run": "P9"}))
    check = kept(replicate_check(wells(*groups), {"S": 1000.0}))
    assert check.status == "consistent" and check.details["n_over_tolerance"] == 1


def test_replicates_cannot_be_checked_without_two_amplified_wells():
    check = kept(replicate_check(wells(("S", [25.0, None]))))
    assert check.status == "cannot_check"


# ---- D-SYMBOL ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "symbol", "status"),
    [
        ("MYCN(4)", "MYCN", "consistent"),
        # a name that does not by itself name one gene cannot confirm the symbol proposed for
        # it (the lookup that made the proposal would confirm itself): a person confirms
        ("1-Mar", "MARCHF1", "cannot_check"),  # Excel's date for MARCHF1, MTARC1 and RTL1
        ("1-Mar", "MTARC1", "cannot_check"),
        ("comp_primer", "MYCN", "cannot_check"),  # not a gene name
        ("NMYC", "NMYC", "contradicted"),  # a previous symbol, not the approved one
        ("TP53", "p53", "contradicted"),  # an alias
        ("SEPT2", "2-Sep", "contradicted"),  # a date
        ("MYCN", "MYC", "contradicted"),  # the name points to another gene
        ("ALUsq(Eurogentec)", "ALU", "cannot_check"),  # HGNC does not know ALU
        ("ALUsq(Eurogentec)", "GAPDH", "contradicted"),  # a repeat assay has no symbol
        ("Actb", "Actb", "cannot_check"),  # matches only ignoring case
        ("geneX", "XYZ999", "cannot_check"),
    ],
)
def test_symbol_check(name, symbol, status):
    check = kept(symbol_check(name, symbol))
    assert check.status == status and check.rule_ids == ["D-SYMBOL"]


# ---- D-COVER and D-NGUARD ----------------------------------------------------------------

RULE = MadeBy(kind="rule")


def proposal(kind, subject, payload, status="proposed", study="abcdef12", by=RULE, pid=""):
    return Proposal(
        id=pid,
        study_id=study,
        kind=kind,
        subject=subject,
        payload=payload,
        made_by=by,
        status=status,
    )


def test_coverage_every_well_one_role():
    table = wells(("A", [20.0, 21.0]), ("N", [None], {"type": "ntc"}))
    types = {"A": (("unkn", ""),), "N": (("ntc", ""),)}
    roles = assemble_roles(types, table)
    assert kept(coverage_check(roles)).status == "consistent"
    conflicting = [
        proposal("design.well_role", "A", {"role": "std"}, "accepted"),
        proposal("design.well_role", "A", {"role": "pos"}, "accepted"),
    ]
    roles = assemble_roles(types, table, conflicting)
    check = kept(coverage_check(roles, [("P1", "W1", "T")]))
    assert check.status == "contradicted" and check.details["n_with_several_roles"] == 2
    assert kept(coverage_check(roles, [])).status == "contradicted"


def test_a_multiplex_well_may_hold_one_role_per_target():
    table = pd.concat(
        [wells(("A", [20.0], {"target": "X"})), wells(("A", [21.0], {"target": "Y"}))]
    )
    roles = assemble_roles({"A": (("pos", "X"), ("unkn", ""))}, table)
    assert roles == {("P1", "W1", "X"): {"pos"}, ("P1", "W1", "Y"): {"unkn"}}
    assert kept(coverage_check(roles)).status == "consistent"


def test_well_level_roles_override_sample_level_roles():
    table = wells(("A", [20.0, 21.0]))
    roles = assemble_roles(
        {"A": (("unkn", ""),)},
        table,
        [
            proposal("design.well_role", "A", {"role": "std"}, "accepted"),
            proposal("design.well_role", "P1/W2", {"role": "unkn"}, "accepted"),
        ],
    )
    assert roles == {("P1", "W1", "T"): {"std"}, ("P1", "W2", "T"): {"unkn"}}


def test_nguard():
    groups = {"a1": "WT", "a2": "WT", "a3": "WT", "b1": "KO", "b2": "KO"}
    ok = kept(nguard_check("WT", "KO", groups, {}))
    assert ok.status == "consistent" and ok.details == {
        "n_units_a": 3,
        "n_units_b": 2,
        "min_units": 2,
    }
    one_unit = {"b1": "M9", "b2": "M9"}  # two cDNA preparations of one animal
    bad = kept(nguard_check("WT", "KO", groups, one_unit))
    assert bad.status == "contradicted" and "withheld" in bad.note
    controls = kept(nguard_check("WT", "KO", groups, {}, {"b2": "ntc"}))
    assert controls.status == "contradicted"
    assert kept(nguard_check("WT", "HET", groups, {})).status == "cannot_check"
    assert kept(nguard_check("WT", "WT", groups, {})).status == "contradicted"


# ---- hard bans ---------------------------------------------------------------------------

DECLARED = DeclaredDesign(
    controls=frozenset({"NTC", "noRT"}),
    control_wells=frozenset({"P1/A1", "P1/A2"}),
    well_samples={"P1/A1": "NTC", "P1/A2": "noRT", "P1/B1": "S1", "P1/B2": "S2"},
    sheet_units={"S1": "M1", "S2": "M1", "S3": "M2"},
)


@pytest.fixture
def declared():
    register_declared("abcdef12", DECLARED)
    yield
    dc._DECLARED.pop("abcdef12", None)


@pytest.mark.parametrize(
    "made_by",
    [MadeBy(kind="rule"), MadeBy(kind="agent", agent="mcp"), MadeBy(kind="model", model="m")],
)
def test_declared_controls_are_never_demoted_by_anyone(declared, made_by):
    for role in ("unkn", "std", "pos"):
        assert hard_ban(proposal("design.well_role", "NTC", {"role": role}, by=made_by), [])
    assert hard_ban(proposal("design.well_role", "P1/A2", {"role": "unkn"}, by=made_by), [])
    assert hard_ban(
        proposal("design.dilution_series", "x", {"samples": {"NTC": 1, "S1": 2}}, by=made_by), []
    )
    assert hard_ban(proposal("design.group", "noRT", {"group": "WT"}, by=made_by), [])
    # a control may become another control, and samples may be typed freely
    assert hard_ban(proposal("design.well_role", "NTC", {"role": "nrt"}, by=made_by), []) is None
    assert hard_ban(proposal("design.well_role", "S1", {"role": "std"}, by=made_by), []) is None


def test_accepted_controls_and_edits_count(declared):
    accepted = proposal("design.well_role", "S4", {"role": "ntc"}, "accepted")  # no id yet
    assert hard_ban(proposal("design.well_role", "S4", {"role": "unkn"}), [accepted])
    pending = proposal("design.well_role", "S5", {"role": "ntc"}, "proposed", pid="p2")
    assert hard_ban(proposal("design.well_role", "S5", {"role": "unkn"}), [pending]) is None
    edited = proposal("design.well_role", "NTC", {"role": "ntc"})
    edited.edits = {"role": "unkn"}  # an edit that would demote is refused too
    assert hard_ban(edited, [])


def test_confirmed_units_are_never_merged_or_split(declared):
    split = hard_ban(proposal("design.bio_unit", "S1", {"biological_unit": "M7"}), [])
    assert split and "splits" in split
    merge = hard_ban(proposal("design.bio_unit", "S1", {"biological_unit": "M2"}), [])
    assert merge and "merges" in merge
    assert hard_ban(proposal("design.bio_unit", "S1", {"biological_unit": "M1"}), []) is None
    assert hard_ban(proposal("design.bio_unit", "S9", {"biological_unit": "M1"}), []) is None
    accepted = proposal("design.bio_unit", "S9", {"biological_unit": "M5"}, "accepted")
    assert hard_ban(proposal("design.bio_unit", "S9", {"biological_unit": "M6"}), [accepted])


def test_unknown_input_fails_closed_for_demotions():
    lost = proposal("design.well_role", "X", {"role": "unkn"}, study="feedfacecafe")
    assert "has not read" in hard_ban(lost, [])
    assert (
        hard_ban(proposal("design.well_role", "X", {"role": "ntc"}, study="feedfacecafe"), [])
        is None
    )
    assert hard_ban(proposal("design.group", "X", {"group": "a"}, study="feedfacecafe"), []) is None


def test_resolver_lets_hard_ban_read_the_input(tmp_path):
    path = write_studio_mini(tmp_path / "mini.rdml")
    qinspect.clear_cache()
    dc.set_input_resolver(lambda study_id: path if study_id == "session-1" else None)
    try:
        refused = hard_ban(
            proposal("design.well_role", "NTC", {"role": "unkn"}, study="session-1"), []
        )
        assert refused and "control" in refused
        allowed = proposal("design.well_role", "water", {"role": "ntc"}, study="session-1")
        assert hard_ban(allowed, []) is None
    finally:
        dc.set_input_resolver(None)
        dc._DECLARED.pop("session-1", None)


# ---- check_proposal on the synthetic file ------------------------------------------------


@pytest.fixture
def mini(tmp_path):
    qinspect.clear_cache()
    path = write_studio_mini(tmp_path / "mini.rdml")
    yield path
    qinspect.clear_cache()


def test_check_proposal_without_an_input_cannot_check(tmp_path):
    store = StudyStore(tmp_path / "studies")
    check = kept(
        check_proposal(proposal("design.well_role", "A", {"role": "ntc"}), store, "abcdef")
    )
    assert check.status == "cannot_check" and "not available" in check.note


def test_check_proposal_on_the_synthetic_file(mini, tmp_path):
    store = StudyStore(tmp_path / "studies")

    def check(kind, subject, payload, accepted=None):
        p = proposal(kind, subject, payload, study="mini01")
        return kept(check_proposal(p, store, "mini01", rdml_path=mini, accepted=accepted))

    water = check("design.well_role", "water", {"role": "ntc"})
    assert water.status == "consistent" and water.rule_ids[0] == "D-NTC"
    ntc = check("design.well_role", "NTC", {"role": "ntc"})
    assert ntc.status == "consistent" and ntc.details["n_late"] == 1
    # the sample named like an instruction amplifies like any sample: as an NTC it is refuted
    injected = check("design.well_role", INJECTION, {"role": "ntc"})
    assert injected.status == "contradicted" and injected.details["n_like_sample"] == 6
    series = check(
        "design.dilution_series",
        "STD",
        {
            "experiment_id": "mini_set",
            "samples": {"STD_100": 100, "STD_1000": 1000, "STD_10000": 1e4},
        },
    )
    assert series.status == "consistent" and series.details["n_fits"] == 2
    assert series.details["r2"] > 0.99
    assert check("design.well_role", "ghost", {"role": "std"}).status == "contradicted"
    symbol = check("design.gene_symbol", "1-Mar", {"symbol": "MARCHF1"})
    assert symbol.status == "cannot_check"  # 1-Mar is Excel's date for several genes
    assert "MARCHF1" in symbol.details["name_candidates"]
    assert check("design.gene_symbol", "GAPDH", {"symbol": "ACTB"}).status == "contradicted"
    accepted = [
        proposal("design.group", s, {"group": g}, "accepted")
        for s, g in (("WT_1", "WT"), ("WT_2", "WT"), ("KO_1", "KO"), ("KO_2", "KO"))
    ]
    fine = check("design.comparison", "comparison", {"group_a": "KO", "group_b": "WT"}, accepted)
    assert fine.status == "consistent"
    merged = [
        *accepted,
        *(
            proposal("design.bio_unit", s, {"biological_unit": "M1"}, "accepted")
            for s in ("KO_1", "KO_2")
        ),
    ]
    guarded = check("design.comparison", "comparison", {"group_a": "KO", "group_b": "WT"}, merged)
    assert guarded.status == "contradicted" and guarded.rule_ids == ["D-NGUARD"]
    assert check("curve.call_rule", "amp_call", {"rule": "linregpcr"}).status == "cannot_check"
    # check_proposal registered the input for the hard bans
    assert hard_ban(proposal("design.well_role", "NTC", {"role": "unkn"}, study="mini01"), [])


def test_instruction_name_gets_the_same_checks_as_a_clean_name(tmp_path):
    store = StudyStore(tmp_path / "studies")
    clean = write_studio_mini(tmp_path / "clean.rdml", rename={INJECTION: "S7"})
    injected = write_studio_mini(tmp_path / "injected.rdml")
    qinspect.clear_cache()
    a = check_proposal(
        proposal("design.well_role", "S7", {"role": "std"}), store, "x1", rdml_path=clean
    )
    b = check_proposal(
        proposal("design.well_role", INJECTION, {"role": "std"}), store, "x2", rdml_path=injected
    )
    assert (a.status, a.rule_ids, a.note) == (b.status, b.rule_ids, b.note)
    assert a.details["n_amplified"] == b.details["n_amplified"] == 6


def _every_kind_of_note():
    """One check per outcome of every rule, independent of test order."""
    control = wells(("N", [23.0, 33.0, 39.0, None], {"type": "ntc", "amp": [1, 1, 0, 0]}))
    plate = pd.concat([wells(*PLATE), control])
    return [
        series_check(series_wells(), QTY),
        series_check(series_wells(efficiency=1.6), QTY),
        series_check(series_wells(scramble=True), QTY),
        series_check(series_wells(), {"L1": 1.0}),
        series_check(series_wells(), {"ghost": 1.0}),
        standard_role_check(wells(("S", [20.0]))),
        standard_role_check(wells(("S", [None]))),
        ntc_check(control, plate),
        ntc_check(control.iloc[1:], plate),
        ntc_check(wells(("N", [23.0], {"type": "ntc"})), wells(("N", [23.0], {"type": "ntc"}))),
        replicate_check(wells(("S", [25.0, 26.2, 25.1])), {"S": 1000.0}),
        replicate_check(wells(("S", [25.0, 26.2, 25.1]))),
        replicate_check(wells(("S", [25.0]))),
        *(symbol_check("MYCN", s) for s in ("MYCN", "MYC", "NMYC", "1-Mar", "XYZ999", "Mycn")),
        nguard_check("A", "B", {"a": "A", "b": "B"}, {}),
        nguard_check("A", "B", {}, {}),
        coverage_check({"P/W": {"unkn", "std"}}),
    ]


def test_notes_never_carry_digits():
    for check in [*CHECKS, *_every_kind_of_note()]:
        assert not any(ch.isdigit() for ch in check.note), check.note


# ---- demo oracles (docs/studio-measured.md, plan step 3.3) --------------------------------


@pytest.fixture(scope="module")
def demo_facts():
    from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir

    path = default_cache_dir() / VERMEULEN_FILENAME
    if not path.exists():
        pytest.skip("demo dataset not cached")
    return file_facts(path)


COMPETIMER_R2 = {
    "comp_00": 0.9986,
    "comp_05": 0.9929,
    "comp_10": 0.9915,
    "comp_20": 0.9908,
    "comp_30": 0.9826,
    "comp_40": 0.9932,
}
COMPETIMER_E = [1.86, 1.80, 1.76, 1.64, 1.47, 1.40, 1.38]


def _series_proposal(series_id):
    levels = ("0.0625", "0.25", "1.0", "4.0", "16.0", "64.0")
    samples = {f"{series_id}_conc_{q}": float(q) for q in levels}
    return proposal(
        "design.dilution_series",
        series_id,
        {"experiment_id": "technical_datasets", "samples": samples},
        study="bc1d233e",
    )


@pytest.mark.demo_data
def test_demo_competimer_series_oracle(demo_facts):
    factors = []
    for series_id, r2 in COMPETIMER_R2.items():
        check = check_with_facts(_series_proposal(series_id), demo_facts)
        assert check.status == "consistent", series_id
        assert check.details["r2"] == pytest.approx(r2, abs=5e-4)
        assert check.details["levels_used"] == [0.0625, 0.25, 1.0, 4.0, 16.0]
        assert check.details["levels_without_amplification"] == [64.0]
        assert check.details["efficiency_warning"] is True  # every level outside 90-110 %
        factors.append(check.details["amplification_factor"])
    comp50 = check_with_facts(_series_proposal("comp_50"), demo_facts)
    assert comp50.status == "contradicted"
    assert comp50.details["r2"] == pytest.approx(0.707, abs=5e-4)
    factors.append(comp50.details["amplification_factor"])
    assert factors == pytest.approx(COMPETIMER_E, abs=0.01)


@pytest.mark.demo_data
def test_demo_top_level_has_no_amplified_well(demo_facts):
    wells = demo_facts.wells
    top = wells[wells["sample"].str.endswith("_conc_64.0")]
    assert len(top) == 21 and int(top["amplification"].sum()) == 0
    late = top[top["cq"].notna()]
    assert len(late) == 7 and late["cq"].between(39.8, 42.1).all()
    for series_id in ("00", "05", "10", "20", "30", "40", "50"):
        p = proposal(
            "design.well_role", f"comp_{series_id}_conc_64.0", {"role": "std"}, study="bc1d233e"
        )
        check = check_with_facts(p, demo_facts)
        assert check.status == "contradicted"
        assert check.details["n_level_wells"] == 21 and check.details["n_level_amplified"] == 0
    low = check_with_facts(
        proposal("design.well_role", "comp_00_conc_1.0", {"role": "std"}, study="bc1d233e"),
        demo_facts,
    )
    assert low.status == "consistent"


@pytest.mark.demo_data
def test_demo_competimer_ntcs(demo_facts):
    """Measured: every competimer NTC amplifies at least nine cycles after the plate's unknowns
    (median Cq 13.74) or, for comp_50_NTC, has a late TD0 without an amplification call."""
    gaps = {}
    for series_id in ("00", "05", "10", "20", "30", "40", "50"):
        p = proposal("design.well_role", f"comp_{series_id}_NTC", {"role": "ntc"}, study="bc1d233e")
        check = check_with_facts(p, demo_facts)
        assert check.status == "consistent"
        gaps[series_id] = check.details["min_gap_cycles"]
    assert gaps["00"] == pytest.approx(9.09, abs=0.01)
    assert gaps["50"] is None
    comp50 = check_with_facts(
        proposal("design.well_role", "comp_50_NTC", {"role": "ntc"}, study="bc1d233e"), demo_facts
    )
    assert comp50.details["n_cq_without_amplification_call"] == 3
    notes = demo_facts.wells.loc[demo_facts.wells["sample"] == "comp_50_NTC", "note"]
    assert notes.str.contains("TD0 found in negative control").all()


@pytest.mark.demo_data
def test_demo_water_ntc_wells(demo_facts):
    """The 192 'water' NTC wells of the biomarker set: 23 amplify, all late (add_plan 3.12)."""
    check = check_with_facts(
        proposal("design.well_role", "water", {"role": "ntc"}, study="bc1d233e"), demo_facts
    )
    assert check.status == "consistent"
    assert check.details["n_wells"] == 192 and check.details["n_late"] == 23
    assert check.details["n_like_sample"] == 0
    assert check.details["min_gap_cycles"] > 5


# ---- D-CURVE: LinRegPCR refutes a well call only when its fit is unambiguous ----------------


def _curve_wells():
    import pandas as pd

    nan = float("nan")
    return pd.DataFrame(
        {
            "run_id": ["p1", "p1", "p1", "p1"],
            "well": ["A1", "A2", "A3", "A4"],
            "sample": ["s1", "s2", "s3", "s4"],
            "amplification": [True, False, True, False],
            "plateau": [True, False, False, True],
            "n0": [120.0, nan, 3.0, 0.5],
            "cq": [11.2, nan, 37.9, 41.0],
            "eff_indiv": [1.92, nan, 1.6, 1.1],
        }
    )


def test_curve_check_refutes_only_unambiguous_disagreements():
    from qpilot.qpcr.design_checks import curve_check

    wells = _curve_wells()
    full = curve_check("p1/A1", {"amplified": False}, wells)
    assert full.status == "contradicted" and full.rule_ids == ["D-CURVE"]
    assert full.details["cq"] == 11.2
    assert curve_check("p1/A1", {"amplified": True}, wells).status == "consistent"
    assert curve_check("p1/A2", {"amplified": True}, wells).status == "contradicted"
    assert curve_check("p1/A2", {"amplified": False}, wells).status == "consistent"
    for well in ("p1/A3", "p1/A4"):  # late, no plateau, or a quantity without LinRegPCR's call
        for claim in (True, False):
            assert curve_check(well, {"amplified": claim}, wells).status == "consistent"


def test_curve_check_refuses_bad_subjects_and_payloads():
    from qpilot.qpcr.design_checks import curve_check

    wells = _curve_wells()
    assert curve_check("A1", {"amplified": True}, wells).status == "contradicted"
    assert curve_check("p1/H12", {"amplified": True}, wells).rule_ids == ["D-COVER"]
    assert curve_check("p1/A1", {"amplified": "yes"}, wells).status == "contradicted"
