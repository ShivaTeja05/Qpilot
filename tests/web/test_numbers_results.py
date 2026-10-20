"""Results, genes, flips, cards and decisions serve the engine's numbers, not the views' own.

Every expected number comes from :mod:`tests.web.numbers_engine`: the study run again from the
RDML file and every decision option evaluated with the engine's decision space. The API reads
the store (``results.json``, ``cards.json``, ``grid.csv``) and finds the planned analysis and
each card's option in the grid by value; these tests check that what it serves is what the
engine computes, on the three demo studies: the ``qpilot run`` analysis (186 analyses), the
Studio design before the Prism round trip, and after it (744 analyses each).

``grid.csv`` keeps 10 significant digits (``write_outputs``), so numbers the API reads from the
grid are compared to 1e-9 relative; numbers it reads from ``results.json`` and ``cards.json``
must be equal exactly.
"""

from __future__ import annotations

import math
import shutil
from collections import Counter

import pandas as pd
import pytest

from qpilot.cli.studio_cmds import EXPECTED
from tests.conftest import DEMO_RDML
from tests.web.numbers_engine import CARD_DIMENSION, Engine, engine, flips_alone, holds
from tests.web.numbers_world import BASE, World, api_client, demo_world, get_json

pytestmark = pytest.mark.demo_data

STUDIES = ["legacy", "before_roundtrip", "study"]
GRID_REL = 1e-9


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return demo_world(tmp_path_factory.getbasetemp() / "numbers-demo", DEMO_RDML)


@pytest.fixture(scope="module")
def api(world):
    with api_client(world.store) as client:
        yield client


@pytest.fixture(scope="module", params=STUDIES)
def which(request, world) -> tuple[str, Engine]:
    study_id = getattr(world, request.param)
    if study_id is None:
        pytest.skip("this store has no study before the round trip")
    return study_id, engine(world, study_id)


@pytest.fixture(scope="module")
def results(api, which) -> dict:
    return get_json(api, f"/api/studies/{which[0]}/results")


def _close(a: float, b: float, rel: float = GRID_REL) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-300)


def _contrast(c) -> dict:
    return {
        "conclusion": c.conclusion,
        "fc": c.fc,
        "log2fc": c.log2fc,
        "ci": [float(c.ci[0]), float(c.ci[1])],
        "p": c.p,
        "n_hi": c.n_hi,
        "n_lo": c.n_lo,
    }


# ---- the results view ------------------------------------------------------------------------


def test_every_gene_row_is_the_engine_contrast(results, which):
    _, eng = which
    rows = {r["gene"]: r for r in results["genes"]}
    assert list(rows) == list(eng.result.contrasts)
    for gene, contrast in eng.result.contrasts.items():
        got = {k: rows[gene][k] for k in ("conclusion", "fc", "log2fc", "ci", "p", "n_hi", "n_lo")}
        assert got == _contrast(contrast), gene


def test_holds_and_confidence_are_the_engine(results, which):
    _, eng = which
    for row in results["genes"]:
        gene = row["gene"]
        robust, grade = eng.result.robustness[gene], eng.result.confidence[gene]
        assert row["holds"] == robust.holds, gene
        assert math.isclose(row["holds"], holds(eng, gene), abs_tol=1e-12), gene
        assert row["n_cells"] == robust.n_cells == len(eng.grid) // len(eng.result.contrasts)
        assert (row["level"], row["reasons"], row["min_flip_changes"]) == (
            grade.level,
            grade.reasons,
            grade.min_flip_changes,
        ), gene
        assert row["efficiency"] == eng.result.efficiency.get(gene), gene


def test_flips_by_is_each_decision_alone_recomputed(results, which):
    _, eng = which
    alone = {dim: flips_alone(eng, dim) for dim in eng.space.dimensions}
    for row in results["genes"]:
        want = sorted(dim for dim, by_gene in alone.items() if by_gene[row["gene"]])
        assert row["flips_by"] == want, row["gene"]


def test_counts_and_levels_add_up(results, which):
    _, eng = which
    calls = Counter(c.conclusion for c in eng.result.contrasts.values())
    assert results["counts"] == {c: calls.get(c, 0) for c in ("up", "down", "none")}
    assert results["levels"] == dict(Counter(g.level for g in eng.result.confidence.values()))
    assert sum(results["counts"].values()) == results["summary"]["n_genes"]


