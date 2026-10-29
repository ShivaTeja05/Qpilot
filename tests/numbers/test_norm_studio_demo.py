"""The normaliser axis end to end on the demo: a designed study, its card, and what follows it.

The demo's Studio design with the other normalisers and the plate corrections asked for, analysed
the way Studio analyses a confirmed design. A person decides the normaliser card (NormFinder's
best pair) and every view of "the analysis in use" follows it: Results, the Prism export, Trace;
the Analysis Record verifies and re-runs. The global mean has no reference wells: the export and
Trace refuse it in words. The reference panel compares geNorm and NormFinder.
"""

from __future__ import annotations

import json

import pytest

from qpilot.core.decisions import apply_decision
from qpilot.core.record import rerun_compare, verify, write_record
from qpilot.core.store import StudyStore
from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS
from qpilot.qpcr.designs import vermeulen_design
from tests.conftest import DEMO_RDML

pytestmark = pytest.mark.demo_data

ASKED = {
    "normaliser": ("planned", "normfinder_pair", "genorm_pair", "global_mean"),
    "interrun": ("none", "calibrator", "factor"),
}
PAIR = ("ALUsq(Eurogentec)", "HPRT1")


@pytest.fixture(scope="module")
def tested(tmp_path_factory):
    from qpilot.qpcr.axes import normaliser as norm_axis

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    # The global mean uses only genes with a value in every compared tumour (science review J7):
    # 45 of the demo's 64, below qPilot's 50. A lab may set its own minimum; 40 here keeps the
    # global mean's paths (its card option, the export and Trace refusing it) under test.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(norm_axis, "GLOBAL_MEAN_MIN_GENES", 40)
        store = StudyStore(tmp_path_factory.mktemp("studies"))
        design = vermeulen_design().model_copy(
            update={"amp_calls": STUDIO_AMP_CALLS, "axes": ASKED}
        )
        study_id = store.ensure_study(DEMO_RDML, design=design)
        yield store, study_id, design


def _decide(store, study_id, option, reason):
    head = store.chain_head(study_id)
    outcome = apply_decision(store, study_id, "card_normaliser", option, reason, "human", head)
    assert outcome.status == "applied", outcome


def test_the_card_and_the_analysis_in_use(tested):
    store, study_id, design = tested
    result = store.get(study_id)
    card = next(c for c in store.cards(study_id) if c.kind == "numbers.normaliser")
    assert card.status == "open" and card.recommended == "planned"
    assert [o.id for o in card.options] == ["planned", "normfinder_pair", "global_mean"]
    assert card.options[1].label.endswith("(ALUsq(Eurogentec), HPRT1)")
    assert result.facts["f_axis_interrun"].value == "not_applicable"
    assert not any(c.kind == "numbers.interrun" for c in store.cards(study_id))
    plain = StudyStore(store.root.parent / "plain")
    plain_id = plain.ensure_study(DEMO_RDML, design=design.model_copy(update={"axes": None}))
    for gene, contrast in plain.get(plain_id).contrasts.items():
        assert result.contrasts[gene].log2fc == pytest.approx(contrast.log2fc, abs=1e-12)


def test_results_and_the_reference_panel(tested):
    from qpilot.web import results_views as rv
    from qpilot.web.references_views import reference_stability

    store, study_id, _ = tested
    view = rv.results_view(store, study_id)
    norm = next(a for a in view.axes if a.name == "normaliser")
    assert norm.status == "swept" and norm.card_id == "card_normaliser"
    flips = {o.id: o.flips.value for o in norm.options if o.flips is not None}
    assert flips == {"normfinder_pair": 3, "global_mean": 9}  # 19 over all 64 genes, before J7
    assert any("agree on the best pair" in n.plain for n in norm.notes)
    interrun = next(a for a in view.axes if a.name == "interrun")
    assert interrun.status == "not_applicable"
    assert any("cancels" in (o.unavailable or "") for o in interrun.options)
    panel = reference_stability(store, study_id)
    assert panel.verdict == "agree" and panel.normfinder_pair.genes == list(PAIR)
    assert panel.groups == {"MYCN-high": 53, "rest": 294} and panel.n_left_out == 19
    ranks = {r.gene: r.normfinder_rank for r in panel.rows}
    assert ranks == {
        "ALUsq(Eurogentec)": 1,
        "HPRT1": 2,
        "SDHA(1)": 3,
        "UBC(2)": 4,
        "HMBS": 5,
    }


def test_a_decided_best_pair_is_the_analysis_in_use_everywhere(tested, tmp_path):
    from qpilot.qpcr.export import Reanalysis, study_inputs
    from qpilot.trace import build_context, model_for_study
    from qpilot.web import results_views as rv

    store, study_id, _ = tested
    _decide(store, study_id, "normfinder_pair", "NormFinder and geNorm agree on this pair")
    view = rv.results_view(store, study_id)
    assert view.choices["card_normaliser"] == "normfinder_pair"
    at = {g.gene: g.at_your_choices for g in view.genes}
    changed = sorted(g for g, a in at.items() if a is not None and a.differs)
    assert changed == ["DPYSL3", "PAICS", "PDE4DIP"]
    inputs = study_inputs(store, study_id, read_only=True)
    assert inputs.refs == PAIR  # the export divides by the pair
    compared, _ = Reanalysis(inputs).results()
    for gene in ("PAICS", "ODC1"):
        assert compared[gene].log2fc == pytest.approx(at[gene].log2fc, abs=1e-9)
    model = model_for_study(store, study_id)
    ctx = build_context(model, study_id, {"normaliser": "normfinder_pair"})
    assert tuple(ctx.cell["refs"]) == PAIR and "normaliser" not in ctx.cell
    j = ctx.items.index("PAICS")
    assert float(ctx.comparison.base.diff[j]) == pytest.approx(at["PAICS"].log2fc, abs=1e-9)
    record = tmp_path / "record"
    write_record(store, study_id, record, rdml_path=DEMO_RDML)
    assert verify(record).ok
    assert json.loads((record / "study_design.json").read_text())["axes"]["normaliser"] == list(
        ASKED["normaliser"]
    )
    again = rerun_compare(record, tmp_path / "rerun")
    assert again.same, again


def test_the_global_mean_is_refused_where_reference_wells_are_needed(tested):
    from qpilot.qpcr.export import ExportError, study_inputs
    from qpilot.trace import TraceError, build_context, model_for_study

    store, study_id, _ = tested
    _decide(store, study_id, "global_mean", "every gene's mean, to compare")
    with pytest.raises(ExportError, match="chose the global mean"):
        study_inputs(store, study_id, read_only=True)
    model = model_for_study(store, study_id)
    with pytest.raises(TraceError, match="no reference wells to follow"):
        build_context(model, study_id, {"normaliser": "global_mean"})


def test_methods_name_normfinder_and_the_global_mean(tested):
    from qpilot.report.build import build

    store, study_id, _ = tested
    text = json.dumps(build(store, study_id).model_dump(mode="json"), ensure_ascii=False)
    assert "NormFinder" in text and "Andersen CL" in text and "Mestdagh P" in text
    assert "inter-run calibration" in text and "neither can change a result" in text
