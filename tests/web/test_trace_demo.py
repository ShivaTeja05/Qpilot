"""Trace on the real demo study (Vermeulen 2013: 64 plates, 366 tumours, 58 compared genes).

The numbers ``qPilot-TRACE-PLAN.md`` measured with prototype scripts, re-measured here with the
engine (``qpilot.trace``) and with an independent brute-force re-run (scipy's Welch test on the
values with each tumour removed), and the speed of a trace after the model is kept.
"""

from __future__ import annotations

import math
import shutil
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import stats

from qpilot.core.store import StudyStore
from qpilot.qpcr.contrast import conclude
from qpilot.trace import build_context, model_for_study, trace_gene, trace_study
from qpilot.trace.welch import CALL_NAMES
from qpilot.web.context import make_context
from qpilot.web.routers import trace as trace_router
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN, wait_job

pytestmark = pytest.mark.demo_data


@pytest.fixture(scope="module")
def demo_study(tmp_path_factory):
    from qpilot.io.datasets import default_cache_dir

    rdml = default_cache_dir() / "data_vermeulen_raw.rdml"
    if not rdml.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    base = tmp_path_factory.mktemp("trace-demo") / "studies"
    store = StudyStore(base)
    return base, store, store.ensure_study(rdml)


@pytest.fixture(scope="module")
def ctx(demo_study):
    _, store, study_id = demo_study
    return build_context(model_for_study(store, study_id), study_id, labels=("MYCN-high", "rest"))


def rerun(ctx, j: int, drop: int | None) -> tuple[float, float, str]:
    """Gene ``j`` re-run from its values with one tumour removed (scipy, no closed form)."""
    used = ctx.comparison.used[:, j].copy()
    if drop is not None:
        used[drop] = False
    x = ctx.relative[:, j]
    a, b = x[used & ctx.in_a], x[used & ctx.in_b]
    t = stats.ttest_ind(a, b, equal_var=False)
    diff = float(a.mean() - b.mean())
    return diff, float(t.pvalue), conclude(diff, float(t.pvalue), ctx.rule)


def test_leave_one_out_equals_a_rerun_for_two_genes(ctx):
    for gene in ("CAMTA2", "ODC1"):
        j = ctx.items.index(gene)
        for i in np.flatnonzero(ctx.comparison.used[:, j]):
            diff, p, call = rerun(ctx, j, int(i))
            assert ctx.loo.after.diff[i, j] == pytest.approx(diff, abs=1e-10)
            assert ctx.loo.after.p[i, j] == pytest.approx(p, rel=1e-6)
            assert CALL_NAMES[int(ctx.loo.after.call[i, j])] == call


def test_the_plans_numbers(ctx):
    """§3 of the plan: 4 of 58 calls change with one tumour removed; at most 0.295 log2."""
    changed = ctx.loo.changed.any(axis=0)
    assert len(ctx.items) == 58
    assert sorted(np.array(ctx.items)[changed]) == ["CAMTA2", "DPYSL3", "IGSF4", "PRKACB_bis"]
    assert float(np.abs(ctx.loo.d_log2fc).max()) == pytest.approx(0.2948, abs=5e-4)
    # S1: 11 tumours with a control-gene well far from their other four (robust z > 3.5)
    assert int(ctx.ref.flagged.any(axis=1).sum()) == 11
    i = ctx.unit_index("2016")
    r = ctx.refs.index("HMBS")
    assert ctx.ref.flagged[i, r]
    assert ctx.ref.pull[i, r] == pytest.approx(2.47, abs=0.01)  # every value 5.5x too high
    assert 2 ** ctx.ref.pull[i, r] == pytest.approx(5.55, abs=0.02)
    for unit, gene in (("1924", "HPRT1"), ("1772", "UBC(2)")):
        assert ctx.ref.flagged[ctx.unit_index(unit), ctx.refs.index(gene)]


