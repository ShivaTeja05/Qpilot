"""What to repeat and why (the Run Review's repeat plan) and the repeat plate, over HTTP.

The mini file with both knock-outs late on ``1-Mar`` (the gene is called down) and an early
no-template control on that plate (``tests/web/test_where_decide.py``): the Run Gate's G-NTC-1
points at the knock-outs' 1-Mar wells, and Trace points at the same wells (S6). The plan:

* lists each knock-out x 1-Mar once, with both reasons in words, as changing a call (leaving
  its value out changes 1-Mar's call), ranked first;
* lays out the repeat plate in the planner's CSV: every repeated sample with the reference
  gene, and per assay the inter-run calibrator (a compared sample nothing points at), the no-RT
  and the no-template controls; the CSV route serves the same rows;
* after a person sets a value aside from Trace, lists it with the person's reason;
* gives the Run Gate's lines per plate, and the Run Review no longer says "not built".
"""

from __future__ import annotations

import csv
import io

import pytest

from qpilot.qpcr import layout as lay
from qpilot.web.routers import evidence as evidence_router
from tests.web import test_where_decide as decided

called_walked = decided.called_walked
called = decided.called
GENE = decided.GENE


@pytest.fixture(autouse=True)
def fresh_plans():
    evidence_router.clear()
    yield
    evidence_router.clear()


def repeat(c, study: str, include: str = "consequential") -> dict:
    """The repeat plan, waiting out the first read of the study (Trace, then the Run Gate)."""
    from tests.web.conftest import wait_job

    for _ in range(200):
        r = c.get(f"/api/studies/{study}/review/repeat", params={"include": include})
        if r.status_code == 409 and r.json()["error"]["code"] == "loading":
            wait_job(c, r.json()["error"]["details"]["job"])
            continue
        assert r.status_code == 200, r.text
        return r.json()
    raise AssertionError("never ready")


def test_the_plan_lists_each_reaction_once_with_every_reason_ranked_by_consequence(called):
    c, study = called["client"], called["study"]
    view = repeat(c, study)
    plan = view["plan"]
    assert view["study_id"] == study and view["session"] == called["sid"]
    assert view["include"] == "consequential" and "your call" in view["note"]
    top = plan["items"][:2]
    assert {(i["sample"], i["target"]) for i in top} == {("KO_1", GENE), ("KO_2", GENE)}
    for item in top:
        assert item["consequence"] == "changes_call" and item["changed_calls"] == [GENE]
        assert item["scope"] == "reaction" and item["on_plate"] and item["repeat"] == [GENE]
        sources = {r["source"] for r in item["reasons"]}
        assert {"run_gate", "trace"} <= sources
        gate = next(r for r in item["reasons"] if r["source"] == "run_gate")
        assert gate["code"] == "G-NTC-1" and "{{" not in gate["words"]  # rendered, in words
        trace = next(r for r in item["reasons"] if r["source"] == "trace")
        assert trace["code"] == "S6" and trace["what_to_check"]
        assert len(item["wells"]) == 3 and item["plates"] == [item["wells"][0].split("/")[0]]
    ranks = [i["rank"] for i in plan["items"]]
    assert ranks == list(range(1, len(ranks) + 1))
    order = ["changes_call", "beyond_ci", "no_value", "unknown", "changes_nothing"]
    shown = [order.index(i["consequence"]) for i in plan["items"]]
    assert shown == sorted(shown)
    assert plan["counts"]["changes_call"] >= 2