def test_the_summary_rule_and_references(results, which, world):
    study_id, eng = which
    r = eng.result
    summary = results["summary"]
    assert (summary["n_plates"], summary["n_reactions"], summary["n_samples"]) == (
        r.n_plates,
        r.n_reactions,
        r.n_samples,
    )
    assert summary["n_genes"] == len(r.contrasts)
    high, rest = eng.space.groups(eng.primary.get("cut"))
    assert [g["n"] for g in summary["groups"]] == [len(high), len(rest)]
    assert [g["n"] for g in summary["groups"]] == [r.design.n_hi, r.design.n_lo]
    rule = results["rule"]
    assert (rule["alpha"], rule["min_log2fc"]) == (
        eng.settings.rule.alpha,
        eng.settings.rule.min_log2fc,
    )
    assert rule["min_fold"] == 2**eng.settings.rule.min_log2fc
    refs = results["references"]
    assert refs["used"] == list(eng.primary["refs"])
    assert refs["m"] == r.genorm.M_initial
    assert refs["v"] == r.genorm.V
    assert refs["order"] == r.genorm.order
    assert refs["recommended"] == list(r.genorm.recommended)
    assert (refs["cutoff_m"], refs["cutoff_v"]) == (r.genorm.cutoff_M, r.genorm.cutoff_V)
    assert refs["stable"] == [g for g, m in r.genorm.M_initial.items() if m < r.genorm.cutoff_M]
    assert set(results["headline"]) == {g for g in eng.settings.headline if g in r.contrasts}


def test_choices_and_waiting_cards_are_the_chain(results, which, world):
    study_id, _ = which
    cards = world.store.cards(study_id)
    assert results["choices"] == {c.id: c.decision for c in cards if c.decision is not None}
    assert results["cards_waiting"] == sum(
        1 for c in cards if c.status in ("open", "pending_human")
    )
    assert results["pending_requests"] == len(world.store.pending(study_id))
    assert results["head"] == world.store.chain_head(study_id)


# ---- the flip matrix -------------------------------------------------------------------------


def test_the_flip_matrix_is_each_option_recomputed(api, which):
    study_id, eng = which
    view = get_json(api, f"/api/studies/{study_id}/flips")
    genes = view["genes"]
    planned = eng.at()
    assert genes == list(eng.result.contrasts)
    assert view["planned"] == [planned[g].conclusion for g in genes]
    assert sorted(row["dimension"] for row in view["rows"]) == sorted(eng.space.dimensions)
    for row in view["rows"]:
        dim = row["dimension"]
        assert [o["value"] for o in row["options"]] == [
            "|".join(v) if isinstance(v, tuple) else str(v) for v in eng.space.dimensions[dim]
        ]
        deltas = dict.fromkeys(genes, 0.0)
        for option in row["options"]:
            value = eng.grid_value(dim, option["value"])
            assert option["planned"] == (value == eng.primary[dim]), (dim, option["value"])
            at = eng.at(**{dim: value})
            assert option["conclusion"] == [at[g].conclusion for g in genes], (dim, value)
            for i, g in enumerate(genes):
                assert _close(option["log2fc"][i], at[g].log2fc), (dim, value, g)
                deltas[g] = max(deltas[g], abs(at[g].log2fc - planned[g].log2fc))
            assert option["flips"] == [at[g].conclusion != planned[g].conclusion for g in genes]
        alone = flips_alone(eng, dim)
        assert row["flips"] == [alone[g] for g in genes], dim
        assert row["n_flipped"] == sum(alone.values()), dim
        for i, g in enumerate(genes):
            assert math.isclose(row["max_delta_log2fc"][i], deltas[g], abs_tol=1e-9), (dim, g)


# ---- Decision Cards --------------------------------------------------------------------------


def test_each_card_option_is_the_engine_at_that_option(api, which, world):
    study_id, eng = which
    view = get_json(api, f"/api/studies/{study_id}/cards")
    engine_cards = {c.id: c for c in eng.cards}
    assert {c["card"]["id"] for c in view["cards"]} == set(engine_cards)
    for item in view["cards"]:
        card = engine_cards[item["card"]["id"]]
        dim = CARD_DIMENSION[card.kind]
        values = eng.option_values(card)
        assert item["card"]["impact"] == card.impact, card.id
        recommended = eng.at(**{dim: values[card.recommended]})
        for option in item["options"]:
            at = eng.at(**{dim: values[option["id"]]})
            for effect in option["effects"]:
                g = effect["gene"]
                got = {k: effect[k] for k in ("conclusion", "fc", "log2fc", "ci", "p")}
                want = _contrast(at[g])
                del want["n_hi"], want["n_lo"]
                assert got == want, (card.id, option["id"], g)
                assert effect["changes_call"] == (at[g].conclusion != recommended[g].conclusion)
        flipped = sum(flips_alone(eng, dim).values())
        assert card.impact["n_genes_flipped"] == flipped, card.id
        if card.impact["flips"]:
            cited = {f["id"]: f["value"] for f in item["impact"]["facts"]}
            assert cited.get("f_n_genes") == len(eng.result.contrasts), card.id
            assert flipped in cited.values(), (card.id, cited)


