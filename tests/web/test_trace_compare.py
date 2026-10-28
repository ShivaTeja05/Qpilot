"""Trace and Where to look in a study with several comparisons, against the engine itself.

On the synthetic three-group file (Control, Drug A, Drug B; ACTB lowered by Drug B) every
comparison can be traced: Trace's call is the engine's corrected call (Holm, Dunnett, Tukey),
its p before correction, corrected p and q are labelled as such, and every closed-form what-if
(one sample set aside, two together, the greedy set) gives the call the engine gives when the
same samples are set aside in every comparison. A paired comparison is refused in words; an
unknown comparison is a 404. Where to look follows the comparison and says so.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from qpilot.qpcr import trace as places_engine
from qpilot.qpcr.contrast import bh
from qpilot.trace import TraceError, build_context, model_for_study
from qpilot.trace.welch import CALL_NAMES
from qpilot.web.routers import trace as trace_router
from qpilot.web.routers import where as where_router
from tests.fixtures.studio.compare_mini import design, write_compare_mini
from tests.web.test_studio_flow import no_html
from tests.web.test_trace_routes import ready

A, B, BA = "drug_a_vs_control", "drug_b_vs_control", "drug_b_vs_drug_a"
SHIFT = {("ACTB", "Drug B"): 2.5}
DESIGNS = {
    "holm": lambda: design(),
    "dunnett": lambda: design(correction="dunnett"),
    "tukey": lambda: design(pattern="all_pairs", correction="tukey"),
}


@pytest.fixture(autouse=True)
def fresh_caches():
    trace_router.clear()
    where_router.clear()
    yield
    trace_router.clear()
    where_router.clear()


@pytest.fixture
def studies(web_store, tmp_path, monkeypatch):
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))
    path = write_compare_mini(tmp_path / "shift.rdml", ref_shift=SHIFT)
    out = {name: web_store.ensure_study(path, make()) for name, make in DESIGNS.items()}
    out["paired"] = web_store.ensure_study(path, design(paired=True))
    out["store"] = web_store
    return out


def _engine_without(model, cid, cell, rows):
    """The engine's results of comparison ``cid`` with units ``rows`` set aside everywhere."""
    space = model.space.focus(cid)
    values, refs = space.cell_arrays(cell)
    hi, lo = space.group_masks(cell)
    hi[list(rows)] = lo[list(rows)] = False
    return space.evaluate_arrays(values, refs, hi, lo)


@pytest.mark.parametrize("name", list(DESIGNS))
def test_every_what_if_is_the_engines_corrected_call(studies, name):
    store, sid = studies["store"], studies[name]
    model = model_for_study(store, sid)
    result = store.get(sid)
    for outcome in result.comparisons.comparisons:
        ctx = build_context(model, sid, comparison=outcome.id)
        assert ctx.comparison_id == outcome.id and ctx.correction == name
        assert ctx.labels == (outcome.group_a, outcome.group_b)
        for j, gene in enumerate(ctx.items):  # the base call and both p-values are the engine's
            stored = outcome.contrasts[gene]
            assert CALL_NAMES[int(ctx.base.call[j])] == stored.conclusion
            assert ctx.base.p[j] == pytest.approx(stored.p, rel=1e-9)
            assert ctx.base.p_adj[j] == pytest.approx(outcome.p_adjusted[gene], rel=1e-7)
        np.testing.assert_allclose(ctx.q, bh(np.array([outcome.contrasts[g].p for g in ctx.items])))
        cell = dict(model.space.primary)
        for i in np.flatnonzero(ctx.comparison.used.any(axis=1)):  # one unit set aside
            exact = _engine_without(model, outcome.id, cell, [i])
            for j in range(len(ctx.items)):
                if not ctx.comparison.used[i, j]:
                    continue
                assert CALL_NAMES[int(ctx.loo.after.call[i, j])] == exact.conclusion[j]
                assert ctx.loo.after.diff[i, j] == pytest.approx(exact.log2fc[j], abs=1e-9)
        for j in range(len(ctx.items)):  # two units set aside together
            rows, _, call = ctx.comparison.pairs(j)
            for u, v in [(0, 1), (0, len(rows) - 1), (2, 5)]:
                if v >= len(rows):
                    continue
                exact = _engine_without(model, outcome.id, cell, [rows[u], rows[v]])
                assert CALL_NAMES[int(call[u, v])] == exact.conclusion[j]
                after = ctx.comparison.without((int(rows[u]), int(rows[v])), j)
                if math.isfinite(float(exact.p[j])):
                    assert float(after.p_adj) == pytest.approx(float(exact.p_call[j]), rel=1e-7)


