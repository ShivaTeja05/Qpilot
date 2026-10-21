"""N5 G-RT: the RT-replicate Cq range per biological unit × target, and the rt_replicate field.

Synthetic tables (CI) for pass, warn (the "fail" case) and not_applicable; the demo is
not_applicable because nothing annotates RT replicates.
"""

import re

import pandas as pd
import pytest

from qpilot.core.validator import validate
from qpilot.explain.evidence_text import GRT_NOT_RUN, gate_rt_text, render_gate_rt
from qpilot.qpcr.designs import (
    SHEET_OPTIONAL,
    DesignError,
    load_design,
    read_sample_sheet,
    vermeulen_design,
)
from qpilot.qpcr.gate_rt import (
    CRITERION,
    RANGE_COLUMNS,
    RT_RANGE_LIMIT,
    SOURCE,
    GateLine,
    g_rt,
    rt_replicate_range,
)
from qpilot.qpcr.quant import EXCLUDED
from qpilot.schemas_studio import Comparison, SampleDesign, StudyDesign
from tests.engine.evidence_toys import toy_design, toy_table

# Hashes captured on c3fbb16 before rt_replicate existed: a None field must not change them.
VERMEULEN_HASH = "da45de3622fc1d4bd9265eaa501e27b43c1771485868945024ab31aee01a5cbe"
GROUPS_HASH = "579108f252dc5fd4e8c860b9369cc9c22b4d67d5d27f121d52ef83519d202637"


def groups_design(**samples_update) -> StudyDesign:
    samples = {
        "A1": SampleDesign(sample="A1", group="LPS", biological_unit="mouse1"),
        "A2": SampleDesign(sample="A2", group="LPS", biological_unit="mouse1"),
        "B1": SampleDesign(sample="B1", group="PBS"),
        "B2": SampleDesign(sample="B2", group="PBS", quantity=None),
    }
    samples.update(samples_update)
    return StudyDesign(
        mode="groups",
        comparison=Comparison(group_a="LPS", group_b="PBS"),
        samples=samples,
        reference_candidates=("R1", "R2", "R3"),
    )


def wells(rows) -> pd.DataFrame:
    """A minimal per-well table: (sample, target, cq) rows, one plate per target."""
    out = []
    for i, (sample, target, cq) in enumerate(rows):
        out.append({"run_id": f"p_{target}", "well": f"A{i}", "sample": sample,
                    "sample_type": "unkn", "target": target, "cq": cq,
                    "n0": None if cq is None else 2.0 ** (40 - cq)})  # fmt: skip
    return pd.DataFrame(out)


def rt_design(labels: dict[str, tuple[str, str | None]]) -> StudyDesign:
    """Samples -> (unit, rt label); two groups so the design is valid."""
    samples = {
        s: SampleDesign(sample=s, group="A" if unit < "m3" else "B", biological_unit=unit,
                        rt_replicate=rt)
        for s, (unit, rt) in labels.items()
    }  # fmt: skip
    return StudyDesign(mode="groups", comparison=Comparison(group_a="A", group_b="B"),
                       samples=samples)  # fmt: skip


LABELS = {
    "m1_rt1": ("m1", "1"),
    "m1_rt2": ("m1", "2"),
    "m2_rt1": ("m2", "1"),
    "m2_rt2": ("m2", "2"),
    "m3_rt1": ("m3", "1"),
    "m3_rt2": ("m3", "2"),
}


def table_with(ranges: dict[str, float], target="GENE") -> pd.DataFrame:
    """RT replicate 2 of each unit sits ``ranges[unit]`` cycles after replicate 1."""
    rows = []
    for unit, spread in ranges.items():
        rows += [(f"{unit}_rt1", target, 25.0), (f"{unit}_rt2", target, 25.0 + spread)]
    return wells(rows)


# ---------- the rule ----------


def test_ranges_within_the_limit_pass():
    line = g_rt(table_with({"m1": 0.2, "m2": 0.5, "m3": 0.9}), rt_design(LABELS))
    assert isinstance(line, GateLine)
    assert (line.rule_id, line.status, line.code) == ("G-RT", "pass", "rt_within_limit")
    assert line.cycles == []
    values = {fid: f.value for fid, f in line.facts.items()}
    assert values["f_grt_n_units"] == 3 and values["f_grt_n_pairs"] == 3
    assert values["f_grt_n_over"] == 0
    assert values["f_grt_max_range"] == pytest.approx(0.9)
    assert (values["f_grt_worst_unit"], values["f_grt_worst_target"]) == ("m3", "GENE")
    assert values["f_grt_limit"] == RT_RANGE_LIMIT == 1.0


