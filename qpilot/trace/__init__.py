"""Trace: follow a result down to the samples, wells and plates that drive it.

A scientist reads "ODC1 3.3× up" and asks what the number stands on: which samples, which
wells, which plate. Trace answers from the engine's own numbers, read-only and without a model:

* :func:`trace_gene` (result-first): every sample's exact influence on one gene's call, the
  fewest samples that change it, each control gene's share, and the well to look at first;
* :func:`trace_study`: genes by how little it takes to change their call, and the samples
  behind the most calls;
* :func:`without_samples`: one gene recomputed with samples set aside (the "what if").

Build a :class:`TraceContext` once per study and analysis (:func:`model_for_study`, then
:func:`build_context`); everything after that is closed-form arithmetic on it. See
``qPilot-TRACE-PLAN.md`` for the design and the measured demo numbers.
"""

from __future__ import annotations

import math
from typing import Any

from qpilot.trace.context import THRESHOLDS, TraceContext, TraceError, build_context
from qpilot.trace.gene import trace_gene
from qpilot.trace.study import trace_study, without_samples

__all__ = [
    "THRESHOLDS",
    "TraceContext",
    "TraceError",
    "build_context",
    "model_for_study",
    "trace_gene",
    "trace_study",
    "without_samples",
]


def model_for_study(store: Any, study_id: str) -> Any:
    """Rebuild a stored study's model from its input file (read-only; ~1 s on the demo).

    The model must give the stored results again, gene for gene, or nothing is traced.

    Raises:
        TraceError: The input file is missing or changed, or the rebuilt numbers differ.
    """
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.study import StudySettings, build_model

    source = store.source(study_id)
    if source is None:
        raise TraceError(
            "The study's input file is missing or has changed since it was analysed, so its "
            "wells cannot be traced. Open the file again to trace it."
        )
    design = store.design(study_id)
    settings = StudySettings.from_design(design) if design is not None else StudySettings()
    curves = analyse_study(source, settings.experiment_id, settings.candidates, settings.curves)
    model = build_model(curves, settings)
    stored = store.get(study_id).contrasts
    rebuilt = model.space.evaluate(model.space.primary)
    for gene, contrast in stored.items():
        again = rebuilt.get(gene)
        if again is None or not math.isclose(again.log2fc, contrast.log2fc, abs_tol=1e-9):
            raise TraceError(
                f"Re-running the study does not give its stored result for {gene}, so it is not "
                "traced. Analyse the file again."
            )
    return model
