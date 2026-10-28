"""Multiplex plates walked end to end on the page's API: Design -> Curves -> Results -> Run Gate.

Real lab files, no model (``QPILOT_MODEL_PROVIDER=none``), every decision the person's:

* the CFX Maestro 4-plex (simulator export, one file per dye): the reference IEC is measured in
  the same well as the genes. Before the fix only the first dye of each well had an N0, so every
  gene was withheld ("fewer than two biological units with a value"); now E_covid and N_covid are
  compared on 47 + 47 units, each normalised by the IEC of its own well;
* the LightCycler 96 4-plex (FAM bACT, Hex X, Texas Red Y, Cy5 IPC): the rules propose leaving
  the IPC out of the comparison, X and Y are normalised by bACT in the same well (detected in one
  group only: their delta Cq is given), the Run Gate still reads the IPC (G-IPC), and the plate
  map gets one row per dye with the dye's name.
"""

from __future__ import annotations

from pathlib import Path

from tests.web.conftest import wait_job
from tests.web.test_design_editor import (
    confirm,
    editor,
    items_of,
    open_export,
    pending,
    propose_design,
    record,
)

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
CFX = CORPUS / "biorad" / "covmatic-cfx-maestro-4.0-simulated-4plex"
LC96 = CORPUS / "rdml" / "lightcycler96-rdml-1.1" / "lc96_bACTXY.rdml"


def finish(client, sid: str, items: list[dict]) -> str:
    """Record the design, reject what the rules proposed besides, confirm both stages."""
    done = record(client, sid, items)  # the rules' proposals that say otherwise are rejected
    assert done["recorded"] >= len(items) - done["unchanged"], done
    for p in pending(client, sid):
        r = client.post(
            f"/api/sessions/{sid}/proposals/{p['id']}/reject",
            json={"reason": "not part of this study", "expected_head": editor(client, sid)["head"]},
        )
        assert r.status_code == 200, r.text
    confirm(client, sid, "design")
    r = client.post(f"/api/sessions/{sid}/propose/curves")
    assert wait_job(client, r.json()["job"])["status"] == "done"
    for p in pending(client, sid, "curves"):
        r = client.post(
            f"/api/sessions/{sid}/proposals/{p['id']}/accept",
            json={"reason": "checked the curves", "expected_head": editor(client, sid)["head"]},
        )
        assert r.status_code == 200, r.text
    confirmed = confirm(client, sid, "curves")
    job = wait_job(client, confirmed["job"])
    assert job["status"] == "done", job
    return job["result"]["study_id"]


def test_a_cfx_4plex_is_compared_with_the_reference_of_each_well(sclient):
    sid = open_export(sclient, sorted(CFX.glob("*.csv")))
    propose_design(sclient, sid)
    view = editor(sclient, sid)
    study = [s for s in view["samples"] if s["role"] == "unkn"]
    assert len(study) == 94 and all(len(s["wells"]) == 1 for s in study)
    assert all(s["targets"] == ["E_covid", "IEC", "N_covid", "ORF1ab_covid"] for s in study)
    items = items_of(
        ("design.target_role", "IEC", {"role": "ref"}),
        ("design.target_role", "E_covid", {"role": "toi"}),
        ("design.target_role", "N_covid", {"role": "toi"}),
        ("design.target_role", "ORF1ab_covid", {"role": "toi"}),
    )
    for s in study:
        column = int(s["wells"][0].split("/")[1][1:])
        items += items_of(
            ("design.group", s["sample"], {"group": "left" if column <= 6 else "right"})
        )
    items += items_of(("design.comparison", "comparison", {"group_a": "right", "group_b": "left"}))
    study_id = finish(sclient, sid, items)
    body = sclient.get(f"/api/studies/{study_id}/results").json()
    genes = {g["gene"]: g for g in body["genes"]}
    assert sorted(genes) == ["E_covid", "N_covid"]
    for gene in genes.values():
        assert gene["n_hi"] == 47 and gene["n_lo"] == 47 and gene["fc"] > 0
    assert body["references"]["used"] == ["IEC"]
    withheld = {w["gene"]: w["reason"] for w in body["withheld"]}
    assert list(withheld) == ["ORF1ab_covid"]  # the simulator's ORF1ab never amplifies
    assert "not detected in any" in withheld["ORF1ab_covid"]


def test_a_lightcycler96_4plex_with_an_ipc_from_design_to_the_run_gate(sclient):
    sid = open_export(sclient, [LC96])
    propose_design(sclient, sid)
    roles = {p["subject"]: p for p in pending(sclient, sid) if p["kind"] == "design.target_role"}
    ipc = roles["IPC"]
    assert ipc["payload"] == {"role": "ignore"} and ipc["level"] == "Moderate"
    assert "internal positive control" in " ".join(ipc["reasons"])
    view = editor(sclient, sid)
    study = sorted((s for s in view["samples"] if s["role"] == "unkn"), key=lambda s: s["sample"])
    assert [s["sample"] for s in study] == [f"Sample {n}" for n in range(53, 59)]
    items = items_of(
        ("design.target_role", "bACT", {"role": "ref"}),
        ("design.target_role", "X", {"role": "toi"}),
        ("design.target_role", "Y", {"role": "toi"}),
        ("design.target_role", "IPC", {"role": "ignore"}),
    )
    items += items_of(
        *(
            ("design.target_role", t["target"], {"role": "ignore"})
            for t in view["targets"]
            if t["target"].startswith("no target")
        )
    )
    items += items_of(
        *(
            ("design.group", s["sample"], {"group": "a" if i < 3 else "b"})
            for i, s in enumerate(study)
        )
    )
    items += items_of(("design.comparison", "comparison", {"group_a": "b", "group_b": "a"}))
    study_id = finish(sclient, sid, items)

    body = sclient.get(f"/api/studies/{study_id}/results").json()
    assert body["references"]["used"] == ["bACT"]
    withheld = {w["gene"]: w for w in body["withheld"]}
    assert sorted(withheld) == ["X", "Y"]
    for gene in ("X", "Y"):  # their N0 is there now; their delta Cq is to bACT in the same well
        only = withheld[gene]["detected_only"]
        assert only["group"] == "a" and only["n_detected"] == 2 and only["n_absent"] == 3
        assert 2.0 < only["dcq"] < 3.5

    gate = sclient.get(f"/api/studies/{study_id}/gate").json()
    (ipc_line,) = [e for e in gate["evaluations"] if e["rule_id"] == "G-IPC"]
    assert ipc_line["target"] == "IPC" and ipc_line["verdict"] == "pass"
    assert "expected Cq is 36.27" in ipc_line["reason"]["plain"]
    assert gate["pack"]["version"] == "1.3.0"

    plate = sclient.get(f"/api/sessions/{sid}/plate").json()
    assert plate["multiplex"] is True
    d3 = [w for w in plate["wells"] if w["well"] == "D3"]
    assert [(w["target"], w["dye"]) for w in d3] == [
        ("bACT", "FAM"),
        ("X", "Hex"),
        ("Y", "Texas Red"),
        ("IPC", "Cy5"),
    ]
    assert len({w["key"] for w in d3}) == 1
    calls = {w["target"]: (w["amplified"], w["cq"]) for w in d3 if w["target"] != "IPC"}
    assert all(amplified and cq for amplified, cq in calls.values())
    assert (
        sclient.get(
            f"/api/sessions/{sid}/curve", params={"well": d3[0]["key"], "target": "Y"}
        ).json()["target"]
        == "Y"
    )
