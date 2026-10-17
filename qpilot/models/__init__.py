"""Pinned model files that ship inside the package (data only: no code is loaded from here).

``curve_judge/`` holds the Curve Judge: ``model.json`` (XGBoost's JSON tree format),
``model.sha256`` (its pin), ``METHOD_CARD.md``, ``metrics.json`` (held-out results and the
evaluator check) and ``transfer.json`` (the pre-registered transfer test on the demo). The
files are read by :mod:`qpilot.qpcr.curve_judge`, which verifies the SHA-256 before parsing
and evaluates the trees with numpy. Nothing here is ever unpickled or executed. The training
code lives outside the package, in ``training/curve_judge/``.
"""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable


def model_dir(name: str) -> Traversable:
    """The packaged directory of one model, e.g. ``model_dir("curve_judge")``."""
    if name not in {"curve_judge"}:
        raise KeyError(f"unknown model {name!r}")
    return files(__name__).joinpath(name)
