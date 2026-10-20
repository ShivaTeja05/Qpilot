"""The audit's views serve the audit's numbers: recomputed here from the files it wrote.

The robustness audit writes every analysis it ran (``grid.parquet``: one row per analysis and
gene, each decision as its option's index), the options' order, tiers and the plan
(``lock.json``), and its per-gene table (``genes.csv``). These tests decode the grid with the
lock (no qsim code) and check that the routes, which read the Decision Simulator's live screen,
serve the same numbers; counts of samples, plates and genes come from a fresh ``run_study``.

A *reasonable* analysis (the audit's word) uses no ``common_practice`` option and keeps the
``question`` decisions (the groups, the multiplicity correction) as planned: 144 per gene on
the demo.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.conftest import DEMO_RDML
from tests.web.numbers_engine import engine
from tests.web.numbers_world import BASE, World, api_client, demo_world, get_json

pytestmark = pytest.mark.demo_data
pytest.importorskip("qpilot.web.routers.audit", reason="the audit routes are not merged yet")

CALL = {1: "up", -1: "down", 0: "none"}
GENES = ["ODC1", "NM23A", "CLSTN1", "DPYSL3", "AHCY"]


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    w = demo_world(tmp_path_factory.getbasetemp() / "numbers-demo", DEMO_RDML)
    if not w.audited:
        pytest.skip("the Decision Simulator is not installed")
    return w


@pytest.fixture(scope="module")
def api(world):
    with api_client(world.store) as client:
        client.headers["origin"] = BASE
        yield client


class Audit:
    """The audit folder, decoded with its own lock (no simulator code)."""

    def __init__(self, folder: Path) -> None:
        lock = json.loads((folder / "lock.json").read_text())
        self.tiers: dict[str, dict[str, str]] = lock["tiers"]
        self.roles: dict[str, str] = lock["roles"]
        self.options = {d: list(t) for d, t in self.tiers.items()}
        self.plan = {d: self.options[d].index(lock["baseline"][d]) for d in self.tiers}
        self.grid = pd.read_parquet(folder / "grid.parquet")
        self.genes = pd.read_csv(folder / "genes.csv").set_index("gene")
        self.manifest = json.loads((folder / "audit_manifest.json").read_text())

    def cell(self, **choices: str) -> pd.DataFrame:
        """Every gene's row in one analysis: the plan, with ``choices`` (option ids) changed."""
        want = {**self.plan, **{d: self.options[d].index(o) for d, o in choices.items()}}
        mask = np.ones(len(self.grid), bool)
        for d, idx in want.items():
            mask &= (self.grid[d] == idx).to_numpy()
        rows = self.grid[mask].set_index("gene")
        assert len(rows) == len(self.genes), choices
        return rows

    @cached_property
    def planned(self) -> pd.DataFrame:
        """The planned analysis, one row per gene."""
        return self.cell()

    @cached_property
    def reasonable(self) -> pd.DataFrame:
        """The reasonable analyses (no shortcut options; question decisions as planned)."""
        mask = np.ones(len(self.grid), bool)
        for d, tiers in self.tiers.items():
            if self.roles[d] == "question":
                mask &= (self.grid[d] == self.plan[d]).to_numpy()
                continue
            shortcut = [i for i, o in enumerate(self.options[d]) if tiers[o] == "common_practice"]
            mask &= ~self.grid[d].isin(shortcut).to_numpy()
        return self.grid[mask]

    def holds(self, gene: str) -> float:
        rows = self.reasonable[self.reasonable["gene"] == gene]
        return float((rows["call"] == self.planned.loc[gene, "call"]).mean())


@pytest.fixture(scope="module")
def audit(world) -> Audit:
    return Audit(world.store.root / "simulator_audits" / world.study)


def fold_words(log2: float) -> str:
    """How the audit words a fold: ``3.32× higher`` / ``2.03× lower``."""
    return f"{2 ** abs(log2):.2f}× {'higher' if log2 >= 0 else 'lower'}"


def url(world: World, tail: str) -> str:
    return f"/api/studies/{world.study}/audit/{tail}"


def test_the_overview_counts_are_the_audit_and_the_engine(api, world, audit):
    view = get_json(api, url(world, "overview"))
    eng = engine(world, world.study).result
    per_gene = Counter(audit.grid["gene"])
    assert set(per_gene.values()) == {view["study"]["analyses"]} == {90_396}
    assert view["study"]["reasonable"] == len(audit.reasonable) // len(audit.genes) == 144
    assert (view["study"]["samples"], view["study"]["plates"], view["study"]["genes"]) == (
        eng.n_samples,
        eng.n_plates,
        len(eng.contrasts),
    )
    assert {v["key"]: v["count"] for v in view["verdicts"]} == dict(Counter(audit.genes["verdict"]))
    assert {v["key"]: v["count"] for v in view["verdicts"]} == audit.manifest["verdict_counts"]
    for gene in view["genes"]:
        name = gene["gene"]
        log2 = audit.planned.loc[name, "log2fc"]
        assert gene["verdict"] == audit.genes.loc[name, "verdict"], name
        assert gene["call_key"] == CALL[int(audit.planned.loc[name, "call"])], name
        assert gene["fold"] == fold_words(log2), name