def test_camta2_points_at_the_three_wells(ctx):
    out = trace_gene(ctx, "CAMTA2")
    trace = out.data
    assert trace.call.conclusion == "none" and trace.n_flip_single == 15
    assert trace.flip.k == 1 and trace.flip.exact
    where = {(p.unit, w.key) for p in trace.places for w in p.wells if "reference_pull" in w.flags}
    assert {
        ("2016", "HMBS_20080318/K22"),
        ("1924", "HPRT1_20080303/F23"),
        ("1772", "UBC(2)_20080220/O13"),
    } <= where
    first = trace.places[0]
    assert first.consequence == "changes_call" and first.kind == "reference_well"
    assert first.unit in ("2016", "1772")
    assert trace.look_first.kind == "place" and trace.look_first.well is not None
    k22 = next(p for p in trace.places if p.unit == "2016")
    well = next(w for w in k22.wells if w.key == "HMBS_20080318/K22")
    assert well.cq == pytest.approx(46.06, abs=0.01) and "reference_pull" in well.flags
    read = next(o for o in k22.options if o.id == "read_from_other_references")
    assert read.regrouped and "2016 leaves MYCN-high" in read.regrouped
    # with the groups held, reading K22 from the other four changes CAMTA2 and IGSF4 (§3, #5)
    held = {c.gene for c in read.fixed_groups_changes or []}
    assert {"CAMTA2", "IGSF4"} <= held
    assert "Look here first" in out.plain("look_first")


def test_the_study_overview_names_the_fragile_genes_and_the_missing_tumours(ctx):
    out = trace_study(ctx)
    study = out.data
    one = [g.gene for g in study.genes if g.flip_k == 1]
    assert sorted(one) == ["CAMTA2", "DPYSL3", "IGSF4", "PRKACB_bis"]
    assert [g.rank for g in study.genes] == list(range(1, 59))
    assert len(study.left_out) == 19  # §3, #9: tumours silently in no comparison
    empty = {m.unit: [w.key for w in m.wells] for m in study.left_out}
    assert "HMBS_20080318/A22" in empty["1846"]
    assert sum(1 for m in study.left_out if m.reason == "empty_reference") >= 14
    flagged = {s.unit for s in study.suspects if "reference_pull" in s.flags}
    assert {"2016", "1924", "1772"} <= flagged
    assert "4 change their call when a single sample is set aside" in out.plain("summary")


def test_speed_after_the_model_is_kept(ctx):
    """Measured on an M3 Pro: context 0.1 s, a gene 0.05-0.15 s, the overview 0.6 s cold."""
    start = time.perf_counter()
    fresh = build_context(ctx.model, ctx.study_id, labels=ctx.labels)
    built = time.perf_counter() - start
    trace_study(fresh)
    overview = time.perf_counter() - start - built
    start = time.perf_counter()
    for gene in ("ODC1", "NTRK1", "BIRC5", "NM23A"):
        trace_gene(fresh, gene)
    per_gene = (time.perf_counter() - start) / 4
    assert built < 2.0 and overview < 6.0 and per_gene < 1.0, (built, overview, per_gene)


def test_the_route_on_the_demo(demo_study, tmp_path):
    base, _, study_id = demo_study
    shutil.copytree(base, tmp_path / "studies")
    store = StudyStore(tmp_path / "studies")
    context = make_context(store, token=TOKEN, watch=False)
    trace_router.clear()
    try:
        with TestClient(create_app(context), base_url=BASE) as c:
            c.headers["x-qpilot-token"] = TOKEN
            r = c.get(f"/api/studies/{study_id}/trace/ODC1")
            if r.status_code == 409:
                assert r.json()["error"]["code"] == "loading"
                assert wait_job(c, r.json()["error"]["details"]["job"])["status"] == "done"
                r = c.get(f"/api/studies/{study_id}/trace/ODC1")
            assert r.status_code == 200, r.text
            body = r.json()
            row = next(
                g for g in c.get(f"/api/studies/{study_id}/results").json()["genes"]
                if g["gene"] == "ODC1"
            )  # fmt: skip
            assert body["trace"]["call"]["log2fc"] == pytest.approx(row["log2fc"], abs=1e-9)
            assert body["trace"]["call"]["conclusion"] == row["conclusion"] == "up"
            assert math.isclose(body["trace"]["call"]["fc"], row["fc"], rel_tol=1e-9)
            start = time.perf_counter()
            assert c.get(f"/api/studies/{study_id}/trace/BIRC5").status_code == 200
            assert time.perf_counter() - start < 2.0
    finally:
        context.close()
        trace_router.clear()