def test_a_range_at_the_limit_warns():
    line = g_rt(table_with({"m1": 0.2, "m2": 1.0, "m3": 2.4}), rt_design(LABELS))
    assert (line.status, line.code) == ("warn", "rt_over_limit")
    values = {fid: f.value for fid, f in line.facts.items()}
    assert (values["f_grt_n_over"], values["f_grt_n_pairs"]) == (2, 3)  # 1.0 is not below 1
    assert values["f_grt_worst_unit"] == "m3"
    assert values["f_grt_max_range"] == pytest.approx(2.4)


def test_no_annotation_is_not_applicable():
    table = table_with({"m1": 3.0, "m2": 3.0, "m3": 3.0})
    for design in (None, rt_design({s: (u, None) for s, (u, _) in LABELS.items()})):
        line = g_rt(table, design)
        assert (line.status, line.code) == ("not_applicable", "rt_not_annotated")
        assert line.facts["f_grt_n_units"].value == 0
        assert "f_grt_n_pairs" not in line.facts


def test_a_single_rt_label_per_unit_is_not_an_rt_replicate():
    labels = {s: (u, "1") for s, (u, _) in LABELS.items()}  # both samples of a unit: RT "1"
    line = g_rt(table_with({"m1": 3.0, "m2": 3.0, "m3": 3.0}), rt_design(labels))
    assert (line.status, line.code) == ("not_applicable", "rt_not_annotated")


def test_rt_replicates_without_a_cq_are_not_measurable():
    rows = [(f"{u}_rt1", "GENE", 25.0) for u in ("m1", "m2", "m3")]
    rows += [(f"{u}_rt2", "GENE", None) for u in ("m1", "m2", "m3")]
    line = g_rt(wells(rows), rt_design(LABELS))
    assert (line.status, line.code) == ("not_applicable", "rt_not_measurable")
    assert line.facts["f_grt_n_units"].value == 3 and line.facts["f_grt_n_pairs"].value == 0


def test_technical_replicates_are_averaged_within_an_rt_replicate():
    rows = [("m1_rt1", "G", 25.0), ("m1_rt1", "G", 25.4), ("m1_rt2", "G", 25.9),
            ("m1_rt2", "G", None), ("m2_rt1", "G", 30.0), ("m2_rt2", "G", 30.1)]  # fmt: skip
    ranges = rt_replicate_range(wells(rows), rt_design(LABELS))
    assert list(ranges.columns) == list(RANGE_COLUMNS)
    m1 = ranges[ranges["unit"] == "m1"].iloc[0]
    assert (m1["n_rt"], m1["n_measured"]) == (2, 2)
    assert m1["cq_min"] == pytest.approx(25.2) and m1["range"] == pytest.approx(0.7)
    assert g_rt(wells(rows), rt_design(LABELS)).status == "pass"


def test_ranges_are_per_unit_and_target_and_sorted():
    table = pd.concat([table_with({"m2": 0.3, "m1": 0.1}, "T2"), table_with({"m1": 1.2}, "T1")])
    ranges = rt_replicate_range(table, rt_design(LABELS))
    assert list(zip(ranges["unit"], ranges["target"], strict=True)) == [
        ("m1", "T1"), ("m1", "T2"), ("m2", "T2"),
    ]  # fmt: skip
    line = g_rt(table, rt_design(LABELS))
    assert line.status == "warn" and line.facts["f_grt_worst_target"].value == "T1"


def test_excluded_and_control_wells_are_left_out():
    table = table_with({"m1": 3.0, "m2": 0.1, "m3": 0.1})
    design = rt_design(LABELS)
    key = f"{table.iloc[1]['run_id']}/{table.iloc[1]['well']}"  # m1_rt2, the late one
    excluded = design.model_copy(update={"excluded_wells": (key,)})
    line = g_rt(table, excluded)
    assert line.facts["f_grt_n_pairs"].value == 2  # m1 has one RT replicate left
    assert line.status == "pass"
    retyped = table.assign(sample_type=["ntc"] + ["unkn"] * (len(table) - 1))
    assert g_rt(retyped, design).facts["f_grt_n_pairs"].value == 2
    with pytest.raises(DesignError):
        g_rt(table, design.model_copy(update={"excluded_wells": ("nope/A1",)}))
    assert EXCLUDED not in table.columns  # the caller's table is never changed


def test_the_limit_must_be_a_positive_number():
    table, design = table_with({"m1": 0.5}), rt_design(LABELS)
    for bad in (0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="limit_cycles"):
            g_rt(table, design, limit_cycles=bad)
    assert g_rt(table, design, limit_cycles=0.4).status == "warn"


def test_the_toy_study_passes_and_warns_with_a_wide_rt_shift():
    assert g_rt(toy_table(), toy_design()).status == "pass"
    assert g_rt(toy_table(rt_shift=1.2), toy_design()).status == "warn"


