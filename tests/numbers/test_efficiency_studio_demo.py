"""The efficiency models end to end on the demo: a designed study, its card, and what follows it.

The demo's Studio design (the published preset with Studio's amplification rules) with the
efficiency models asked for, analysed in a throwaway store the way Studio analyses a confirmed
design (``StudyStore.ensure_study``). Then a person decides the efficiency card and every view
that shows "the analysis in use" follows it: Results, Trace, the Prism export, the audit bridge.
The Analysis Record verifies and re-runs it, and ``qpilot run --efficiency`` gives the same card.
"""

from __future__ import annotations

import json
import math

import pytest

from qpilot.core.decisions import apply_decision
from qpilot.core.record import rerun_compare, verify, write_record
from qpilot.core.store import StudyStore
from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS
from qpilot.qpcr.designs import study_key, vermeulen_design
from tests.conftest import DEMO_RDML

pytestmark = pytest.mark.demo_data

ASKED = ("linregpcr", "per_well", "amplicon_mean", "assumed_2", "standard_curve")
TESTED = ["linregpcr", "per_well", "assumed_2", "standard_curve"]  # one plate per assay


@pytest.fixture(scope="module")
def tested(tmp_path_factory):
    """A store with the demo's Studio design, the efficiency models asked for, analysed."""
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    store = StudyStore(tmp_path_factory.mktemp("studies"))
    design = vermeulen_design().model_copy(
        update={"amp_calls": STUDIO_AMP_CALLS, "axes": {"efficiency": ASKED}}
    )
    study_id = store.ensure_study(DEMO_RDML, design=design)
    return store, study_id, design


@pytest.fixture(scope="module")
def decided(tested):
    """The same study with the efficiency card decided by a person: each well's own."""
    store, study_id, _ = tested
    head = store.chain_head(study_id)
    outcome = apply_decision(
        store, study_id, "card_efficiency", "per_well", "the assay's own wells", "human", head
    )
    assert outcome.status == "applied", outcome
    return tested


def test_the_study_is_its_own_and_raises_the_efficiency_card(tested):
    store, study_id, design = tested
    result = store.get(study_id)
    assert study_id == study_key(result.input_sha256, design)[:12]
    assert store.design(study_id).axes == {"efficiency": ASKED}
    card = next(c for c in store.cards(study_id) if c.kind == "numbers.efficiency_model")
    assert card.id == "card_efficiency" and card.status == "open"
    assert [o.id for o in card.options] == TESTED and card.recommended == "linregpcr"
    assert card.impact["n_genes_flipped"] == result.facts["f_n_flipped_efficiency"].value == 6
    assert result.facts["f_axis_efficiency"].value == "swept"
    assert "one run" in result.facts["f_axis_efficiency_unavailable_amplicon_mean"].value
    assert result.facts["f_eff_label_per_well"].value == "each well's own efficiency"
    # the analysis in use is the one without the efficiency models
    plain = StudyStore(store.root.parent / "plain")
    plain_id = plain.ensure_study(DEMO_RDML, design=design.model_copy(update={"axes": None}))
    for gene, contrast in plain.get(plain_id).contrasts.items():
        assert result.contrasts[gene].log2fc == pytest.approx(contrast.log2fc, abs=1e-12)


def test_results_say_what_the_grid_did_with_it(tested):
    from qpilot.web import results_views as rv

    store, study_id, _ = tested
    result = store.get(study_id)
    axis, *others = rv.results_view(store, study_id).axes
    assert axis.name == "efficiency" and [a.name for a in others] == ["normaliser", "interrun"]
    assert axis.status == "swept" and axis.card_id == "card_efficiency"
    assert not axis.can_propose and axis.command == "qpilot run --efficiency all"
    flips = {o.id: o.flips.value for o in axis.options if o.flips is not None}
    assert flips == {"per_well": 5, "assumed_2": 4, "standard_curve": 3}
    assert all(o.flips.id in result.facts for o in axis.options if o.flips is not None)
    assert [f.id for f in axis.text.facts] == ["f_n_flipped_efficiency", "f_n_genes"]
    assert "9" in axis.notes[0].plain and axis.notes[0].facts[0].id == "f_n_eff_excluded_per_well"
    row = next(r for r in rv.flips_view(store, study_id).rows if r.dimension == "efficiency")
    assert row.title == "Which efficiency turns Cq into quantity"
    assert row.card_id == "card_efficiency" and row.n_flipped == 6
    assert [o.card_option for o in row.options] == TESTED
    card = next(c for c in rv.cards_view(store, study_id).cards if c.card.id == "card_efficiency")
    assert card.title == "Which efficiency turns Cq into quantity"
    assert card.impact.plain == "6 of 58 conclusions change with this choice"
    assert "with each well's own efficiency, 5 of 58 genes" in card.explanation.plain