def test_the_audit_baseline_is_qpilot_s_planned_analysis(audit, world):
    """The audit reproduces qPilot (manifest), and so do its files: every gene, every number."""
    eng = engine(world, world.study).result
    for gene, contrast in eng.contrasts.items():
        row = audit.planned.loc[gene]
        assert math.isclose(row["log2fc"], contrast.log2fc, abs_tol=1e-9), gene
        assert math.isclose(row["p"], contrast.p, rel_tol=1e-9), gene
        assert CALL[int(row["call"])] == contrast.conclusion, gene


def test_the_map_is_the_planned_fold_and_the_reasonable_share(api, world, audit):
    view = get_json(api, url(world, "study"))
    assert len(view["map"]) == len(audit.genes)
    for point in view["map"]:
        gene = point["gene"]
        assert math.isclose(point["log2"], audit.planned.loc[gene, "log2fc"], abs_tol=1e-12)
        assert point["fold"] == fold_words(point["log2"]), gene
        assert point["holds"] == round(100 * audit.holds(gene)), gene
        assert math.isclose(audit.holds(gene), audit.genes.loc[gene, "defensible_holds"])
        assert point["verdict"] == audit.genes.loc[gene, "verdict"], gene


def test_choices_alone_count_the_genes_each_choice_flips(api, world, audit):
    view = get_json(api, url(world, "study"))
    flipped = pd.read_csv(audit_folder(world) / "decisions.csv").set_index("decision")
    for choice in view["choices"]:
        assert choice["alone"] == flipped.loc[choice["id"], "genes_flipped_alone"], choice
        alone = set()
        for option in audit.options[choice["id"]]:
            cell = audit.cell(**{choice["id"]: option})
            alone |= set(cell.index[cell["call"] != audit.planned["call"]])
        assert choice["alone"] == len(alone), choice["id"]


def audit_folder(world: World) -> Path:
    return world.store.root / "simulator_audits" / world.study


@pytest.mark.parametrize("gene", GENES)
def test_the_analyses_strip_is_every_reasonable_analysis(api, world, audit, gene):
    view = get_json(api, url(world, f"analyses/{gene}"))
    rows = audit.reasonable[audit.reasonable["gene"] == gene]
    base = audit.planned.loc[gene, "call"]
    assert view["n"] == len(view["rows"]) == len(rows)
    assert view["n_same"] == int((rows["call"] == base).sum())
    assert view["n_other"] == view["n"] - view["n_same"]
    assert view["base_call_key"] == CALL[int(base)]
    assert sorted(round(r["log2"], 12) for r in view["rows"]) == sorted(
        round(x, 12) for x in rows["log2fc"]
    )
    (planned,) = (r for r in view["rows"] if r["planned"])
    assert math.isclose(planned["log2"], audit.planned.loc[gene, "log2fc"], abs_tol=1e-12)
    assert all(r["same"] == (r["call_key"] == view["base_call_key"]) for r in view["rows"])


@pytest.mark.parametrize("gene", GENES)
def test_one_choice_at_a_time_is_that_analysis(api, world, audit, gene):
    view = get_json(api, url(world, f"effects/{gene}"))
    base = audit.planned.loc[gene]
    assert math.isclose(view["planned_log2"], base["log2fc"], abs_tol=1e-12)
    for decision in view["decisions"]:
        d = decision["id"]
        assert len(decision["options"]) == len(audit.options[d]), d
        changed = 0
        for option_id, option in zip(audit.options[d], decision["options"], strict=True):
            row = audit.cell(**{d: option_id}).loc[gene]
            assert option["tier"] == audit.tiers[d][option_id], (d, option_id)
            assert option["planned"] == (audit.options[d].index(option_id) == audit.plan[d])
            assert math.isclose(option["log2"], row["log2fc"], abs_tol=1e-12), (d, option_id)
            assert option["call_key"] == CALL[int(row["call"])], (d, option_id)
            assert option["changes_call"] == (row["call"] != base["call"]), (d, option_id)
            changed += option["changes_call"]
        assert decision["n_change"] == changed, d


