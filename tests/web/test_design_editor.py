"""The Design page's own editing: finish the design on the page, with no model, on real exports.

A CFX export and a group sheet stopped at "no reference genes yet": the rules propose groups
from the sheet's group column, but nothing said which target is the reference gene. Here a
person sets it on the page (``POST …/design/set``), the groups the rules proposed are accepted
by the same act, the comparison is chosen, and the study goes through Curves to Results, all
with ``QPILOT_MODEL_PROVIDER=none``. Every write is the person's (``actor="human"``), recorded in
the hash-chained inbox with its reason; the engine checks every item first.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from tests.timing import work_time
from tests.web.conftest import wait_job

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
SYNTH_CFX = CORPUS / "synthetic" / "cfx-manager-raw-vs-baseline-subtracted"
HMUY = CORPUS / "rdml" / "lightcycler96-lc96p-hmuy" / "hmuy_hm_vs_dip_r123.lc96p"
GROUPS = "Sample,Group\nS1,A\nS2,A\nS3,A\nS4,A\nS5,B\nS6,B\nS7,B\nS8,B\n"
REASON = "plate layout from my lab notebook"


def cfx_files() -> list[Path]:
    return sorted(SYNTH_CFX.glob("qpilot-synthetic-raw *"))


def open_export(client, paths, sheet: str | None = None) -> str:
    parts = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    if sheet is not None:
        parts.append(("sheet", ("groups.csv", sheet.encode(), "text/csv")))
    r = client.post("/api/workspaces", files=parts)
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "done", job
    return job["result"]["key"]


def open_rdml(client, path: Path) -> str:
    r = client.post("/api/workspaces", files={"rdml": (path.name, path.read_bytes(), "x")})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "done", job
    return job["result"]["key"]


def propose_design(client, sid: str) -> dict:
    r = client.post(f"/api/sessions/{sid}/propose/design", json={})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "done", job
    return job["result"]


def editor(client, sid: str) -> dict:
    r = client.get(f"/api/sessions/{sid}/design/editor")
    assert r.status_code == 200, r.text
    return r.json()


def items_of(*triples) -> list[dict]:
    return [{"kind": k, "subject": s, "payload": p} for k, s, p in triples]


def record(client, sid, items, reason=REASON, **extra) -> dict:
    view = editor(client, sid)
    body = {"items": items, "reason": reason, "expected_head": view["head"], **extra}
    r = client.post(f"/api/sessions/{sid}/design/set", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def pending(client, sid, stage="design") -> list[dict]:
    r = client.get(f"/api/sessions/{sid}/proposals", params={"stage": stage})
    return [p for p in r.json()["proposals"] if p["status"] == "proposed"]


def confirm(client, sid, stage):
    shown = client.post(f"/api/sessions/{sid}/confirm/{stage}")
    assert shown.status_code == 200, shown.text
    view = shown.json()
    assert view["ready"], view
    r = client.post(
        f"/api/sessions/{sid}/confirm/{stage}/accept",
        json={"proposal_id": view["proposal"]["id"], "expected_head": view["head"]},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def cfx_session(sclient):
    sid = open_export(sclient, cfx_files(), GROUPS)
    propose_design(sclient, sid)
    return sid


# ---- the blocker the audit found, and its fix --------------------------------------------------


def test_a_cfx_export_with_a_group_sheet_needs_a_reference_gene(sclient, cfx_session):
    view = editor(sclient, cfx_session)
    codes = [n["code"] for n in view["needs"]]
    assert "reference" in codes
    need = next(n for n in view["needs"] if n["code"] == "reference")
    assert need["where"] == "targets"  # the page links the need to the control that fixes it
    targets = {t["target"]: t for t in view["targets"]}
    assert set(targets) == {"REF", "GOI"}
    assert all(t["role"] is None for t in targets.values())
    samples = {s["sample"]: s for s in view["samples"]}
    assert samples["S1"]["waiting"] == ["design.group"]  # the sheet's group, waiting
    member = {m["sample"]: m for m in view["membership"]}
    assert member["S1"]["group"] is None and set(member) == set(samples)
    assert len(samples["S1"]["wells"]) == samples["S1"]["n_wells"] > 0
    # blind: the editor never carries a number about a well
    text = str(view)
    assert "cq" not in {k for s in view["samples"] for k in s}
    assert "fold" not in text.lower()


def test_check_shows_what_recording_does_and_writes_nothing(sclient, cfx_session):
    before = editor(sclient, cfx_session)["head"]
    items = items_of(
        ("design.target_role", "REF", {"role": "ref"}),
        ("design.target_role", "GOI", {"role": "toi"}),
        ("design.group", "S1", {"group": "A"}),
        ("design.group", "S5", {"group": "Z"}),
    )
    r = sclient.post(f"/api/sessions/{cfx_session}/design/check", json={"items": items})
    assert r.status_code == 200, r.text
    plan = {(p["kind"], p["subject"]): p for p in r.json()["items"]}
    assert plan[("design.target_role", "REF")]["action"] == "new"
    assert plan[("design.target_role", "REF")]["check"]["status"] == "cannot_check"
    assert plan[("design.target_role", "GOI")]["action"] == "new"  # a target has no default
    s1 = plan[("design.group", "S1")]
    assert s1["action"] == "accept" and s1["accept_id"]  # the rules' proposal says the same
    s5 = plan[("design.group", "S5")]
    assert s5["action"] == "new" and len(s5["rejects"]) == 1  # the sheet said B: rejected
    assert "Put sample S5 in group “Z”" in s5["words"]
    assert editor(sclient, cfx_session)["head"] == before


def test_the_whole_design_is_finished_on_the_page_then_curves_and_results(sclient, cfx_session):
    sid = cfx_session
    groups = {f"S{i}": "A" if i <= 4 else "B" for i in range(1, 9)}
    items = [
        *items_of(("design.target_role", "REF", {"role": "ref"})),
        *items_of(*(("design.group", s, {"group": g}) for s, g in groups.items())),
        *items_of(("design.comparison", "comparison", {"group_a": "B", "group_b": "A"})),
    ]
    done = record(sclient, sid, items)
    assert done["recorded"] == 1 + 8 + 1, done  # REF, the 8 sheet groups accepted, the comparison
    assert done["rejected"] == 0
    view = editor(sclient, sid)
    assert {t["target"]: t["role"] for t in view["targets"]}["REF"] == "ref"
    assert view["groups"] == {"A": 4, "B": 4}
    assert view["comparison"] == {"group_a": "B", "group_b": "A"}
    assert [n["code"] for n in view["needs"] if n["code"] != "waiting"] == []
    # every decision is the person's, with the reason, in the hash-chained inbox
    decided = [
        p
        for p in sclient.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()[
            "proposals"
        ]
        if p["status"] == "accepted"
    ]
    assert all(p["decided_by"] == "human" and p["reason"] == REASON for p in decided)
    mine = [p for p in decided if p["made_by"]["kind"] == "person"]
    assert {p["subject"] for p in mine} == {"REF", "comparison"}
    assert {p["made_by"]["kind"] for p in decided if p["kind"] == "design.group"} == {"rule"}
    # what the rules proposed besides (well roles, symbols) is still the person's to decide
    for p in pending(sclient, sid):
        r = sclient.post(
            f"/api/sessions/{sid}/proposals/{p['id']}/reject",
            json={
                "reason": "not part of this study",
                "expected_head": editor(sclient, sid)["head"],
            },
        )
        assert r.status_code == 200, r.text
    confirm(sclient, sid, "design")
    r = sclient.post(f"/api/sessions/{sid}/propose/curves")
    assert r.status_code == 202, r.text
    assert wait_job(sclient, r.json()["job"])["status"] == "done"
    for p in pending(sclient, sid, "curves"):
        r = sclient.post(
            f"/api/sessions/{sid}/proposals/{p['id']}/accept",
            json={"reason": "checked the curves", "expected_head": editor(sclient, sid)["head"]},
        )
        assert r.status_code == 200, r.text
    confirmed = confirm(sclient, sid, "curves")
    assert confirmed["results_visible"] is True
    job = wait_job(sclient, confirmed["job"])
    assert job["status"] == "done", job
    results = sclient.get(f"/api/studies/{job['result']['study_id']}/results")
    assert results.status_code == 200, results.text
    body = results.json()
    assert [g["gene"] for g in body["genes"]] == ["GOI"]
    assert body["references"]["candidates"] == ["REF"] or "REF" in str(body["references"])
    goi = body["genes"][0]
    assert goi["n_hi"] == 4 and goi["n_lo"] == 4  # four biological units in each group


def test_a_declared_control_is_refused_in_words_and_nothing_is_written(sclient, mini_rdml):
    sid = open_rdml(sclient, mini_rdml)
    propose_design(sclient, sid)
    view = editor(sclient, sid)
    control = next(s for s in view["samples"] if s["locked"])
    before = view["head"]
    items = items_of(("design.group", control["sample"], {"group": "WT"}))
    plan = sclient.post(f"/api/sessions/{sid}/design/check", json={"items": items}).json()
    assert plan["items"][0]["action"] == "refused"
    assert "control" in plan["items"][0]["refusal"]
    r = sclient.post(
        f"/api/sessions/{sid}/design/set",
        json={"items": items, "reason": "test", "expected_head": before},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "studio"
    assert "Nothing was recorded" in r.json()["error"]["message"]
    assert editor(sclient, sid)["head"] == before


def test_a_reason_is_required_and_a_stale_head_is_refused(sclient, cfx_session):
    items = items_of(("design.target_role", "REF", {"role": "ref"}))
    r = sclient.post(
        f"/api/sessions/{cfx_session}/design/set", json={"items": items, "reason": "  "}
    )
    assert r.status_code == 422
    view = editor(sclient, cfx_session)
    record(sclient, cfx_session, items_of(("design.group", "S1", {"group": "A"})))
    r = sclient.post(
        f"/api/sessions/{cfx_session}/design/set",
        json={"items": items, "reason": REASON, "expected_head": view["head"]},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"


def test_bad_names_and_unknown_subjects_are_refused_in_words(sclient, cfx_session):
    items = items_of(
        ("design.group", "S1", {"group": "<script>"}),
        ("design.group", "nobody", {"group": "A"}),
        ("design.target_role", "REF", {"role": "boss"}),
        ("design.comparison", "comparison", {"group_a": "A", "group_b": "A"}),
    )
    plan = sclient.post(f"/api/sessions/{cfx_session}/design/check", json={"items": items}).json()
    refusals = [p["refusal"] for p in plan["items"]]
    assert all(r for r in refusals), plan
    assert any("letters, digits" in r for r in refusals)
    assert any("no sample" in r for r in refusals)


def test_a_group_and_a_unit_can_be_taken_back(sclient, cfx_session):
    sid = cfx_session
    record(
        sclient,
        sid,
        items_of(
            ("design.group", "S1", {"group": "A"}),
            ("design.bio_unit", "S1", {"biological_unit": "M1"}),
        ),
    )
    record(
        sclient,
        sid,
        items_of(
            ("design.group", "S1", {"group": None}),
            ("design.bio_unit", "S1", {"biological_unit": None}),
        ),
        reason="S1 was a mislabelled tube",
    )
    s1 = next(s for s in editor(sclient, sid)["membership"] if s["sample"] == "S1")
    assert s1["group"] is None and s1["unit"] is None


def test_an_agent_cannot_make_a_person_made_proposal(web_store, mini_rdml):
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.proposals import ProposalError
    from qpilot.schemas_studio import MadeBy, Proposal
    from qpilot.studio_service import Studio

    studio = Studio(web_store, client=ModelClient(backend=NoneBackend()))
    sid = studio.open(mini_rdml)
    forged = Proposal(
        study_id=sid,
        kind="design.group",
        subject="WT_1",
        payload={"group": "KO"},
        made_by=MadeBy(kind="person"),
    )
    for actor in ("agent", "system"):
        out = studio.store.proposals(sid).propose(forged, actor)
        assert out.status == "refused", out
    assert "person" in (studio.store.proposals(sid).propose(forged, "system").reason or "")
    with pytest.raises(ProposalError):
        studio.store.proposals(sid).decide_together(
            [(forged, "accept")], [], "agent", "x", proposer="human"
        )


# ---- the sample-sheet template and attaching a sheet from the Design page -------------------


def test_the_template_is_prefilled_and_reads_back_as_a_sheet(sclient, cfx_session, tmp_path):
    from qpilot.io.sheets import sheet_table, target_roles

    record(sclient, cfx_session, items_of(("design.target_role", "REF", {"role": "ref"})))
    r = sclient.get(f"/api/sessions/{cfx_session}/design/template.csv")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "sample sheet.csv" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][:5] == ["Sample", "Group", "Biological unit", "Sample type", "Quantity"]
    names = {row[0]: row for row in rows[1:] if row[0]}
    assert {f"S{i}" for i in range(1, 9)} <= set(names)
    assert names["NTC"][3] == "NTC" and names["S1"][3] == "Unknown"
    assert names["S1"][5].startswith("A1")  # the sample's wells, to find it on the plate
    assert {row[7]: row[8] for row in rows[1:] if row[7]} == {"REF": "Reference", "GOI": ""}
    path = tmp_path / "template.csv"
    path.write_text(text, encoding="utf-8")
    table = sheet_table(path)
    assert table is not None and {"sample", "group", "target", "target_role"} <= set(table.columns)
    assert [(c.target, c.role) for c in target_roles(path)] == [("REF", "ref")]


def test_a_filled_sheet_attached_from_design_proposes_the_reference(sclient):
    sid = open_export(sclient, cfx_files())  # no sheet at first: no group, no reference
    first = editor(sclient, sid)
    assert first["has_sheet"] is False
    sheet = (
        "Sample,Group,,Target,Gene type\n"
        "S1,A,,REF,Reference\nS2,A,,GOI,Target\nS3,A\nS4,A\nS5,B\nS6,B\nS7,B\nS8,B\n"
    )
    r = sclient.post(
        f"/api/sessions/{sid}/sheet", files={"sheet": ("filled.csv", sheet.encode(), "text/csv")}
    )
    assert r.status_code == 202, r.text
    assert wait_job(sclient, r.json()["job"])["status"] == "done"
    view = editor(sclient, sid)
    assert view["has_sheet"] is True and view["sheet_name"] == "filled.csv"
    waiting = {
        (p["kind"], p["subject"]): p["payload"]
        for p in pending(sclient, sid)
        if p["kind"] in ("design.target_role", "design.group")
    }
    assert waiting[("design.target_role", "REF")] == {"role": "ref"}
    assert waiting[("design.target_role", "GOI")] == {"role": "toi"}
    assert waiting[("design.group", "S5")] == {"group": "B"}


def test_an_unreadable_sheet_is_refused_in_words(sclient, cfx_session):
    r = sclient.post(
        f"/api/sessions/{cfx_session}/sheet",
        files={"sheet": ("notes.csv", b"hello,world\n1,2\n", "text/csv")},
    )
    assert r.status_code == 400
    assert "Sample column" in r.json()["error"]["message"]


# ---- a real LightCycler 96 file: no names, every target declared a reference -----------------


def test_lightcycler96_every_target_declared_ref_is_only_a_low_proposal(sclient):
    sid = open_export(sclient, [HMUY])
    propose_design(sclient, sid)
    roles = [p for p in pending(sclient, sid) if p["kind"] == "design.target_role"]
    assert roles and all(p["level"] == "Low" for p in roles)
    assert all(p["alternatives"] == [{"role": "toi"}] for p in roles)


def test_lightcycler96_is_finished_on_the_page_with_an_empty_channel_left_out(sclient, studio_ctx):
    sid = open_export(sclient, [HMUY])
    propose_design(sclient, sid)
    view = editor(sclient, sid)
    targets = {t["target"]: t for t in view["targets"]}
    hmuy = next(t for t in targets if "hmuy" in t.lower())  # LC96 names: dye@target or target
    rrna = next(t for t in targets if "16s" in t.lower())
    empty = next(t for t in targets if t not in (hmuy, rrna))
    studied = sorted(
        (s for s in view["samples"] if s["role"] == "unkn"), key=lambda s: sorted(s["wells"])[0]
    )
    assert len(studied) == 6
    groups = {s["sample"]: ("Hm" if i < 3 else "DIP") for i, s in enumerate(studied)}
    items = [
        *items_of(
            ("design.target_role", rrna, {"role": "ref"}),
            ("design.target_role", hmuy, {"role": "toi"}),
            ("design.target_role", empty, {"role": "ignore"}),
        ),
        *items_of(*(("design.group", s, {"group": g}) for s, g in groups.items())),
        *items_of(("design.comparison", "comparison", {"group_a": "DIP", "group_b": "Hm"})),
    ]
    done = record(sclient, sid, items)
    assert done["recorded"] >= 9  # 3 targets (one may accept the rules' Low proposal), 6 groups
    view = editor(sclient, sid)
    assert {t["target"]: t["role"] for t in view["targets"]} == {
        rrna: "ref",
        hmuy: "toi",
        empty: "ignore",
    }
    assert [n["code"] for n in view["needs"] if n["code"] not in ("waiting",)] == []
    # the design assembles with the empty channel left out of the headline genes
    assembly = studio_ctx.studio.assemble(sid)
    assert assembly.design is not None, assembly.blockers
    assert empty not in assembly.design.headline and hmuy in assembly.design.headline
    assert assembly.design.targets[empty].role == "ignore"
    plate = sclient.get(f"/api/sessions/{sid}/plate").json()
    left = [w for w in plate["wells"] if w["target"] == empty]
    assert len(left) == targets[empty]["n_wells"]  # still on the plate map, marked
    assert all("left out" in w["excluded_note"] for w in left)


def test_ref_is_never_renamed_alyref_and_such_a_rename_is_never_consistent(sclient, web_store):
    from qpilot.mcp_server import QpilotTools

    sid = open_export(sclient, cfx_files(), GROUPS)
    propose_design(sclient, sid)
    symbols = [p for p in pending(sclient, sid) if p["kind"] == "design.gene_symbol"]
    assert not [p for p in symbols if p["subject"] in ("REF", "GOI")]
    QpilotTools(web_store).qpcr_propose(sid, "design.gene_symbol", "REF", {"symbol": "ALYREF"})
    agent = next(p for p in pending(sclient, sid) if p["kind"] == "design.gene_symbol")
    assert agent["subject"] == "REF" and agent["check"]["status"] == "cannot_check"
    shown = sclient.get(f"/api/sessions/{sid}/bulk/accept", params={"stage": "design"}).json()
    assert agent["id"] not in shown["ids"]  # never in "Accept all consistent"


def test_a_whole_96_well_plate_is_set_in_one_act_quickly(web_store):
    """CFX Maestro 4-plex (simulator): 96 unnamed samples, one per well; one act, ~190 items."""

    from qpilot import studio_design as sd
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.studio_service import Studio
    from qpilot.web import intake

    studio = Studio(web_store, client=ModelClient(backend=NoneBackend()))
    folder = CORPUS / "biorad" / "covmatic-cfx-maestro-4.0-simulated-4plex"
    found = intake.sort_dropped([intake.classify(p, p.name) for p in sorted(folder.glob("*.csv"))])
    sid = studio.open(intake.read_export(web_store, found.exports).rdml_path)
    state = sd.state(studio, sid)
    study = [s for s in state.samples if s.role == "unkn"]
    assert len(study) >= 90
    items = [sd.DesignItem("design.target_role", "IEC", {"role": "ref"})]
    for s in study:
        half = "left" if int(s.wells[0].split("/")[1][1:]) <= 6 else "right"
        items.append(sd.DesignItem("design.group", s.sample, {"group": half}))
        items.append(
            sd.DesignItem("design.bio_unit", s.sample, {"biological_unit": f"u_{s.sample[-3:]}"})
        )
    with work_time() as spent:
        done = sd.set_design(studio, sid, items, "human", "plate halves")
    assert done.recorded == len(items)
    assert spent.seconds < 20, spent  # was quadratic (a copy of the inbox per item)
    entries = web_store.proposals(sid).entries()
    assert {e.actor for e in entries} == {"human"}  # proposed and accepted by the person


def test_proposing_again_never_asks_what_a_person_already_decided(sclient, cfx_session):
    sid = cfx_session
    groups = {f"S{i}": "A" if i <= 4 else "B" for i in range(1, 9)}
    record(sclient, sid, items_of(*(("design.group", s, {"group": g}) for s, g in groups.items())))
    assert not [p for p in pending(sclient, sid) if p["kind"] == "design.group"]
    report = propose_design(sclient, sid)  # the same sheet: the same groups
    assert not [p for p in pending(sclient, sid) if p["kind"] == "design.group"]
    assert any("not made again" in n for n in report["notes"]), report


def test_the_template_is_a_download_never_a_page_and_defuses_formulas(sclient, mini_rdml):
    """A sample named like markup or a spreadsheet formula comes back as a CSV cell only."""
    from tests.fixtures.studio.studio_mini import write_studio_mini

    evil = write_studio_mini(
        mini_rdml.parent / "evil.rdml", rename={"KO_2": '=HYPERLINK("x")<b>x</b>'}
    )
    sid = open_rdml(sclient, evil)
    r = sclient.get(f"/api/sessions/{sid}/design/template.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    names = [row[0] for row in rows[1:] if row[0]]
    assert '\'=HYPERLINK("x")<b>x</b>' in names  # a leading ' keeps Excel from running it
    assert not any(n.startswith("=") for n in names)
