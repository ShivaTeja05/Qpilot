"""A study's (or a file's) absolute quantification, from its file and confirmed design.

The one way in for the Quantities view, the exports (the Quantities table, the Methods
paragraph, the MIQE items) and the CLI: the per-well table from the curve cache, the design's
well roles and exclusions (:func:`qpilot.qpcr.designs.design_curves`), its primary amplification
rule and well calls, the standards' quantities (a person's over the file's declared ones), the
biological units and the reaction input. :func:`qpilot.qpcr.absolute.quantify` does every
number. One study's result is kept in memory by study id and input hash.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from qpilot.qpcr import absolute as ab

MAX_CACHED = 4
NO_FILE = "the study's input file is not known or has changed"
LEGACY_GROUPS = (
    "The groups of this study are defined from the data (by a marker gene's expression), so the "
    "units are listed without their group; Results shows the comparison."
)


class QuantitiesUnavailable(RuntimeError):
    """The study's quantities cannot be computed (the message says why, in plain words)."""


class Computed:
    """One study's quantification and the groups of its units."""

    def __init__(self, result: ab.Absolute, groups: Mapping[str, str] | None, notes: list[str]):
        self.result = result
        self.groups = groups
        self.notes = notes


_cache: OrderedDict[tuple[Any, ...], Computed] = OrderedDict()
_lock = threading.Lock()


def declared_quantities(path: str | Path) -> dict[tuple[str, str], tuple[float, str]]:
    """The file's declared quantities: ``(sample, target) -> (value, unit)`` (RDML)."""
    from qpilot.qpcr.inspect import file_facts

    out: dict[tuple[str, str], tuple[float, str]] = {}
    for sample, entries in file_facts(path).sample_quantities.items():
        for value, unit, target in entries:
            out.setdefault((sample, target), (float(value), str(unit or "")))
    return out


def quantify_file(
    path: str | Path,
    design: Any = None,
    *,
    settings: Any = None,
    loq_cv: float | None = None,
    rule_id: str | None = None,
) -> ab.Absolute:
    """:func:`qpilot.qpcr.absolute.quantify` on an RDML file with a design (or none).

    ``rule_id`` and ``loq_cv`` replace the design's primary amplification rule and the default
    LOQ line (a quantification study's analysis in use, :func:`qpilot.qpcr.quantify_study.
    analysis_in_use`).
    """
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.designs import design_curves, design_units
    from qpilot.qpcr.study import StudySettings

    if settings is None:  # a file without a design: every experiment, no control genes
        settings = (
            StudySettings.from_design(design)
            if design is not None
            else StudySettings(experiment_id=None, candidates=())
        )
    curves = analyse_study(path, settings.experiment_id, settings.candidates, settings.curves)
    table = design_curves(curves, design) if design is not None else curves
    quantities = None
    reaction = None
    units = None
    calls = None
    if design is not None:
        quantities = {s: d.quantity for s, d in design.samples.items() if d.quantity}
        units = design_units(design) or None
        calls = dict(design.well_calls) or None
        given = design.reaction_input
        if given is not None:
            reaction = ab.ReactionInputs(given.template_ul, given.input_ng, given.unit)
    options = ab.AbsoluteSettings(loq_cv=loq_cv) if loq_cv is not None else None
    return ab.quantify(
        table,
        quantities=quantities,
        declared=declared_quantities(path),
        units=units,
        rule_id=rule_id or settings.amp_calls[0],
        calls=calls,
        reaction=reaction,
        settings=options,
    )


def for_study(
    study_id: str,
    input_sha256: str,
    path: Path,
    design: Any,
    choice: Mapping[str, str] | None = None,
) -> Computed:
    """:func:`computed` from a study's id, input hash, file and design (the report's way in).

    ``choice`` is a quantification study's analysis in use (``amp_call`` and ``loq_cv``, from
    the person's decisions on its cards); ``None``: the analysis as planned.

    Raises:
        QuantitiesUnavailable: The file is not the study's input (its sha256 differs).
    """
    from qpilot.core.store import sha256_file
    from qpilot.qpcr.designs import unit_groups
    from qpilot.qpcr.study import StudySettings

    picked = tuple(sorted((choice or {}).items()))
    key = (study_id, input_sha256, picked)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    if sha256_file(path) != input_sha256:
        raise QuantitiesUnavailable(NO_FILE)
    legacy = StudySettings() if design is None else None  # the demo analysis
    loq = (choice or {}).get("loq_cv")
    absolute = quantify_file(
        path,
        design,
        settings=legacy,
        loq_cv=float(loq) if loq is not None else None,
        rule_id=(choice or {}).get("amp_call"),
    )
    notes: list[str] = []
    groups = None
    if design is not None and design.mode == "groups":
        groups = unit_groups(design)
    elif absolute.unknowns:
        notes.append(LEGACY_GROUPS)
    found = Computed(absolute, groups, notes)
    with _lock:
        _cache[key] = found
        while len(_cache) > MAX_CACHED:
            _cache.popitem(last=False)
    return found
