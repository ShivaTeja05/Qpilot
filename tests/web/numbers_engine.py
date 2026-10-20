"""The engine's own numbers for a stored study, computed without the store or the web views.

For each study the engine is run again from the RDML file (``run_study``) and its decision space
is rebuilt (``build_model``). Every option of every decision is then evaluated with
``QpcrSpace.evaluate`` (one contrast per gene, recomputed from the per-sample matrix), so what
the API reads from ``grid.csv`` and the cards is compared with numbers that never went through
either.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from qpilot.schemas import ContrastResult, DecisionCard, StudyResult
from tests.web.numbers_world import World, engine_run

#: Decision Card kind -> the robustness dimension it decides (``qpilot/qpcr/study.py``).
CARD_DIMENSION = {
    "reference_set": "refs",
    "group_cutoff": "cut",
    "undetermined": "undetermined",
    "amp_call": "amp_call",
}


@dataclass(frozen=True, eq=False)
class Engine:
    """One study as the engine computes it from the file."""

    result: StudyResult
    cards: list[DecisionCard]
    grid: pd.DataFrame
    space: Any  # qpilot.qpcr.space.QpcrSpace
    stability: Any
    settings: Any

    @property
    def primary(self) -> dict[str, Any]:
        """The planned option of every dimension."""
        return dict(self.space.primary)

    def at(self, **choices: Any) -> dict[str, ContrastResult]:
        """Every gene's contrast with ``choices`` and the other decisions as planned."""
        return _evaluate(self, tuple(sorted({**self.primary, **choices}.items())))

    def option_values(self, card: DecisionCard) -> dict[str, Any]:
        """A card's option ids -> the dimension's values (as the engine builds the cards)."""
        from qpilot.qpcr.study import _pct, _ref_options

        dim = CARD_DIMENSION[card.kind]
        if dim == "refs":
            pairs = _ref_options(self.space, self.stability, self.settings.candidates)
            values = {spec.id: tuple(spec.value) for spec, _ in pairs}
        elif dim == "cut":
            values = {f"cut_{_pct(c)}": c for c in self.settings.cuts}
        else:
            values = {o.id: o.id for o in card.options}
        return {o.id: values[o.id] for o in card.options}

    def grid_value(self, dimension: str, text: str) -> Any:
        """A grid option written as text (``grid.csv``) -> the dimension's own value."""
        for value in self.space.dimensions[dimension]:
            if _as_text(value) == text:
                return value
        raise KeyError(f"{dimension}: no option {text!r}")


def _as_text(value: Any) -> str:
    if isinstance(value, tuple):
        return "|".join(map(str, value))
    return str(value)


@functools.cache
def _evaluate(engine: Engine, cell: tuple[tuple[str, Any], ...]) -> dict[str, ContrastResult]:
    return engine.space.evaluate(dict(cell))


@functools.cache
def _model(rdml: Path, design_json: str | None) -> tuple[Any, Any]:
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.study import StudySettings, build_model
    from qpilot.schemas_studio import StudyDesign

    if design_json is None:
        settings = StudySettings()
    else:
        settings = StudySettings.from_design(StudyDesign.model_validate_json(design_json))
    curves = analyse_study(rdml, settings.experiment_id, settings.candidates, settings.curves)
    return build_model(curves, settings), settings


_engines: dict[tuple[Path, str | None], Engine] = {}


def engine(world: World, study_id: str) -> Engine:
    """The engine's study (run once per process and design)."""
    design = world.store.design(study_id)
    design_json = None if design is None else design.model_dump_json()
    key = (world.rdml, design_json)
    if key not in _engines:
        result, cards, grid = engine_run(world.rdml, design_json)
        model, settings = _model(world.rdml, design_json)
        _engines[key] = Engine(result, cards, grid, model.space, model.stability, settings)
    return _engines[key]


def flips_alone(eng: Engine, dimension: str) -> dict[str, bool]:
    """Per gene: does some option of ``dimension`` alone give another call than planned?"""
    planned = eng.at()
    out = dict.fromkeys(planned, False)
    for value in eng.space.dimensions[dimension]:
        for gene, contrast in eng.at(**{dimension: value}).items():
            if contrast.conclusion != planned[gene].conclusion:
                out[gene] = True
    return out


def holds(eng: Engine, gene: str) -> float:
    """Share of the engine grid's analyses that give the planned call (recomputed)."""
    rows = eng.grid[eng.grid["item"] == gene]
    return float((rows["conclusion"] == eng.result.contrasts[gene].conclusion).mean())
