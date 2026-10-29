"""The plate map, a well's curve and the curve calls serve the engine's per-well numbers.

Expected values come from the engine's own per-well table (LinRegPCR through
``qpilot.qpcr.curves.analyse_study``) and, for the raw fluorescence, from the RDML XML itself;
the amplification calls are recomputed here from their documented definitions
(``qpilot/qpcr/amp_call.py``: a well counts when it has a starting quantity, and a Cq rule also
needs Cq ≤ its line), not with the engine's function.
"""

from __future__ import annotations

import json
import zipfile
from collections import Counter

import pandas as pd
import pytest
from lxml import etree

from qpilot.cli.studio_cmds import EXPECTED
from qpilot.io.rdml_io import hardened_parser
from tests.conftest import DEMO_RDML
from tests.web.numbers_world import World, api_client, demo_world, get_json

pytestmark = pytest.mark.demo_data

TECHNICAL = "technical_datasets"
CQ_LINES = {"cq_le_40": 40.0, "cq_le_38": 38.0, "cq_le_35": 35.0}


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return demo_world(tmp_path_factory.getbasetemp() / "numbers-demo", DEMO_RDML)


@pytest.fixture(scope="module")
def api(world):
    with api_client(world.store) as client:
        yield client


@pytest.fixture(scope="module")
def design(world):
    return world.store.design(world.study)


@pytest.fixture(scope="module")
def engine_wells(design) -> dict[str, pd.DataFrame]:
    """The engine's per-well table for the design's experiment and for the technical one."""
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.study import StudySettings

    settings = StudySettings.from_design(design)
    return {
        design.experiment_id: analyse_study(
            DEMO_RDML, settings.experiment_id, settings.candidates, settings.curves
        ),
        TECHNICAL: analyse_study(DEMO_RDML, TECHNICAL),
    }


@pytest.fixture(scope="module")
def xml():
    """The RDML document as XML (no rdmlpython): samples' declared types, every raw curve."""
    with zipfile.ZipFile(DEMO_RDML) as archive:
        root = etree.fromstring(archive.read("rdml_data.xml"), hardened_parser())
    ns = {"r": root.nsmap[None]}
    types = {s.get("id"): s.findtext("r:type", namespaces=ns) for s in root.findall("r:sample", ns)}
    return {"root": root, "ns": ns, "types": types}