def test_the_call_reads_corrected_p_q_and_the_p_before_correction(client, studies):
    sid = studies["holm"]
    r = ready(client, f"/api/studies/{sid}/trace/MYC?comparison={B}")
    assert r.status_code == 200, r.text
    body = r.json()
    trace = body["trace"]
    assert trace["comparison"] == B and trace["comparison_label"] == "Drug B vs Control"
    assert trace["labels"] == ["Drug B", "Control"]
    call = trace["call"]
    outcome = next(o for o in studies["store"].get(sid).comparisons.comparisons if o.id == B)
    assert call["conclusion"] == outcome.contrasts["MYC"].conclusion == "up"
    assert call["p"] == pytest.approx(outcome.contrasts["MYC"].p)
    assert call["p_adjusted"] == pytest.approx(outcome.p_adjusted["MYC"])
    assert call["q"] == pytest.approx(outcome.q_value["MYC"])
    assert call["correction"] == "Holm"
    summary = body["texts"]["summary"]["plain"]
    assert "corrected p 0.003 (Holm), q 0.002; p before correction 0.001" in summary
    assert "corrected p below" in summary and "corrected p" in trace["rule"]
    first = ready(client, f"/api/studies/{sid}/trace/MYC").json()
    assert first["trace"]["comparison"] == A and first["trace"]["call"]["conclusion"] == "none"
    overview = ready(client, f"/api/studies/{sid}/trace?comparison={B}").json()
    assert overview["trace"]["comparison"] == B
    row = next(g for g in overview["trace"]["genes"] if g["gene"] == "MYC")
    assert row["p_adjusted"] == pytest.approx(outcome.p_adjusted["MYC"])
    no_html(body)


def test_a_what_if_without_samples_follows_the_comparison(client, studies):
    sid = studies["dunnett"]
    ready(client, f"/api/studies/{sid}/trace/MYC?comparison={B}")
    r = client.post(
        f"/api/studies/{sid}/trace/MYC/without",
        params={"comparison": B},
        json={"samples": ["DrugB_D1", "DrugB_D2"]},
    )
    assert r.status_code == 200, r.text
    after = r.json()["result"]["after"]
    assert after["correction"] == "Dunnett" and after["p_adjusted"] is not None
    assert after["p_adjusted"] >= after["p"]


def test_paired_and_unknown_comparisons_are_refused_in_words(client, studies):
    sid = studies["paired"]
    r = ready(client, f"/api/studies/{sid}/trace/MYC?comparison={B}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_traceable"
    assert "paired comparison (by donor)" in r.json()["error"]["message"]
    r = client.get(f"/api/studies/{studies['holm']}/trace/MYC", params={"comparison": "nope"})
    assert r.status_code == 404 and "it has:" in r.json()["error"]["message"]
    with pytest.raises(TraceError, match="no comparison"):
        build_context(model_for_study(studies["store"], studies["holm"]), comparison="nope")


def test_where_to_look_follows_the_comparison(client, studies):
    sid = studies["tukey"]
    ready(client, f"/api/studies/{sid}/trace/MYC?comparison={BA}")
    r = client.get(f"/api/studies/{sid}/where-to-look", params={"gene": "MYC", "comparison": BA})
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["comparison"] == BA and "Drug B vs Drug A" in view["comparison_note"]
    assert "every comparison" in view["comparison_note"]
    first = client.get(f"/api/studies/{sid}/where-to-look", params={"gene": "MYC"}).json()
    assert first["comparison"] == A
    no_html(view)


def test_where_to_look_calls_are_exact_under_a_correction(studies):
    store, sid = studies["store"], studies["holm"]
    model = model_for_study(store, sid)
    ctx = places_engine.build_context(model.inputs.primary_table, model, comparison=B)
    space = model.space.focus(B)
    values, refs = space.cell_arrays()
    hi, lo = space.group_masks()
    for i in np.flatnonzero(ctx.used):
        h, l_ = hi.copy(), lo.copy()
        h[i] = l_[i] = False
        exact = space.evaluate_arrays(values, refs, h, l_)
        for j in range(len(ctx.items)):
            if ctx.valid[i, j]:
                assert ctx.loo_call[i, j] == exact.conclusion[j]
