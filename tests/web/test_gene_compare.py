"""A gene's page in a study with several comparisons: each unit's values and the figure follow it.

On the synthetic three-group file (Control, Drug A, Drug B): ``?comparison=`` on
``/genes/{gene}/units`` gives that comparison's two groups, its stored fold change, the p before
correction, the corrected p and q; a paired comparison's fold change is checked as the mean of
its within-pair differences; the figure draws every group with a bracket per comparison, the
chosen one in ink, and its caption names each comparison's corrected p. A study with one
comparison answers as before.
"""

from __future__ import annotations

import numpy as np
import pytest

from qpilot.report.figures import figure_svg, gene_figure, group_order
from qpilot.report.tables import study_tables
from tests.fixtures.studio.compare_mini import design, write_compare_mini
from tests.web.test_studio_flow import no_html

A, B = "drug_a_vs_control", "drug_b_vs_control"


@pytest.fixture
def studies(web_store, tmp_path, monkeypatch):
    from qpilot.web import units_views

    units_views.clear_cache()
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))
    path = write_compare_mini(tmp_path / "mini.rdml", missing_well=True)
    out = {
        "holm": web_store.ensure_study(path, design()),
        "paired": web_store.ensure_study(path, design(paired=True)),
        "tukey": web_store.ensure_study(path, design(pattern="all_pairs", correction="tukey")),
        "one": web_store.ensure_study(path, design().model_copy(update={"comparisons": None})),
        "store": web_store,
    }
    yield out
    units_views.clear_cache()


@pytest.mark.parametrize("name", ["holm", "paired"])
def test_each_units_values_follow_the_comparison(client, studies, name):
    sid = studies[name]
    stored = {o.id: o for o in studies["store"].get(sid).comparisons.comparisons}
    for cid in (A, B):
        r = client.get(f"/api/studies/{sid}/genes/MYC/units", params={"comparison": cid})
        assert r.status_code == 200, r.text
        view = r.json()
        outcome = stored[cid]
        assert view["comparison"] == cid and view["comparison_label"] == outcome.label
        assert view["groups"]["high"]["label"] == outcome.group_a
        assert view["groups"]["rest"]["label"] == outcome.group_b
        assert view["fold_log2"] == pytest.approx(outcome.contrasts["MYC"].log2fc, abs=1e-9)
        assert view["p"] == pytest.approx(outcome.contrasts["MYC"].p)
        assert view["p_adjusted"] == pytest.approx(outcome.p_adjusted["MYC"])
        assert view["q"] == pytest.approx(outcome.q_value["MYC"])
        assert view["correction"] == "Holm" and view["paired"] == (name == "paired")
        groups = {p["group"] for p in view["points"]}
        assert groups == {"high", "rest"}
        no_html(view)
    # TP53 lacks DrugB_D4: a paired comparison's fold change is the complete pairs' mean
    r = client.get(f"/api/studies/{sid}/genes/TP53/units", params={"comparison": B})
    assert r.status_code == 200, r.text
    assert r.json()["fold_log2"] == pytest.approx(stored[B].contrasts["TP53"].log2fc, abs=1e-9)


def test_units_refuse_an_unknown_comparison_and_keep_one_comparison_studies(client, studies):
    r = client.get(f"/api/studies/{studies['holm']}/genes/MYC/units", params={"comparison": "nope"})
    assert r.status_code == 404 and "it has:" in r.json()["error"]["message"]
    one = client.get(f"/api/studies/{studies['one']}/genes/MYC/units").json()
    assert one["comparison"] is None and one["p_adjusted"] is None and one["q"] is None
    assert one["groups"]["high"]["label"] == "Drug A"


def test_the_figure_draws_every_group_and_a_bracket_per_comparison(client, studies):
    sid = studies["tukey"]
    info = client.get(
        f"/api/studies/{sid}/report/figure/info", params={"gene": "MYC", "comparison": B}
    ).json()
    assert info["comparison"] == "Drug B vs Control"  # the id names the comparison too
    assert [g["name"] for g in info["groups"]] == ["Control", "Drug A", "Drug B"]
    outcome = next(o for o in studies["store"].get(sid).comparisons.comparisons if o.id == B)
    assert info["p_adjusted"] == pytest.approx(outcome.p_adjusted["MYC"])
    caption = info["caption"]
    assert "Drug B vs Control, fold change" in caption and "corrected p" in caption
    assert "Drug B vs Drug A" in caption and "Tukey" in caption
    assert "The bracket in black is Drug B vs Control" in caption
    tables = study_tables(studies["store"], sid)
    fig = gene_figure(tables, "MYC", comparison="Drug B vs Control")
    assert [b.name for b in fig.brackets][0] == "Drug B vs Control" and fig.brackets[0].chosen
    assert sum(b.chosen for b in fig.brackets) == 1 and len(fig.brackets) == 3
    svg = figure_svg(fig)
    assert svg.count('class="bracket"') == 9  # three brackets, a line and two ends each
    for group in fig.groups:  # every group's dots are the per-unit values of its comparison
        units = dict(group.points)
        assert all(np.isfinite(v) for v in units.values()) and units
    assert group_order(tables.analysis("as_decided").comparisons) == [
        "Control",
        "Drug A",
        "Drug B",
    ]


def test_a_study_with_one_comparison_keeps_its_figure(client, studies):
    info = client.get(
        f"/api/studies/{studies['one']}/report/figure/info", params={"gene": "MYC"}
    ).json()
    assert [g["name"] for g in info["groups"]] == ["Drug A", "Control"]
    assert info["p_adjusted"] is None
    fig = gene_figure(study_tables(studies["store"], studies["one"]), "MYC")
    assert fig.brackets == ()