def test_the_criterion_is_cited_and_marked_to_verify():
    assert CRITERION == "RT-replicate ΔCq range < 1 cycle"
    assert "Bustin" in SOURCE["citation"] and "clinchem.2014.230615" in SOURCE["citation"]
    assert "04-preanalytics-qc-gates.md" in SOURCE["quoted_from"]
    assert SOURCE["status"].startswith("to verify against the paper")


# ---------- the text ----------


@pytest.mark.parametrize(
    ("ranges", "start"),
    [
        ({"m1": 0.2, "m2": 0.5}, "G-RT passes"),
        ({"m1": 0.2, "m2": 1.5}, "G-RT warns"),
    ],
)
def test_the_line_renders_from_its_facts(ranges, start):
    line = g_rt(table_with(ranges), rt_design(LABELS))
    text = render_gate_rt(line)
    assert text.plain.startswith(start)
    assert validate(text.tokens, line.facts).ok
    assert "{{" not in text.plain
    assert "1 cycle" in text.plain


def test_not_applicable_text_and_degrade():
    line = g_rt(table_with({"m1": 0.2}), None)
    text = render_gate_rt(line).plain
    assert (
        text == "G-RT does not apply: no RT replicates annotated, so RT variability not measured."
    )
    assert gate_rt_text({}) == GRT_NOT_RUN and not re.search(r"\d", GRT_NOT_RUN)
    rows = [("m1_rt1", "G", 25.0), ("m1_rt2", "G", None)]
    assert "no unit × target" in render_gate_rt(g_rt(wells(rows), rt_design(LABELS))).plain


def test_names_in_the_line_are_escaped_in_html():
    labels = {"<b>m1</b>_a": ("<b>m1</b>", "1"), "<b>m1</b>_b": ("<b>m1</b>", "2"),
              "m3_a": ("m3", "1"), "m3_b": ("m3", "2")}  # fmt: skip
    rows = [("<b>m1</b>_a", "G", 25.0), ("<b>m1</b>_b", "G", 27.0), ("m3_a", "G", 25.0),
            ("m3_b", "G", 25.1)]  # fmt: skip
    html = render_gate_rt(g_rt(wells(rows), rt_design(labels))).html
    assert "<b>" not in html and "&lt;b&gt;m1&lt;/b&gt;" in html


# ---------- the design field and the sample sheet ----------


def test_existing_design_hashes_are_unchanged():
    assert vermeulen_design().design_hash() == VERMEULEN_HASH
    assert groups_design().design_hash() == GROUPS_HASH
    assert "rt_replicate" not in groups_design().canonical()
    labelled = groups_design(B2=SampleDesign(sample="B2", group="PBS", rt_replicate="2"))
    assert labelled.design_hash() != GROUPS_HASH
    assert '"rt_replicate":"2"' in labelled.canonical()


def test_the_sample_sheet_reads_rt_replicate(tmp_path):
    assert "rt_replicate" in SHEET_OPTIONAL
    sheet = tmp_path / "samples.csv"
    sheet.write_text(
        "sample,group,biological_unit,RT_Replicate\nm1_a,LPS,m1,1\nm1_b,LPS,m1,2\nm2_a,PBS,m2,\n",
        encoding="utf-8",
    )
    samples = read_sample_sheet(sheet)
    assert (samples["m1_a"].rt_replicate, samples["m1_b"].rt_replicate) == ("1", "2")
    assert samples["m2_a"].rt_replicate is None
    assert samples["m1_b"].unit() == "m1"


def test_a_study_yaml_may_carry_rt_replicate(tmp_path):
    path = tmp_path / "study.yaml"
    path.write_text(
        "mode: groups\ncomparison: {group_a: LPS, group_b: PBS}\nsamples:\n"
        "  m1_a: {group: LPS, biological_unit: m1, rt_replicate: '1'}\n"
        "  m1_b: {group: LPS, biological_unit: m1, rt_replicate: '2'}\n"
        "  m2_a: {group: PBS}\n",
        encoding="utf-8",
    )
    design = load_design(path)
    assert design.samples["m1_b"].rt_replicate == "2"
    assert g_rt(table_with({"m1": 0.4}).replace({"m1_rt1": "m1_a", "m1_rt2": "m1_b"}),
                design).status == "pass"  # fmt: skip


# ---------- the demo study ----------


@pytest.mark.demo_data
def test_demo_is_not_applicable(demo_curves):
    for design in (None, vermeulen_design()):
        line = g_rt(demo_curves, design)
        assert (line.status, line.code) == ("not_applicable", "rt_not_annotated")
    assert "RT variability not measured" in render_gate_rt(line).plain
