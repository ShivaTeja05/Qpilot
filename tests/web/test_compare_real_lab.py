"""A real lab's conditions, end to end on the page: several comparisons in every section.

The RDML that LinRegPCR wrote from a LightCycler 480 II study of the unfolded protein response in
Komagataella phaffii (Büchner, Ludwig, Kerpes & Becker 2025, Microbial Cell Factories; CC BY 4.0;
the corpus set ``rdml/linregpcr-rdml-1.3-lc480-kphaffii``): eight conditions in three biological
replicates each, four UPR genes and two reference genes (ACT1, TFC1), every sample in triplicate
wells, raw curves. A person opens it on the page, puts four conditions in their groups (20, 28,
D20, D28; the others stay out) and, on the Design page, sets each of them against ``20`` with
Dunnett's correction (their own design item, with a reason). Then every section follows the
comparisons: Results, the side by side view, the Decision Cards, Trace, a gene's units and figure,
History and the Run Review; Dunnett's corrected p equals scipy's on the units' own values.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scipy import stats

from tests.web.conftest import wait_job
from tests.web.test_design_editor import confirm, editor, pending, propose_design, record
from tests.web.test_studio_flow import no_html

RDML = (
    Path(__file__).resolve().parents[1]
    / "fixtures/corpus/rdml/linregpcr-rdml-1.3-lc480-kphaffii/12934_2025_2809_MOESM5_ESM.rdml"
)
GROUPS = ("20", "28", "D20", "D28")
REASON = "each condition against 20, as prespecified in our protocol"


def _open(client, path: Path) -> str:
    r = client.post("/api/workspaces", files={"rdml": (path.name, path.read_bytes(), "x")})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "done", job
    return job["result"]["key"]


def _study(client, sid: str) -> str:
    for p in pending(client, sid):
        r = client.post(
            f"/api/sessions/{sid}/proposals/{p['id']}/reject",
            json={"reason": "not part of this study", "expected_head": editor(client, sid)["head"]},
        )
        assert r.status_code == 200, r.text
    confirm(client, sid, "design")
    r = client.post(f"/api/sessions/{sid}/propose/curves")
    assert r.status_code == 202, r.text
    assert wait_job(client, r.json()["job"])["status"] == "done"
    for p in pending(client, sid, "curves"):
        r = client.post(
            f"/api/sessions/{sid}/proposals/{p['id']}/accept",
            json={"reason": "checked", "expected_head": editor(client, sid)["head"]},
        )
        assert r.status_code == 200, r.text
    confirmed = confirm(client, sid, "curves")
    job = wait_job(client, confirmed["job"])
    assert job["status"] == "done", job
    return job["result"]["study_id"]


def test_real_conditions_with_dunnett_in_every_section(sclient):
    sid = _open(sclient, RDML)
    propose_design(sclient, sid)
    view = editor(sclient, sid)
    samples = [s["sample"] for s in view["samples"] if s["role"] == "unkn"]
    condition = {s: s.rsplit("_", 1)[0] for s in samples}
    assert len(samples) == 24 and set(condition.values()) >= set(GROUPS)
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
    done = record(sclient, sid, items, reason=REASON)
    assert done["rejected"] == 0, done
    shown = editor(sclient, sid)
    assert shown["comparison_plan"]["correction"] == "dunnett"
    assert shown["comparison_plan"]["control"] == "20"
    study = _study(sclient, sid)
    api = f"/api/studies/{study}"

    # Results and the side-by-side view: three comparisons, Dunnett-corrected
    side = sclient.get(f"{api}/comparisons").json()
    assert side["correction"] == "dunnett" and side["test"] == "pooled_t"
    ids = [c["id"] for c in side["comparisons"]]
    assert ids == ["28_vs_20", "d20_vs_20", "d28_vs_20"]
    assert any(n["kind"] == "correction" and "Dunnett" in n["text"] for n in side["notes"])
    genes = [g["gene"] for g in side["genes"]]
    assert len(genes) == 4  # the four UPR genes; the references normalise
    gene = genes[0]
    # the engine's corrected p is scipy's Dunnett on the per-unit values the units route shows
    values: dict[str, list[float]] = {}
    for cid in ids:
        units = sclient.get(f"{api}/genes/{gene}/units", params={"comparison": cid}).json()
        assert units["comparison"] == cid and units["correction"] == "Dunnett"
        for p in units["points"]:
            label = units["groups"][p["group"]]["label"]
            values.setdefault(label, {})[p["unit"]] = p["x"] + 0.0  # type: ignore[index]
    # each comparison's x is relative to the control's mean: the same shift for every group
    groups = {g: list(v.values()) for g, v in values.items()}  # type: ignore[union-attr]
    want = stats.dunnett(*(groups[g] for g in others), control=groups["20"], random_state=1)
    row = next(g for g in side["genes"] if g["gene"] == gene)
    for cell, p in zip(row["cells"], want.pvalue, strict=True):
        assert cell["p_adjusted"] == pytest.approx(p, abs=2e-3)

    # the Decision Cards count every comparison
    cards = sclient.get(f"{api}/cards").json()["cards"]
    refset = next(c for c in cards if c["card"]["id"] == "card_refset")
    assert [c["id"] for c in refset["comparisons"]] == ids
    assert refset["study_wide"]

    # Trace follows each comparison, with the corrected call
    for cid in ids:
        r = sclient.get(f"{api}/trace/{gene}", params={"comparison": cid})
        for _ in range(200):
            if r.status_code != 409 or r.json()["error"]["code"] != "loading":
                break
            wait_job(sclient, r.json()["error"]["details"]["job"])
            r = sclient.get(f"{api}/trace/{gene}", params={"comparison": cid})
        assert r.status_code == 200, r.text
        call = r.json()["trace"]["call"]
        cell = row["cells"][ids.index(cid)]
        assert call["conclusion"] == cell["conclusion"] and call["correction"] == "Dunnett"
        assert call["p_adjusted"] == pytest.approx(cell["p_adjusted"], rel=1e-6)

    # the figure draws the four conditions, a bracket per comparison
    info = sclient.get(
        f"{api}/report/figure/info", params={"gene": gene, "comparison": ids[2]}
    ).json()
    assert [g["name"] for g in info["groups"]] == ["20", "28", "D20", "D28"]
    assert "Dunnett" in info["caption"] and info["p_adjusted"] is not None

    # History and the Run Review name the comparisons
    history = sclient.get(f"{api}/history", params={"comparison": ids[1]}).json()
    assert history["comparison"] == ids[1] and len(history["comparisons"]) == 3
    review = sclient.get(f"{api}/review").json()
    assert review["comparisons"][0]["plain"].startswith("28 vs 20 (the first comparison)")
    no_html(side)