def test_the_repeat_plate_carries_the_references_the_calibrator_and_the_controls(called):
    c, study = called["client"], called["study"]
    view = repeat(c, study)
    plan = view["plan"]
    wells = plan["wells"]
    assert plan["n_plates"] == 1 and plan["plate_size"] == 96 and plan["n_wells"] == len(wells)
    assert plan["replicates"] == 3  # the study's own triplicates
    samples = {(w["sample"], w["target"]) for w in wells if w["type"] == "unkn"}
    assert samples == {("KO_1", GENE), ("KO_1", "GAPDH"), ("KO_2", GENE), ("KO_2", "GAPDH")}
    assert plan["n_samples"] == 2 and plan["n_reactions"] == 4
    cal = plan["calibrator"]
    assert (
        cal
        and cal not in {"KO_1", "KO_2"}
        and cal in {"WT_1", "WT_2"} | {w["sample"] for w in wells}
    )
    for target in (GENE, "GAPDH"):
        kinds = [w["type"] for w in wells if w["target"] == target]
        assert kinds.count("unkn") == 2 * 3 and kinds.count("pos") == 3  # calibrator x 3
        assert kinds.count("nrt") == 1 and kinds.count("ntc") == 1
    assert {w["sample"] for w in wells if w["type"] == "pos"} == {cal}
    assert len({w["well"] for w in wells}) == len(wells)  # each well once
    assert any("inter-run calibrator" in n for n in plan["notes"])
    # the CSV is the planner's format, the same rows
    r = c.get(view["csv_url"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert view["csv_name"] in r.headers["content-disposition"]
    rows = lay.read_layout_csv(r.text)
    assert [(p, w, s, g, t, k) for p, w, s, g, t, k in rows] == [
        (x["plate"], x["well"], x["sample"], x["group"], x["target"], x["type"]) for x in wells
    ]
    header = next(csv.reader(io.StringIO(r.text)))
    assert tuple(header) == lay.CSV_COLUMNS


def test_every_item_goes_on_the_plate_when_asked(called):
    c, study = called["client"], called["study"]
    some = repeat(c, study)["plan"]
    every = repeat(c, study, include="all")["plan"]
    assert len(every["items"]) == len(some["items"])
    quiet = [i for i in every["items"] if i["consequence"] == "changes_nothing" and i["repeat"]]
    assert all(i["on_plate"] for i in every["items"] if i["repeat"])
    assert not any(i["on_plate"] for i in some["items"] if i["consequence"] == "changes_nothing")
    assert every["n_wells"] >= some["n_wells"] and (not quiet or every["n_wells"] > 0)


def test_a_value_set_aside_from_trace_is_listed_with_the_persons_reason(called):
    c, sid, study = called["client"], called["sid"], called["study"]
    view = decided.where(c, study, gene=GENE)
    done = decided.decide(c, study, view, "set_aside_value").json()
    new = decided.analysed(c, sid, done)
    plan = repeat(c, new)["plan"]
    item = next(i for i in plan["items"] if (i["sample"], i["target"]) == ("KO_1", GENE))
    left = next(r for r in item["reasons"] if r["source"] == "set_aside")
    assert decided.REASON in left["words"] and "from Trace" in left["words"]
    assert item["consequence"] == "changes_call"  # leaving it out changed 1-Mar's call
    assert sorted(item["wells"]) == sorted(done["left_out"])


def test_the_run_gate_lines_per_plate_and_no_more_not_built(called):
    c, study = called["client"], called["study"]
    plan = repeat(c, study)["plan"]
    lines = {line["plate"]: line for line in plan["gate_lines"]}
    tainted = next(p for p in lines if p.startswith(GENE))
    assert lines[tainted]["worst"] in ("fail", "warn")
    assert any(f["code"] == "G-NTC-1" for f in lines[tainted]["findings"])
    assert all(sum(line["counts"].values()) > 0 for line in lines.values())
    review = c.get(f"/api/studies/{study}/review").json()
    assert [n["id"] for n in review["not_built"]] == ["next_run"]
    assert "not built" not in str(review).lower()


def test_names_that_are_not_studies(called):
    c = called["client"]
    assert c.get("/api/studies/nope/review/repeat").status_code == 404
    bad = c.get(f"/api/studies/{called['study']}/review/repeat", params={"include": "x"})
    assert bad.status_code == 422


# ---- the repeat layout itself (pure) ----------------------------------------------------------


def test_a_repeat_layout_keeps_each_sample_whole_and_splits_plates_when_it_must():
    spec = lay.RepeatSpec(
        reactions=tuple((f"S{i:02d}", "A" if i % 2 else "B", "T1") for i in range(30)),
        refs=("R1", "R2"),
        calibrator="CAL",
        replicates=2,
        plate_size=96,
    )
    layout = lay.make_repeat_layout(spec)
    assert len(layout.plates) > 1
    seen: dict[str, int] = {}
    for plate in layout.plates:
        assert len(plate.wells) <= 96
        for w in plate.wells:
            if w.type == "unkn":
                assert seen.setdefault(w.sample, plate.number) == plate.number  # whole sample
        for assay in ("T1", "R1", "R2"):
            kinds = [w.type for w in plate.wells if w.target == assay]
            assert kinds.count("pos") == 2 and kinds.count("ntc") == 1 and kinds.count("nrt") == 1
    assert len(seen) == 30
    assert lay.make_repeat_layout(spec).wells() == layout.wells()  # the same seed, the same plate
    with pytest.raises(lay.LayoutError, match="calibrator is a sample to repeat"):
        lay.make_repeat_layout(lay.RepeatSpec(reactions=(("CAL", "", "T1"),), refs=("R1",),
                                              calibrator="CAL"))  # fmt: skip
    with pytest.raises(lay.LayoutError, match="nothing to repeat"):
        lay.make_repeat_layout(lay.RepeatSpec(reactions=(), refs=("R1",)))
    with pytest.raises(lay.LayoutError, match="384-well plates"):
        many = tuple(("S1", "", f"T{i}") for i in range(40))
        lay.make_repeat_layout(lay.RepeatSpec(reactions=many, refs=("R1",), replicates=2))
