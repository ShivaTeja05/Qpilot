"""Checks that a results-route answer is the engine's: shared by the demo and fixture tests.

Each function takes the route's JSON and the :class:`~tests.web.numbers_engine.Engine` of the
same study and asserts; ``grid.csv`` keeps 10 significant digits, so numbers the views read from
the grid are compared to :data:`GRID_REL`. A number the engine could not compute (NaN) must be
served as ``null``, never as a stand-in value.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from tests.web.numbers_engine import CARD_DIMENSION, Engine, flips_alone, holds

GRID_REL = 1e-9


def close(got: Any, want: float, rel: float = GRID_REL) -> bool:
    """``got`` is ``want`` to ``rel``; a NaN ``want`` must be served as ``None``."""
    if want is None or (isinstance(want, float) and math.isnan(want)):
        return got is None
    return got is not None and math.isclose(got, want, rel_tol=rel, abs_tol=1e-300)


def contrast_dict(c: Any, with_n: bool = True) -> dict:
    """A ContrastResult as the routes serve it (JSON: tuples are lists, NaN is null)."""

    def num(x: float) -> float | None:
        return None if math.isnan(x) else x

    out = {
        "conclusion": c.conclusion,
        "fc": num(c.fc),
        "log2fc": num(c.log2fc),
        "ci": [num(float(c.ci[0])), num(float(c.ci[1]))],
        "p": num(c.p),
    }
    if with_n:
        out.update(n_hi=c.n_hi, n_lo=c.n_lo)
    return out


def check_gene_rows(results: dict, eng: Engine) -> None:
    """Every GeneRow: the contrast, robustness, confidence and flips_by of the engine."""
    rows = {r["gene"]: r for r in results["genes"]}
    assert list(rows) == list(eng.result.contrasts)
    alone = {dim: flips_alone(eng, dim) for dim in eng.space.dimensions}
    for gene, contrast in eng.result.contrasts.items():
        row = rows[gene]
        keys = ("conclusion", "fc", "log2fc", "ci", "p", "n_hi", "n_lo")
        assert {k: row[k] for k in keys} == contrast_dict(contrast), gene
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
        assert row["flips_by"] == sorted(d for d, by in alone.items() if by[gene]), gene
    calls = Counter(c.conclusion for c in eng.result.contrasts.values())
    assert results["counts"] == {c: calls.get(c, 0) for c in ("up", "down", "none")}
    assert results["levels"] == dict(Counter(g.level for g in eng.result.confidence.values()))
    assert sum(results["counts"].values()) == results["summary"]["n_genes"]


def check_flips(view: dict, eng: Engine) -> None:
    """The flip matrix: every option of every decision is the engine at that option."""
    genes = view["genes"]
    planned = eng.at()
    assert genes == list(eng.result.contrasts)
    assert view["planned"] == [planned[g].conclusion for g in genes]
    assert sorted(row["dimension"] for row in view["rows"]) == sorted(eng.space.dimensions)
    for row in view["rows"]:
        dim = row["dimension"]
        assert [o["value"] for o in row["options"]] == [
            "|".join(v) if isinstance(v, tuple) else str(v) for v in eng.space.dimensions[dim]
        ], dim
        deltas = dict.fromkeys(genes, 0.0)
        for option in row["options"]:
            value = eng.grid_value(dim, option["value"])
            assert option["planned"] == (value == eng.primary[dim]), (dim, option["value"])
            at = eng.at(**{dim: value})
            assert option["conclusion"] == [at[g].conclusion for g in genes], (dim, value)
            for i, g in enumerate(genes):
                assert close(option["log2fc"][i], at[g].log2fc), (dim, value, g)
                deltas[g] = max(deltas[g], abs(at[g].log2fc - planned[g].log2fc))
            assert option["flips"] == [at[g].conclusion != planned[g].conclusion for g in genes]
        alone = flips_alone(eng, dim)
        assert row["flips"] == [alone[g] for g in genes], dim
        assert row["n_flipped"] == sum(alone.values()), dim
        for i, g in enumerate(genes):
            assert math.isclose(row["max_delta_log2fc"][i], deltas[g], abs_tol=1e-9), (dim, g)


def check_cards(view: dict, eng: Engine) -> None:
    """Every Decision Card option's effect per gene is the engine at that option."""
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
                assert got == contrast_dict(at[g], with_n=False), (card.id, option["id"], g)
                assert effect["changes_call"] == (at[g].conclusion != recommended[g].conclusion)
        flipped = sum(flips_alone(eng, dim).values())
        assert card.impact["n_genes_flipped"] == flipped, card.id
        if card.impact["flips"]:
            cited = {f["id"]: f["value"] for f in item["impact"]["facts"]}
            assert cited.get("f_n_genes") == len(eng.result.contrasts), card.id
            assert flipped in cited.values(), (card.id, cited)


def check_gene(view: dict, eng: Engine, gene: str) -> None:
    """One gene's view: its contrast, robustness, confidence and its every grid analysis."""
    assert view["contrast"] == eng.result.contrasts[gene].model_dump(mode="json")
    assert view["robustness"] == eng.result.robustness[gene].model_dump(mode="json")
    assert view["confidence"] == eng.result.confidence[gene].model_dump(mode="json")
    grid = view["grid"]
    assert grid is not None, f"{gene}: no grid"
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
        assert close(got[cell][0], log2fc), (gene, cell, "log2fc", got[cell][0], log2fc)
        assert close(got[cell][1], p), (gene, cell, "p", got[cell][1], p)
        assert got[cell][2] == call, (gene, cell)
    same = sum(c == eng.result.contrasts[gene].conclusion for c in grid["conclusion"])
    assert math.isclose(same / len(grid["conclusion"]), view["row"]["holds"], abs_tol=1e-12)