def test_the_decisions_are_the_chain(api, which, world):
    study_id, _ = which
    view = get_json(api, f"/api/studies/{study_id}/decisions")
    entries = world.store.entries(study_id)
    assert [e["entry"] for e in view["entries"]] == [e.model_dump(mode="json") for e in entries]
    labels = {(c.id, o.id): o.label for c in world.store.cards(study_id) for o in c.options}
    for e in view["entries"]:
        assert e["option_label"] == labels[(e["entry"]["card_id"], e["entry"]["option"])]
    assert view["head"] == world.store.chain_head(study_id)


# ---- one gene --------------------------------------------------------------------------------


def _genes(eng: Engine) -> list[str]:
    genes = list(eng.settings.headline) + ["CLSTN1", "NTRK1", "AHCY"]
    return [g for g in dict.fromkeys(genes) if g in eng.result.contrasts]


def test_a_gene_view_is_the_engine_gene(api, which):
    study_id, eng = which
    for gene in _genes(eng):
        view = get_json(api, f"/api/studies/{study_id}/genes/{gene}")
        assert view["contrast"] == eng.result.contrasts[gene].model_dump(mode="json")
        assert view["robustness"] == eng.result.robustness[gene].model_dump(mode="json")
        assert view["confidence"] == eng.result.confidence[gene].model_dump(mode="json")
        grid = view["grid"]
        assert grid is not None, gene
        assert grid["dimensions"] == list(eng.space.dimensions)
        assert grid["planned"] == [
            list(eng.space.dimensions[d]).index(eng.primary[d]) for d in grid["dimensions"]
        ]
        rows = eng.grid[eng.grid["item"] == gene]
        assert len(grid["cells"]) == len(rows) == eng.result.robustness[gene].n_cells
        idx = [f"{d}__idx" for d in grid["dimensions"]]
        want = {
            tuple(int(x) for x in r[idx]): (float(r["log2fc"]), float(r["p"]), r["conclusion"])
            for _, r in rows.iterrows()
        }
        got = {
            tuple(cell): (grid["log2fc"][i], grid["p"][i], grid["conclusion"][i])
            for i, cell in enumerate(grid["cells"])
        }
        assert got.keys() == want.keys()
        for cell, (log2fc, p, call) in want.items():
            assert _close(got[cell][0], log2fc) and _close(got[cell][1], p), (gene, cell)
            assert got[cell][2] == call, (gene, cell)
        holds_strip = sum(c == eng.result.contrasts[gene].conclusion for c in grid["conclusion"])
        assert holds_strip / len(grid["conclusion"]) == pytest.approx(
            view["row"]["holds"], abs=1e-12
        )


# ---- your choices: decide on a copy of the store, then read every gene at those options ------


@pytest.fixture(scope="module")
def decided(world, tmp_path_factory):
    """The session's current study with two cards decided away from the recommendation."""
    from qpilot.core.store import StudyStore

    root = tmp_path_factory.mktemp("numbers-decided") / "studies"
    shutil.copytree(world.store.root, root)
    store = StudyStore(root)
    choices = {"card_refset": "top2", "card_amp_call": "cq_le_35"}
    with api_client(store) as client:
        client.headers["origin"] = BASE
        for card_id, option in choices.items():
            r = client.post(
                f"/api/studies/{world.study}/cards/{card_id}/decide",
                json={
                    "option": option,
                    "reason": "a scientist's choice, to check the numbers",
                    "expected_head": store.chain_head(world.study),
                },
            )
            assert r.status_code == 200, r.text
        yield client, store, choices