def _num(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _label(react_id: str, n_columns: int) -> str:
    """RDML react id (1-based, row-major) -> ``A1``-style well label."""
    index = int(react_id) - 1
    return f"{chr(ord('A') + index // n_columns)}{index % n_columns + 1}"


def _raw_curve(xml, run_id: str, well: str) -> list[tuple[int, float]]:
    ns = xml["ns"]
    for run in xml["root"].findall("r:experiment/r:run", ns):
        if run.get("id") != run_id:
            continue
        columns = int(run.findtext("r:pcrFormat/r:columns", namespaces=ns))
        for react in run.findall("r:react", ns):
            if _label(react.get("id"), columns) == well:
                points = react.findall("r:data/r:adp", ns)
                return [
                    (
                        int(float(p.findtext("r:cyc", namespaces=ns))),
                        float(p.findtext("r:fluor", namespaces=ns)),
                    )
                    for p in points
                ]
    raise KeyError(f"{run_id}/{well} not in the XML")


def _plates(api, world) -> dict[str, dict]:
    return {r["run_id"]: r for r in get_json(api, f"/api/sessions/{world.sid}/plate")["runs"]}


def _sampled_runs(api, world, design) -> list[str]:
    """The first plate, the plate of the round trip's excluded well, ALUsq's, a technical one."""
    runs = _plates(api, world)
    excluded = sorted({key.split("/")[0] for key in design.excluded_wells})
    alu = sorted(r for r, v in runs.items() if "ALUsq(Eurogentec)" in v["targets"])
    technical = sorted(r for r, v in runs.items() if v["experiment_id"] == TECHNICAL)
    first = next(r for r, v in runs.items() if v["in_design"])
    return list(dict.fromkeys([first, *excluded[:1], *alu[:1], *technical[:1]]))


def test_the_plate_list_is_the_file_and_the_design(api, world, design, xml):
    ns = xml["ns"]
    want = {
        run.get("id"): exp.get("id")
        for exp in xml["root"].findall("r:experiment", ns)
        for run in exp.findall("r:run", ns)
    }
    runs = _plates(api, world)
    assert {r: v["experiment_id"] for r, v in runs.items()} == want
    assert {r for r, v in runs.items() if v["in_design"]} == {
        r for r, e in want.items() if e == design.experiment_id
    }


def test_each_plate_shows_the_engine_numbers_of_every_well(api, world, design, engine_wells, xml):
    runs = _plates(api, world)
    for run_id in _sampled_runs(api, world, design):
        plate = get_json(api, f"/api/sessions/{world.sid}/plate?run={run_id}")
        assert plate["curves_shown"] is True
        table = engine_wells[runs[run_id]["experiment_id"]]
        rows = table[table["run_id"] == run_id]
        want = {
            f"{run_id}/{r.well}|{r.target}": {
                "cq": _num(r.cq),
                "efficiency": _num(r.eff_indiv),
                "r2": _num(r.r2),
                "amplified": bool(pd.notna(r.n0))
                if f"{run_id}/{r.well}" not in design.well_calls
                else bool(pd.notna(r.n0) and design.well_calls[f"{run_id}/{r.well}"]),
                "declared_type": xml["types"][r.sample] if r.sample in xml["types"] else None,
            }
            for r in rows.itertuples()
        }
        got = {
            f"{w['key']}|{w['target']}": {
                k: w[k] for k in ("cq", "efficiency", "r2", "amplified", "declared_type")
            }
            for w in plate["wells"]
        }
        assert got.keys() == want.keys(), run_id
        for key in want:
            if want[key]["declared_type"] is None:  # a sample the XML names differently
                got[key]["declared_type"] = None
        assert got == want, run_id
        excluded = {w["key"] for w in plate["wells"] if w["excluded_by_person"]}
        assert excluded == {k for k in design.excluded_wells if k.startswith(f"{run_id}/")}


def test_the_alusq_plate_shows_the_curve_judge_disagreements(api, world, design):
    """studio_cmds EXPECTED: 110 Curve Judge well calls, all on ALUsq (none accepted)."""
    runs = _plates(api, world)
    target = EXPECTED["curve_judge_target"]
    n = 0
    for run_id, run in runs.items():
        if target in run["targets"] and run["in_design"]:
            plate = get_json(api, f"/api/sessions/{world.sid}/plate?run={run_id}")
            n += sum(1 for w in plate["wells"] if w["disagrees"])
    assert n == EXPECTED["curve_judge_well_calls"]


def test_a_well_curve_is_the_file_raw_fluorescence(api, world, design, engine_wells, xml):
    runs = _plates(api, world)
    for run_id in _sampled_runs(api, world, design):
        table = engine_wells[runs[run_id]["experiment_id"]]
        rows = table[table["run_id"] == run_id]
        picks = [rows.iloc[0], rows.iloc[len(rows) // 2], rows.iloc[-1]]
        picks += [r for _, r in rows.iterrows() if f"{run_id}/{r.well}" in design.excluded_wells]
        for row in picks:
            key = f"{run_id}/{row.well}"
            view = get_json(api, f"/api/sessions/{world.sid}/curve?well={key}")
            raw = _raw_curve(xml, run_id, row.well)
            assert view["cycle"] == [c for c, _ in raw], key
            assert view["fluorescence"] == pytest.approx([f for _, f in raw], rel=0, abs=0), key
            got = {k: view[k] for k in ("cq", "efficiency", "r2", "baseline")}
            assert got == {
                "cq": _num(row.cq),
                "efficiency": _num(row.eff_indiv),
                "r2": _num(row.r2),
                "baseline": _num(row.baseline),
            }, key


def _judge(world) -> dict[str, bool]:
    path = world.store.find_session(world.sid) / "curve_judge_calls.json"
    return json.loads(path.read_text())["calls"] if path.exists() else {}


@pytest.mark.parametrize("gene", ["ODC1", "ALUsq(Eurogentec)", "MYCN(4)", "CLSTN1"])
def test_curve_calls_follow_the_rule_definitions(api, world, design, engine_wells, gene):
    view = get_json(api, f"/api/sessions/{world.sid}/curve-calls?gene={gene}")
    table = engine_wells[design.experiment_id]
    rows = table[table["target"] == gene]
    judge = _judge(world)
    want = {}
    for r in rows.itertuples():
        key = f"{r.run_id}/{r.well}"
        quantity = bool(pd.notna(r.n0))
        calls = {"linregpcr": quantity}
        for rule, line in CQ_LINES.items():
            calls[rule] = quantity and not (pd.notna(r.cq) and r.cq > line)
        if "linregpcr_call" in view["rules"]:  # science review J1: LinRegPCR's own call
            negative = r.sample_type in ("ntc", "nac", "ntp", "nrt")
            called = True if pd.isna(r.amplification) else bool(r.amplification)
            calls["linregpcr_call"] = quantity and (called or negative)
        if key in design.well_calls:
            calls = dict.fromkeys(calls, quantity and design.well_calls[key])
        if "learned" in view["rules"] and key in judge:
            calls["learned"] = judge[key]
        want[key] = {"cq": _num(r.cq), "calls": calls}
    got = {
        f"{w['run_id']}/{w['well']}": {"cq": w["cq"], "calls": w["calls"]} for w in view["wells"]
    }
    assert got == want
    assert sorted(view["disagreements"]) == sorted(
        k for k, v in want.items() if len(set(v["calls"].values())) > 1
    )


def test_the_inbox_counts_are_the_service_s_and_the_documented_ones(api, world):
    """studio_cmds EXPECTED: 131 rule proposals, 121 consistent, 9 contradicted (7 well roles),
    110 Curve Judge well calls; R² 0.707 (comp_50) and 0.694 (the ALUsq standards)."""
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.studio_service import Studio

    studio = Studio(world.store, client=ModelClient(backend=NoneBackend()))
    views = {}
    for stage in ("design", "curves"):
        view = get_json(api, f"/api/sessions/{world.sid}/proposals?stage={stage}")
        inbox = studio.inbox(world.sid, stage)
        assert sorted(p["id"] for p in view["proposals"]) == sorted(p.id for p in inbox)
        want = Counter(p.status for p in inbox)
        want.update(p.check.status for p in inbox if p.status == "proposed")
        assert view["counts"] == dict(want), stage
        views[stage] = view["proposals"]
    design = [p for p in views["design"] if p["kind"] != "stage.confirm"]
    checks = Counter(p["check"]["status"] for p in design)
    assert len(design) == EXPECTED["design_proposals"]
    assert checks["consistent"] == EXPECTED["consistent_listed"]
    assert checks["contradicted"] == EXPECTED["contradicted_left"]
    roles = [p for p in design if p["kind"] == "design.well_role"]
    assert (
        sum(p["check"]["status"] == "contradicted" for p in roles)
        == EXPECTED["well_roles_contradicted"]
    )
    series = {p["subject"]: p["check"] for p in design if p["kind"] == "design.dilution_series"}
    assert (series["comp_50"]["status"], round(series["comp_50"]["details"]["r2"], 3)) == (
        "contradicted",
        EXPECTED["comp_50_r2"],
    )
    assert (series["STD"]["status"], round(series["STD"]["details"]["r2"], 3)) == (
        "contradicted",
        EXPECTED["std_series_r2"],
    )
    consistent = sum(c["status"] == "consistent" for c in series.values())
    assert consistent >= EXPECTED["dilution_series_consistent_min"]
    calls = [p for p in views["curves"] if p["kind"] == "curve.well_call"]
    assert len(calls) == EXPECTED["curve_judge_well_calls"]
    assert all(p["subject"].startswith(EXPECTED["curve_judge_target"] + "_") for p in calls)