def test_the_decided_model_is_the_analysis_in_use_everywhere(decided):
    from qpilot.integration.simulator import chosen_changes, load_analysis, prepare
    from qpilot.qpcr.export import Reanalysis, study_inputs
    from qpilot.trace import build_context, model_for_study
    from qpilot.web import results_views as rv

    store, study_id, _ = decided
    view = rv.results_view(store, study_id)
    assert view.choices["card_efficiency"] == "per_well"
    at = {g.gene: g.at_your_choices for g in view.genes}
    assert at["PAICS"] is not None and at["PAICS"].differs and at["PAICS"].conclusion == "up"
    # the Prism export: its tables are the decided model's numbers
    inputs = study_inputs(store, study_id, read_only=True)
    efficiency = next(c for c in inputs.choices if c.dimension == "efficiency")
    assert (efficiency.option, efficiency.actor) == ("per_well", "human")
    compared, _ = Reanalysis(inputs).results()
    for gene in ("PAICS", "CAMTA2", "NTRK1", "ODC1"):
        assert compared[gene].log2fc == pytest.approx(at[gene].log2fc, abs=1e-9)
    table = inputs.table("column", ["PAICS"])
    means = table.groupby("group")["log2_rq"].mean()
    hi, lo = inputs.group_order
    assert means[hi] - means[lo] == pytest.approx(compared["PAICS"].log2fc, abs=1e-9)
    # Trace at the analysis in use reproduces the engine's numbers (or it would refuse)
    model = model_for_study(store, study_id)
    choice = {"efficiency": "per_well"}
    ctx = build_context(model, study_id, choice, labels=("MYCN-high", "rest"))
    j = ctx.items.index("PAICS")
    assert ctx.cell["efficiency"] == "per_well" and not ctx.planned
    assert float(ctx.comparison.base.diff[j]) == pytest.approx(at["PAICS"].log2fc, abs=1e-9)
    # the robustness audit maps the choice onto its own efficiency decision
    pytest.importorskip("qsim")
    changes, notes = chosen_changes(prepare(load_analysis(store, study_id)), inputs.choices)
    assert changes.get("efficiency") == "per_well"
    assert not any("efficiency" in n for n in notes)


def test_the_record_verifies_and_reruns_with_the_models(decided, tmp_path):
    store, study_id, _ = decided
    record = tmp_path / "record"
    write_record(store, study_id, record, rdml_path=DEMO_RDML)
    assert verify(record).ok
    design = json.loads((record / "study_design.json").read_text())
    assert design["axes"] == {"efficiency": list(ASKED)}
    again = rerun_compare(record, tmp_path / "rerun")
    assert again.same, again


def test_qpilot_run_tests_the_models_under_their_own_study_id(tested, tmp_path, capsys):
    from qpilot.cli import main

    store, study_id, _ = tested
    out = tmp_path / "out"
    assert main(["run", str(DEMO_RDML), "--efficiency", "all", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Efficiency models: tested as one more choice of the grid" in printed
    assert "amplicon_mean not applicable: every amplicon is on one run" in printed
    assert "numbers.efficiency_model: changes 6 of 58 conclusions; needs a human" in printed
    result = json.loads((out / "results.json").read_text())
    legacy = store.get(study_id).input_sha256[:12]
    assert result["study_id"] != legacy  # never the legacy analysis's id
    facts = json.loads((out / "facts.json").read_text())
    assert facts["f_axis_efficiency"]["value"] == "swept"
    assert facts["f_n_flipped_efficiency"]["value"] == 6
    header = (out / "grid.csv").read_text().splitlines()[0].split(",")
    assert "efficiency" in header and "efficiency__idx" in header
    assert not math.isnan(result["contrasts"]["ODC1"]["log2fc"])
