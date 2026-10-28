"""The Claim Auditor on a real lab's study with several comparisons, over the page's API.

The K. phaffii LinRegPCR RDML (corpus ``rdml/linregpcr-rdml-1.3-lc480-kphaffii``), walked
through Studio as ``test_compare_real_lab`` walks it: 28, D20 and D28 each against 20, Dunnett.
The first comparison is 28 against 20. A claim about D20 is not checked against it (it was, and
came back Supported or Contradicted on 28's numbers: science review, B3); a claim about 28
against 20 is checked as before; a claim that names no group says which comparison it was read
against.
"""

from __future__ import annotations

from tests.web.test_compare_real_lab import GROUPS, RDML, REASON, _open, _study
from tests.web.test_design_editor import editor, propose_design, record


def _claims(client, study: str, text: str) -> list[dict]:  # noqa: ANN001
    r = client.post(f"/api/studies/{study}/claims", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()["claims"]


def test_claims_follow_the_comparisons_of_a_real_study(sclient):
    sid = _open(sclient, RDML)
    propose_design(sclient, sid)
    view = editor(sclient, sid)
    condition = {
        s["sample"]: s["sample"].rsplit("_", 1)[0] for s in view["samples"] if s["role"] == "unkn"
    }
    others = [g for g in GROUPS if g != "20"]
    plan = {
        "group_a": others[0],
        "group_b": "20",
        "comparisons": [{"group_a": g, "group_b": "20"} for g in others],
        "pattern": "vs_control",
        "control": "20",
        "correction": "dunnett",
    }
    items = [
        {"kind": "design.target_role", "subject": "ACT1", "payload": {"role": "ref"}},
        {"kind": "design.target_role", "subject": "TFC1", "payload": {"role": "ref"}},
        *(
            {"kind": "design.group", "subject": s, "payload": {"group": g}}
            for s, g in condition.items()
            if g in GROUPS
        ),
        {"kind": "design.comparison", "subject": "comparison", "payload": plan},
    ]
    assert record(sclient, sid, items, reason=REASON)["rejected"] == 0
    study = _study(sclient, sid)

    (other,) = _claims(sclient, study, "HAC1i was higher in D20 than in 20.")
    assert other["verdict"] == "unchecked", other["headline"]["plain"]
    plain = other["headline"]["plain"]
    assert "“D20”" in plain and "first comparison only (28 against 20)" in plain

    (first,) = _claims(sclient, study, "HAC1i was higher in 28 than in 20.")
    assert first["verdict"] in ("overstated", "supported", "contradicted")
    assert "first comparison only" not in first["headline"]["plain"]

    (bare,) = _claims(sclient, study, "HAC1i did not change.")
    notes = [c["text"]["plain"] for c in bare["checks"] if c["check"] == "groups"]
    assert notes == [
        "This study has several comparisons; with no group named, the claim is read against "
        "the first, 28 against 20."
    ]
