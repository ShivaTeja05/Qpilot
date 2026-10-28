"""The reference-gene panel: geNorm M and NormFinder's stability side by side (engine numbers).

The study's matrix is rebuilt read-only from its input file and confirmed design, exactly as the
Prism bridge does (nothing in the workspace is written; the curve cache is only read), and its
geNorm result must equal the stored one before anything is shown. NormFinder
(:func:`qpilot.qpcr.normfinder.normfinder`) then runs on the same candidates with the study's
groups: every group of a confirmed design, or the expression-defined split's high group and the
rest. The words compare the two best pairs; they never say which reference genes to use.
"""

from __future__ import annotations

import math
import threading
from collections import Counter, OrderedDict
from typing import TYPE_CHECKING

from qpilot.qpcr.normfinder import SOURCE, NormFinderError, agreement, normfinder
from qpilot.web.contract_norm import ReferenceGeneRow, ReferencePair, ReferenceStability

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore

GENORM_SOURCE = "Vandesompele et al., Genome Biol 2002; 3:research0034"
CHOICE_NOTE = (
    "Which reference genes the analysis divides by stays your choice, on the reference-gene "
    "card; this panel only compares the two rankings."
)
MAX_CACHED = 8
_cache: OrderedDict[str, ReferenceStability] = OrderedDict()
_lock = threading.Lock()


class ReferencesUnavailable(RuntimeError):
    """The study's matrix cannot be rebuilt (the message says why, in plain words)."""


def _model(store: StudyStore, study_id: str):
    """The study's model, rebuilt read-only; refuses when it does not reproduce geNorm."""
    from qpilot.core.store import sha256_file
    from qpilot.io.datasets import default_cache_dir
    from qpilot.qpcr.curves import analyse_study, cache_path
    from qpilot.qpcr.study import StudySettings, build_model

    result = store.get(study_id)
    path = store.source(study_id)
    if path is None or sha256_file(path) != result.input_sha256:
        raise ReferencesUnavailable("the study's input file is not known or has changed")
    design = store.design(study_id)
    settings = StudySettings.from_design(design) if design is not None else StudySettings()
    cached = cache_path(
        result.input_sha256,
        settings.experiment_id,
        settings.candidates,
        settings.curves,
        default_cache_dir(),
    ).exists()
    curves = analyse_study(
        path, settings.experiment_id, settings.candidates, settings.curves, use_cache=cached
    )
    model = build_model(curves, settings)
    stored = result.genorm.M_initial
    if set(stored) != set(model.stability.M_initial) or any(
        not math.isclose(stored[g], model.stability.M_initial[g], rel_tol=1e-12) for g in stored
    ):
        raise ReferencesUnavailable(
            "a re-analysis with the study's own settings does not reproduce its geNorm values"
        )
    return result, settings, model


def _groups(settings, model) -> dict[str, str | None]:
    """Unit -> group: every group of a confirmed design, else the primary split's two sides."""
    from qpilot.qpcr.designs import unit_groups

    units = list(model.matrix.index)
    if model.labels is not None and settings.design is not None:
        by_unit = unit_groups(settings.design)
        return {u: by_unit.get(u) for u in units}
    high, rest = model.high, model.rest
    label = f"{settings.marker_label}-high"
    return {u: label if u in high else "rest" if u in rest else None for u in units}


def reference_stability(store: StudyStore, study_id: str) -> ReferenceStability:
    """The two rankings side by side for one stored study (cached per study)."""
    with _lock:
        if study_id in _cache:
            _cache.move_to_end(study_id)
            return _cache[study_id]
    try:
        result, settings, model = _model(store, study_id)
    except (OSError, ValueError) as err:
        raise ReferencesUnavailable(str(err)) from err
    view = _view(study_id, result, settings, model)
    with _lock:
        _cache[study_id] = view
        while len(_cache) > MAX_CACHED:
            _cache.popitem(last=False)
    return view


def _view(study_id: str, result, settings, model) -> ReferenceStability:
    genorm = result.genorm
    candidates = list(settings.candidates)
    used = list(result.design.refs_primary)
    g_rank = {gene: i + 1 for i, gene in enumerate(genorm.order)} if genorm.M_initial else {}
    g_pair = ReferencePair(genes=list(genorm.order[:2])) if len(genorm.order) >= 2 else None
    found, why = None, None
    try:
        found = normfinder(model.matrix, candidates, _groups(settings, model))
    except NormFinderError as err:
        why = str(err)
    rows = []
    for gene in candidates:
        row = ReferenceGeneRow(
            gene=gene,
            used=gene in used,
            genorm_m=genorm.M_initial.get(gene),
            genorm_rank=g_rank.get(gene) if len(candidates) >= 3 else None,
        )
        if found is not None:
            row.normfinder = found.stability[gene]
            row.normfinder_rank = found.order.index(gene) + 1
            row.within_sd = math.sqrt(found.intragroup[gene])
            row.shift = dict(found.intergroup.get(gene, {}))
        rows.append(row)
    if found is None or g_pair is None or len(candidates) < 3:
        verdict = "not_available"
        words = (
            f"NormFinder could not rank these candidates: {why}."
            if why
            else "geNorm needs three candidates to name a best pair."
        )
    else:
        agreed = agreement(genorm.order, found)
        verdict = "agree" if agreed.same_pair else "share_one" if agreed.shared else "disagree"
        words = agreed.words
    reasons = Counter((found.left_out if found is not None else {}).values())
    return ReferenceStability(
        study_id=study_id,
        candidates=candidates,
        used=used,
        rows=rows,
        genorm_pair=g_pair if len(candidates) >= 3 else None,
        normfinder_pair=(
            ReferencePair(genes=list(found.best_pair), value=found.pair_stability)
            if found is not None
            else None
        ),
        verdict=verdict,
        words=words,
        choice_note=CHOICE_NOTE,
        grouped=bool(found is not None and found.grouped),
        groups=dict(found.groups) if found is not None and found.grouped else {},
        n_units=found.n_units if found is not None else 0,
        n_left_out=sum(reasons.values()),
        left_out_reasons=dict(sorted(reasons.items())),
        warnings=list(found.warnings) if found is not None else [],
        unavailable=why,
        sources=[GENORM_SOURCE, SOURCE],
    )


__all__ = ["ReferencesUnavailable", "reference_stability"]