def test_your_choices_are_the_engine_at_those_options(decided, world):
    client, store, choices = decided
    eng = engine(world, world.study)
    cards = {c.id: c for c in eng.cards}
    cell = {}
    for card_id, option in choices.items():
        card = cards[card_id]
        cell[CARD_DIMENSION[card.kind]] = eng.option_values(card)[option]
    at = eng.at(**cell)
    body = get_json(client, f"/api/studies/{world.study}/results")
    assert body["choices"] == {c.id: c.decision for c in store.cards(world.study) if c.decision}
    for row in body["genes"]:
        mine = row["at_your_choices"]
        want = at[row["gene"]]
        assert mine is not None, row["gene"]
        assert mine["conclusion"] == want.conclusion, row["gene"]
        assert _close(mine["fc"], want.fc) and _close(mine["log2fc"], want.log2fc), row["gene"]
        assert _close(mine["p"], want.p), row["gene"]
        assert mine["differs"] == (want.conclusion != eng.result.contrasts[row["gene"]].conclusion)
    flips = get_json(client, f"/api/studies/{world.study}/flips")
    for frow in flips["rows"]:
        chosen = [o["value"] for o in frow["options"] if o["chosen"]]
        dim = frow["dimension"]
        # the option in use now: the person's where they chose, the planned one elsewhere
        want = cell.get(dim, eng.primary[dim])
        assert [eng.grid_value(dim, v) for v in chosen] == [want], dim


# ---- the audit's verdicts next to the results ------------------------------------------------


def test_verdicts_and_the_audit_badge_are_the_audit(api, world):
    if not world.audited:
        pytest.skip("the Decision Simulator is not installed")
    folder = world.store.root / "simulator_audits" / world.study
    genes = pd.read_csv(folder / "genes.csv")
    body = get_json(api, f"/api/studies/{world.study}/results")
    assert body["audit"]["status"] == "ready"
    assert body["audit"]["verdict_counts"] == dict(Counter(genes["verdict"]))
    assert {r["gene"]: r["verdict"] for r in body["genes"]} == dict(
        zip(genes["gene"], genes["verdict"], strict=True)
    )
    grid = pd.read_parquet(folder / "grid.parquet", columns=["gene"])
    assert set(grid.groupby("gene").size()) == {90_396}, "README: 90,396 analyses per gene"


# ---- the documented demo numbers, through the API --------------------------------------------


def _gene(api, study_id: str, gene: str) -> dict:
    body = get_json(api, f"/api/studies/{study_id}/results")
    return next(r for r in body["genes"] if r["gene"] == gene)


def test_the_documented_demo_numbers_hold_through_the_api(api, world):
    """README, docs/studio-measured.md §6.2 and studio_cmds EXPECTED, read from the API."""
    legacy = _gene(api, world.legacy, "ODC1")
    assert (round(legacy["fc"], 3), legacy["conclusion"], legacy["n_cells"]) == (
        EXPECTED["odc1_fc"],
        "up",
        186,
    )
    nm23a = _gene(api, world.legacy, "NM23A")
    assert (round(nm23a["fc"], 2), nm23a["conclusion"]) == (2.19, "up")
    assert round(nm23a["holds"] * 186) == 120, "integration #0026: NM23A holds 120/186"
    after = _gene(api, world.study, "ODC1")
    assert (round(after["fc"], 3), after["conclusion"], after["n_cells"]) == (
        EXPECTED["odc1_fc_after"],
        "up",
        EXPECTED["grid_cells"],
    )
    if world.before_roundtrip:
        before = get_json(api, f"/api/studies/{world.before_roundtrip}/results")
        now = get_json(api, f"/api/studies/{world.study}/results")
        odc1 = next(r for r in before["genes"] if r["gene"] == "ODC1")
        assert round(odc1["fc"], 3) == EXPECTED["odc1_fc"]
        changed = [
            a["gene"]
            for a, b in zip(before["genes"], now["genes"], strict=True)
            if a["conclusion"] != b["conclusion"]
        ]
        assert len(changed) == EXPECTED["conclusions_changed"], changed
        assert len(now["genes"]) == EXPECTED["genes"]


def test_the_documented_cq_cut_offs_through_the_flip_matrix(api, world):
    """docs/studio-measured.md §4.1: Cq > 35 changes 10 conclusions (> 38: 3, > 40: 1)."""
    study = world.before_roundtrip or world.study
    view = get_json(api, f"/api/studies/{study}/flips")
    (row,) = (r for r in view["rows"] if r["dimension"] == "amp_call")
    changed = {o["value"]: sum(o["flips"]) for o in row["options"]}
    assert changed == {"linregpcr": 0, "cq_le_40": 1, "cq_le_38": 3, "cq_le_35": 10}
    (option,) = (o for o in row["options"] if o["value"] == "cq_le_35")
    flipped = sorted(g for g, f in zip(view["genes"], option["flips"], strict=True) if f)
    assert flipped == [
        "CLSTN1", "EPN2", "MRPL3", "NTRK1", "PAICS", "PLAT", "PRKACB_bis", "PTPRF", "PTPRH",
        "SLC25A5",
    ]  # fmt: skip