@pytest.mark.parametrize(
    "changes",
    [{"refs": "HMBS", "late_cq": "cq35"}, {"efficiency": "assume_100", "test": "student"}],
)
def test_the_what_if_lab_is_the_audit_at_those_choices(api, world, audit, changes):
    r = api.post(url(world, "whatif"), json={"changes": changes})
    assert r.status_code == 200, r.text
    view = r.json()
    cell = audit.cell(**changes)
    base = audit.planned
    assert view["n_genes"] == len(view["rows"]) == len(audit.genes)
    for row in view["rows"]:
        gene = row["gene"]
        assert math.isclose(row["base_log2"], base.loc[gene, "log2fc"], abs_tol=1e-12)
        assert math.isclose(row["new_log2"], cell.loc[gene, "log2fc"], abs_tol=1e-12), gene
        assert row["new_call_key"] == CALL[int(cell.loc[gene, "call"])], gene
        assert row["changed"] == (cell.loc[gene, "call"] != base.loc[gene, "call"]), gene
        assert (row["base"], row["new"]) == (
            fold_words(row["base_log2"]),
            fold_words(row["new_log2"]),
        )
    changed = sorted(cell.index[cell["call"] != base["call"]])
    assert view["n_changed"] == len(changed)
    assert sorted(view["changed_genes"]) == changed


@pytest.mark.parametrize("gene", GENES)
def test_your_samples_average_to_the_planned_fold(api, world, audit, gene):
    r = api.post(url(world, "samples"), json={"gene": gene})
    assert r.status_code == 200, r.text
    view = r.json()
    contrast = engine(world, world.study).result.contrasts[gene]
    groups = view["groups"]
    assert (groups["high"]["n"], groups["rest"]["n"]) == (contrast.n_hi, contrast.n_lo)
    xs = {g: [p["x"] for p in view["points"] if p["group"] == g and p["x"] is not None]
          for g in ("high", "rest")}  # fmt: skip
    assert (len(xs["high"]), len(xs["rest"])) == (contrast.n_hi, contrast.n_lo)
    assert math.isclose(np.mean(xs["rest"]), 0.0, abs_tol=1e-9)
    assert math.isclose(groups["high"]["mean"], np.mean(xs["high"]), abs_tol=1e-9)
    assert math.isclose(groups["high"]["mean"], contrast.log2fc, abs_tol=1e-9)
    assert math.isclose(view["fold_log2"], audit.planned.loc[gene, "log2fc"], abs_tol=1e-12)
    for p in view["points"]:
        if p["x"] is not None:
            assert p["value"] == fold_words(p["x"]), p


@pytest.mark.parametrize("gene", GENES)
def test_the_gene_card_tiles_are_the_audit(api, world, audit, gene):
    view = get_json(api, url(world, f"gene/{gene}"))
    tiles = {t["label"]: t for t in view["tiles"]}
    base = audit.planned.loc[gene]
    assert tiles["Fold change, planned analysis"]["value"] == fold_words(base["log2fc"])
    assert float(tiles["p-value, planned analysis"]["value"]) == pytest.approx(base["p"], rel=0.05)
    rows = audit.reasonable[audit.reasonable["gene"] == gene]
    same = int((rows["call"] == base["call"]).sum())
    ((k, n),) = re.findall(r"^(\d+) of (\d+)$", tiles["Same answer in"]["value"])
    assert (int(k), int(n)) in {(same, len(rows)), (round(100 * audit.holds(gene)), 100)}
    assert view["holds"]["n"] == round(100 * audit.holds(gene))
    assert view["verdict"] == audit.genes.loc[gene, "verdict"]
    assert view["call_key"] == CALL[int(base["call"])]


@pytest.mark.parametrize("gene", GENES)
def test_the_lab_numbers_are_the_engine_s(api, world, audit, gene):
    view = get_json(api, url(world, f"lab/{gene}"))
    numbers = view["numbers"]
    eng = engine(world, world.study)
    contrast = eng.result.contrasts[gene]
    # the groups' sizes; the contrast counts the units with a value for this gene
    samples = api.post(url(world, "samples"), json={"gene": gene}).json()["groups"]
    assert (numbers["n_high"], numbers["n_rest"]) == (
        contrast.n_hi + samples["high"]["missing"],
        contrast.n_lo + samples["rest"]["missing"],
    )
    assert math.isclose(numbers["p"], audit.planned.loc[gene, "p"], rel_tol=1e-9)
    assert math.isclose(numbers["p"], contrast.p, rel_tol=1e-9)
    assert numbers["eff_assay"] == eng.result.efficiency[gene]
    stability = eng.result.genorm.M_initial
    for ref in view["references"]:
        assert math.isclose(ref["m_value"], stability[ref["gene"]], abs_tol=5e-4), ref


@pytest.mark.xfail(
    strict=True,
    reason="to api-audit: summary.json keeps geNorm M to 3 decimals and the words round it "
    "again (HPRT1 1.6349 -> 1.635 -> '1.64'; Results shows 1.63)",
)
def test_the_audit_words_geNorm_M_as_results_does(api, world):
    stability = engine(world, world.study).result.genorm.M_initial
    view = get_json(api, url(world, "lab/ODC1"))
    study = get_json(api, url(world, "study"))
    for ref in [*view["references"], *study["references"]]:
        assert ref["m"] == f"{stability[ref['gene']]:.2f}", ref
