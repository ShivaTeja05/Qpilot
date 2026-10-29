"""The Curve Judge: a learned amplification call, read from the shape of each curve.

One option on the ``amp_call`` axis, **never the default**, and offered only for an input file
:func:`validated` accepts. It is a pinned gradient-boosted tree classifier (XGBoost, 17 trees)
trained on 165,214 expert-labelled TaqMan Array Card curves (Brintz et al., Gates Open
Research 9:1, 2025; data CC0 on GitHub / CC BY 4.0 on Zenodo, attributed in the method card).
It is not a language model and nothing here calls one: the engine stays deterministic.

How it runs, offline and without XGBoost:

* ``qpilot/models/curve_judge/model.json`` is XGBoost's own JSON tree dump. Before a single
  byte is parsed its SHA-256 must equal both ``model.sha256`` and :data:`MODEL_SHA256` below;
  otherwise loading is refused (a tampered or swapped model never runs). It is parsed with
  ``json.loads``: no pickle, no ``eval``, no network.
* :class:`TreeEnsemble` walks the trees with numpy exactly as XGBoost's CPU predictor does:
  inputs cast to float32, ``x < split_condition`` goes left, a missing value (NaN) follows the
  node's learned default direction, the margin starts at ``logit(base_score)`` and the
  probability is the logistic of the summed margin. ``training/curve_judge/evaluate.py``
  checks it against ``xgboost.Booster.predict`` on all 33,043 held-out curves and records the
  maximum difference in ``metrics.json``; ``tests/engine/test_curve_judge.py`` re-checks a
  stored sample of those curves.
* A curve is called amplified when ``p > 0.5`` (the paper's rule). A curve the model cannot
  score (see below) has no call: None, never "not amplified".

Inputs: 40 cycles, ``Fnorm = Fstand - (Fmin - 1)`` per curve (the paper's normalisation),
where ``Fstand`` was the reporter divided by the ROX passive reference on the training
instrument. qPCR instruments without ROX (the demo's LightCycler 480, SYBR Green) get the
substitution pre-registered in ``training/curve_judge/transfer.py``: cycles 1-40 of the curve,
divided by the curve's own minimum over those cycles (see :func:`features_from_rdml`). A curve
whose minimum is not a positive number (a baseline-subtracted or offset export) cannot be
scored. Whether the substitution is good enough is decided only by the transfer test, never by
this module.

Validation is per input file, and never without one. The transfer test ran on one file, and
``transfer.json`` records its SHA-256 and its :func:`fingerprint`: the instrument, dyes, target
types and cycle counts it declares. :func:`validated` says yes for exactly two kinds of file:

* the transfer-tested file itself (same SHA-256), and
* a file in which every run names its instrument and whose fingerprint stays within the record.

A file that names no instrument is never validated by its fingerprint: "no instrument named" is
true of exports from any machine (a CFX384 plate with SYBR at 45 cycles looks like the demo), so
only its hash can tie it to the test. The demo file names no instrument and no dye chemistry,
so its record (dye ``SYBR``, targets of interest only, 45 or 50 cycles, no instrument named)
covers no other file: today the demo file is the only one validated.

Wiring (done by the integration, not here)::

    from qpilot.qpcr import curve_judge
    if curve_judge.validated(rdml_path):
        register_learned(curve_judge.LEARNED_RULE, curve_judge.predict)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

from qpilot.schemas_studio import AmpCallRule

log = logging.getLogger(__name__)

#: SHA-256 of the shipped ``model.json``; must also match ``model.sha256``. Update both (and
#: re-run the transfer test) whenever the model is retrained.
MODEL_SHA256 = "39ea518cb716c82534e4371ce43ad74ee2adc7be809324bdb8847c79a9e586f9"
MODEL_NAME = "curve_judge"
METHOD_CARD = "methods/curve_judge.md"
N_CYCLES = 40
CYC_COLUMNS: tuple[str, ...] = tuple(f"Cyc{i}" for i in range(1, N_CYCLES + 1))
THRESHOLD = 0.5
MAX_MODEL_BYTES = 32 * 1024 * 1024
#: Added to the refusal when the only change is LF turned into CRLF (a Git checkout on Windows
#: that ignored the repository's ``.gitattributes``): the file is still refused, by its bytes.
CRLF_HINT = (
    " (its line ends were changed to CRLF, as a Git checkout on Windows without the repository's "
    ".gitattributes does: check the file out again, or reinstall qPilot)"
)
NOT_VALIDATED = "not validated for this instrument"
KEY_NAME = "run_id/well"
FINGERPRINT_KEYS: tuple[str, ...] = ("instrument", "dye", "target_type", "cycles")
#: Fingerprints kept per process, keyed by the file's SHA-256 (the demo takes ~11 s to read).
FINGERPRINT_CACHE_SIZE = 32
_FINGERPRINTS: OrderedDict[str, str] = OrderedDict()
_FINGERPRINTS_LOCK = threading.Lock()
_SHA256_HEX = frozenset("0123456789abcdef")

LEARNED_RULE = AmpCallRule(
    id="learned",
    label="Learned call (Curve Judge)",
    kind="learned",
    cq_max=None,
    recommended=False,
    note=(
        "Pinned XGBoost classifier of the curve's shape, trained on 165,214 expert-labelled "
        "TaqMan Array Card curves (Brintz et al. 2025). One option, never the default; offered "
        f"only when its transfer test passed for this instrument, otherwise {NOT_VALIDATED}."
    ),
    method_card=METHOD_CARD,
)


class CurveJudgeError(Exception):
    """The Curve Judge cannot run on this input."""


class ModelIntegrityError(CurveJudgeError):
    """The model file is missing, modified, or not the tree model this module evaluates."""


class _Readable(Protocol):
    def read_bytes(self) -> bytes: ...


# ---------------------------------------------------------------------------------------------
# The model: integrity check, parsing, numpy evaluation
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Tree:
    left: np.ndarray  # int64, -1 at leaves
    right: np.ndarray  # int64
    feature: np.ndarray  # int64
    condition: np.ndarray  # float32: split threshold, or the leaf value at a leaf
    default_left: np.ndarray  # bool


@dataclass(frozen=True)
class TreeEnsemble:
    """A binary:logistic gbtree model, evaluated with numpy as XGBoost's CPU predictor does."""

    trees: tuple[_Tree, ...]
    base_margin: np.float32
    feature_names: tuple[str, ...]
    sha256: str

    @property
    def n_features(self) -> int:
        """Number of input features (40 cycles)."""
        return len(self.feature_names)

    def margin(self, x: np.ndarray) -> np.ndarray:
        """Raw margin (log-odds) per row, float32; NaN cells are missing values."""
        data = np.asarray(x, dtype=np.float64)
        if data.ndim != 2 or data.shape[1] != self.n_features:
            raise CurveJudgeError(f"expected an (n, {self.n_features}) array, got {data.shape}")
        if np.isinf(data).any():
            raise CurveJudgeError("input contains an infinite value")
        data32 = data.astype(np.float32)  # XGBoost's DMatrix stores float32
        out = np.full(data32.shape[0], self.base_margin, dtype=np.float32)
        for tree in self.trees:
            out += _leaf_values(tree, data32)
        return out

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        """Probability of amplification per row (XGBoost's float32 logistic)."""
        margin = self.margin(x)
        return (np.float32(1.0) / (np.exp(-margin) + np.float32(1.0))).astype(np.float32)


def _leaf_values(tree: _Tree, x32: np.ndarray) -> np.ndarray:
    node = np.zeros(x32.shape[0], dtype=np.int64)
    rows = np.arange(x32.shape[0])
    for _ in range(len(tree.left)):  # a valid tree is never deeper than its node count
        active = tree.left[node] != -1
        if not active.any():
            return tree.condition[node]
        idx = rows[active]
        current = node[idx]
        value = x32[idx, tree.feature[current]]
        go_left = np.where(
            np.isnan(value), tree.default_left[current], value < tree.condition[current]
        )
        node[idx] = np.where(go_left, tree.left[current], tree.right[current])
    raise ModelIntegrityError("tree walk did not terminate (malformed tree)")


def _sha256_pin(sha256_file: _Readable) -> str:
    text = sha256_file.read_bytes().decode("ascii", errors="strict").split()
    if not text or len(text[0]) != 64 or any(c not in "0123456789abcdef" for c in text[0]):
        raise ModelIntegrityError("model.sha256 does not hold a SHA-256 hex digest")
    return text[0]


def _as_float(value: Any) -> float:
    """XGBoost >= 3 writes ``base_score`` as ``"[5E-1]"``; older versions as ``"5E-1"``."""
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        parts = [p for p in text[1:-1].split(",") if p.strip()]
        if len(parts) != 1:
            raise ModelIntegrityError("expected one base_score (one target)")
        text = parts[0]
    return float(text)


def _parse_tree(raw: dict[str, Any], n_features: int) -> _Tree:
    left = np.asarray(raw["left_children"], dtype=np.int64)
    right = np.asarray(raw["right_children"], dtype=np.int64)
    feature = np.asarray(raw["split_indices"], dtype=np.int64)
    condition = np.asarray(raw["split_conditions"], dtype=np.float32)
    default_left = np.asarray(raw["default_left"], dtype=np.int64).astype(bool)
    split_type = np.asarray(raw.get("split_type", [0] * len(left)), dtype=np.int64)
    n = len(left)
    if not n or any(len(a) != n for a in (right, feature, condition, default_left, split_type)):
        raise ModelIntegrityError("tree arrays have inconsistent lengths")
    if split_type.any() or raw.get("categories"):
        raise ModelIntegrityError("categorical splits are not supported")
    if int(raw.get("tree_param", {}).get("size_leaf_vector", "1")) not in (0, 1):
        raise ModelIntegrityError("vector leaves are not supported")
    leaf = left == -1
    if not np.array_equal(leaf, right == -1):
        raise ModelIntegrityError("a node has exactly one child")
    inner = ~leaf
    children = np.concatenate([left[inner], right[inner]])
    if children.size and (children.min() < 1 or children.max() >= n):
        raise ModelIntegrityError("child index out of range")
    # Unique children and a root that is nobody's child: what the root reaches is a tree.
    # (Nodes removed by pruning can stay in the arrays, unreachable; they are never visited.)
    if len(np.unique(children)) != children.size:
        raise ModelIntegrityError("nodes do not form a tree")
    if inner.any() and (feature[inner].min() < 0 or feature[inner].max() >= n_features):
        raise ModelIntegrityError("split feature out of range")
    return _Tree(left, right, feature, condition, default_left)


def parse_model(payload: bytes, sha256: str) -> TreeEnsemble:
    """Parse XGBoost JSON bytes into a :class:`TreeEnsemble` (no integrity check here)."""
    try:
        doc = json.loads(payload)
        learner = doc["learner"]
        objective = learner["objective"]["name"]
        params = learner["learner_model_param"]
        booster = learner["gradient_booster"]
        model = booster["model"]
        feature_names = tuple(learner.get("feature_names") or ())
        n_features = int(params["num_feature"])
    except (ValueError, KeyError, TypeError) as err:
        raise ModelIntegrityError(f"not an XGBoost JSON model ({err})") from err
    if objective != "binary:logistic":
        raise ModelIntegrityError(f"objective {objective!r} is not binary:logistic")
    if booster.get("name") != "gbtree":
        raise ModelIntegrityError("only the gbtree booster is supported")
    if int(params.get("num_class", "0")) > 1 or int(params.get("num_target", "1")) != 1:
        raise ModelIntegrityError("only single-output models are supported")
    if int(model.get("gbtree_model_param", {}).get("num_parallel_tree", "1")) != 1:
        raise ModelIntegrityError("only num_parallel_tree = 1 is supported")
    if any(int(group) != 0 for group in model.get("tree_info", [])):
        raise ModelIntegrityError("only one output group is supported")
    if n_features != N_CYCLES or (feature_names and feature_names != CYC_COLUMNS):
        raise ModelIntegrityError(f"expected features {CYC_COLUMNS[0]}..{CYC_COLUMNS[-1]}")
    base_score = _as_float(params["base_score"])
    if not 0.0 < base_score < 1.0:
        raise ModelIntegrityError("base_score must be a probability for binary:logistic")
    # XGBoost's ProbToMargin for the logistic objective, in float32.
    base_margin = np.float32(-math.log(1.0 / base_score - 1.0))
    trees = tuple(_parse_tree(raw, n_features) for raw in model["trees"])
    if not trees:
        raise ModelIntegrityError("the model has no trees")
    return TreeEnsemble(trees, base_margin, CYC_COLUMNS, sha256)


def _default_files() -> tuple[_Readable, _Readable]:
    from qpilot.models import model_dir

    folder = model_dir(MODEL_NAME)
    return folder.joinpath("model.json"), folder.joinpath("model.sha256")


def load_model(
    model_path: str | Path | None = None,
    sha256_path: str | Path | None = None,
    *,
    expected_sha256: str | None = MODEL_SHA256,
) -> TreeEnsemble:
    """Verify, then parse, the Curve Judge model.

    The bytes are read once; their SHA-256 must equal the digest in ``model.sha256`` and, unless
    ``expected_sha256`` is None (training scripts only), :data:`MODEL_SHA256`. Only then are the
    same bytes parsed, so nothing can change between the check and the use.

    Args:
        model_path: A ``model.json``; defaults to the packaged one.
        sha256_path: Its ``model.sha256``; defaults to the packaged one.
        expected_sha256: The pin compiled into this module.

    Raises:
        ModelIntegrityError: Missing, oversized, modified or unsupported model.
    """
    default_model, default_sha = _default_files()
    model_file: _Readable = Path(model_path) if model_path is not None else default_model
    sha_file: _Readable = Path(sha256_path) if sha256_path is not None else default_sha
    try:
        if isinstance(model_file, Path) and model_file.stat().st_size > MAX_MODEL_BYTES:
            raise ModelIntegrityError("model file is too large")
        payload = model_file.read_bytes()
        pinned = _sha256_pin(sha_file)
    except (OSError, UnicodeDecodeError) as err:
        raise ModelIntegrityError(f"cannot read the Curve Judge model ({err})") from err
    if len(payload) > MAX_MODEL_BYTES:
        raise ModelIntegrityError("model file is too large")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != pinned:
        # Still refused: the pin is on the bytes. Only the message says what the change was.
        crlf = b"\r\n" in payload and hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()
        raise ModelIntegrityError(
            f"model.json SHA-256 {actual[:12]}… does not match model.sha256 {pinned[:12]}…; "
            "refusing to load a modified model" + (CRLF_HINT if crlf == pinned else "")
        )
    if expected_sha256 is not None and actual != expected_sha256:
        raise ModelIntegrityError(
            f"model.json SHA-256 {actual[:12]}… is not the pinned {expected_sha256[:12]}…; "
            "refusing to load a modified model"
        )
    return parse_model(payload, actual)


@lru_cache(maxsize=1)
def shipped_model() -> TreeEnsemble:
    """The packaged model, verified once per process."""
    return load_model()


# ---------------------------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------------------------


def normalise(fluorescence: np.ndarray) -> np.ndarray:
    """The paper's ``Fnorm = Fstand - (Fmin - 1)`` per curve (row); NaN cycles are ignored.

    Identical to ``training/curve_judge/features.normalise`` (the authors' R script, lines
    33-37): the row minimum minus one is subtracted from every cycle, so the minimum becomes 1.
    """
    values = np.asarray(fluorescence, dtype=np.float64)
    if values.ndim != 2:
        raise CurveJudgeError("expected one curve per row")
    out = np.full_like(values, np.nan)
    has_data = ~np.isnan(values).all(axis=1)
    out[has_data] = values[has_data] - (np.nanmin(values[has_data], axis=1, keepdims=True) - 1.0)
    return out


def standardise_without_reference(fluorescence: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-curve stand-in for ROX standardisation on instruments without a passive reference.

    ``Fstand = F / min(F)`` over the curve's cycles 1-40 (pre-registered in
    ``training/curve_judge/transfer.py``). A curve whose minimum is not a positive finite
    number cannot be standardised: it comes back all-NaN and ``callable`` False.

    Returns:
        ``(standardised curves, callable flags)``.
    """
    values = np.asarray(fluorescence, dtype=np.float64)
    minimum = np.where(np.isnan(values), np.inf, values).min(axis=1)  # all-NaN row -> inf
    ok = np.isfinite(minimum) & (minimum > 0) & ~np.isinf(values).any(axis=1)
    out = np.full_like(values, np.nan)
    out[ok] = values[ok] / minimum[ok, None]
    return out, ok


def _curve(adps: Sequence[Sequence[str]]) -> tuple[np.ndarray, int]:
    """Cycles 1-40 of one curve (NaN where absent) and the number of cycles in the file."""
    curve = np.full(N_CYCLES, np.nan)
    cycles = 0
    for point in adps:
        cycle = int(math.ceil(float(point[0])))  # as LinRegPCR reads ``cyc``
        cycles = max(cycles, cycle)
        if 1 <= cycle <= N_CYCLES:
            curve[cycle - 1] = float(point[1])
    return curve, cycles


#: Features already read in this process, by (the file's sha256, experiment); see below.
_FEATURES: dict[tuple[str, str], pd.DataFrame] = {}
_FEATURES_LOCK = threading.Lock()  # one read at a time: a second asker waits, then shares it
FEATURES_KEPT = 4  # a few files at most; the demo's are about 40 MB in memory


def features_from_rdml(rdml_path: str | Path, experiment_id: str) -> pd.DataFrame:
    """:func:`read_features`, kept per file contents and experiment (a fresh copy each time).

    Check the curves, the curve-calls view and the Curve Judge's checks read the same file's
    features; reading them (every curve through rdmlpython) takes ~15 s on the demo.
    """
    from qpilot.core.store import sha256_file

    try:
        key = (sha256_file(Path(rdml_path)), str(experiment_id))
    except OSError:  # not readable: the reader says why, in its own words
        return read_features(rdml_path, experiment_id)
    with _FEATURES_LOCK:
        found = _FEATURES.get(key)
        if found is None:
            found = read_features(rdml_path, experiment_id)
            if len(_FEATURES) >= FEATURES_KEPT:
                _FEATURES.pop(next(iter(_FEATURES)), None)
            _FEATURES[key] = found
    return found.copy()


def features_kept(rdml_path: str | Path, experiment_id: str) -> bool:
    """True when this file's features for the experiment are already in memory."""
    from qpilot.core.store import sha256_file

    try:
        return (sha256_file(Path(rdml_path)), str(experiment_id)) in _FEATURES
    except OSError:
        return False


def read_features(rdml_path: str | Path, experiment_id: str) -> pd.DataFrame:
    """The model's 40 inputs for every well of one experiment, from the raw curves.

    The file is opened only through :func:`qpilot.io.rdml_io.load` (hardened parser) and read
    with the vendored rdmlpython's ``Run.getreactjson(curves=True)``, the same ``adp`` data
    LinRegPCR uses. Per curve: cycles 1-40 (later cycles are dropped, missing ones are NaN),
    :func:`standardise_without_reference`, then :func:`normalise`.

    Returns:
        One row per well, indexed by ``run_id`` and ``well`` (named by
        :func:`qpilot.qpcr.curves.react_well_label`, so rows join
        ``qpilot.qpcr.curves.analyse_study``), with ``sample``, ``target``, ``n_cycles``,
        ``callable`` and ``Cyc1``…``Cyc40``.

    Raises:
        CurveJudgeError: A well holds more than one curve (multiplex), two wells share a
            ``run_id/well`` key, or there are no runs.
        qpilot.io.rdml_io.RdmlLoadError: The file could not be loaded safely.
    """
    from qpilot.io.rdml_io import load, runs
    from qpilot.qpcr.curves import normalise_target, react_well_label, safe_name

    doc = load(rdml_path)
    meta: list[tuple[str, str, str, str, int]] = []
    curves: list[np.ndarray] = []
    for run in runs(doc, experiment_id):
        run_id = safe_name(str(run["id"]), "run")
        n_columns = int(run["pcrFormat_columns"])
        for react in run.getreactjson(curves=True)["reacts"]:
            datas = react.get("datas", [])
            if len(datas) > 1:
                raise CurveJudgeError(
                    f"{run_id} well {react['id']}: {len(datas)} curves in one well; the Curve "
                    "Judge takes one curve per well"
                )
            for data in datas:
                curve, n_cycles = _curve(data.get("adps", []))
                meta.append(
                    (
                        run_id,
                        react_well_label(react["id"], n_columns),
                        safe_name(react.get("sample", ""), "sample"),
                        normalise_target(safe_name(data.get("tar", ""), "target")),
                        n_cycles,
                    )
                )
                curves.append(curve)
    if not meta:
        raise CurveJudgeError(f"experiment {experiment_id!r} has no curves")
    standardised, ok = standardise_without_reference(np.vstack(curves))
    table = pd.DataFrame(meta, columns=["run_id", "well", "sample", "target", "n_cycles"])
    table["callable"] = ok
    table[list(CYC_COLUMNS)] = normalise(standardised)
    if table.duplicated(["run_id", "well"]).any():
        raise CurveJudgeError("duplicate run_id/well keys")
    return table.set_index(["run_id", "well"])


# ---------------------------------------------------------------------------------------------
# Predictions and the validation gate
# ---------------------------------------------------------------------------------------------


def predict_proba(features: pd.DataFrame, model: TreeEnsemble | None = None) -> pd.Series:
    """Probability of amplification per row; NaN where the row is not ``callable``."""
    model = model or shipped_model()
    missing = [c for c in CYC_COLUMNS if c not in features.columns]
    if missing:
        raise CurveJudgeError(f"features lack columns {missing[:3]}…")
    x = features[list(CYC_COLUMNS)].to_numpy(dtype=np.float64)
    ok = features["callable"].to_numpy(dtype=bool) if "callable" in features else None
    if ok is None:
        ok = ~np.isnan(x).all(axis=1)
    p = np.full(len(features), np.nan)
    if ok.any():
        p[ok] = model.predict_proba(x[ok])
    return pd.Series(p, index=features.index, name="learned_p")


def predict(features: pd.DataFrame) -> pd.Series:
    """Amplified (``p > 0.5``) per row of :func:`features_from_rdml`; None = cannot score.

    A row that is not ``callable`` was never read by the model, so it has no call: None
    ("cannot score"), never False ("not amplified"). The values are True, False or None
    (object dtype). This is the ``Callable[[pd.DataFrame], pd.Series]`` that
    ``register_learned`` takes.
    """
    p = predict_proba(features)
    calls = [None if math.isnan(value) else bool(value > THRESHOLD) for value in p]
    return pd.Series(calls, index=p.index, dtype=object, name="learned")


def well_keys(run_id: pd.Series | pd.Index, well: pd.Series | pd.Index) -> pd.Index:
    """``run_id/well`` keys, the subject format of ``curve.well_call`` proposals."""
    return pd.Index(
        [f"{r}/{w}" for r, w in zip(run_id, well, strict=True)], name=KEY_NAME, dtype=str
    )


def predict_calls(rdml_path: str | Path, experiment_id: str) -> pd.Series:
    """The learned call for every well of one experiment, indexed ``run_id/well``.

    True or False, or None for a curve the model cannot score (see :func:`predict`): a caller
    must not count None as "not amplified" or as a disagreement with LinRegPCR. Runs whether
    or not :func:`validated` is True; deciding whether to *offer* it is the caller's job.
    """
    features = features_from_rdml(rdml_path, experiment_id)
    calls = predict(features)
    calls.index = well_keys(
        features.index.get_level_values("run_id"), features.index.get_level_values("well")
    )
    return calls


def _transfer_file() -> _Readable:
    from qpilot.models import model_dir

    return model_dir(MODEL_NAME).joinpath("transfer.json")


def transfer_result(transfer_path: str | Path | None = None) -> dict[str, Any] | None:
    """The recorded transfer test, or None when there is none or it cannot be read."""
    source: _Readable = Path(transfer_path) if transfer_path is not None else _transfer_file()
    try:
        result = json.loads(source.read_bytes())
    except (OSError, ValueError) as err:
        log.info("no readable Curve Judge transfer result: %s", err)
        return None
    return result if isinstance(result, dict) else None


def fingerprint(rdml_path: str | Path) -> dict[str, list[Any]]:
    """What an RDML file declares about its instrument and chemistry, for :func:`validated`.

    Read from every curve of every run in the file (opened only through
    :func:`qpilot.io.rdml_io.load`):

    * ``instrument``: the run's ``<instrument>``, ``""`` when the run names none;
    * ``dye``: ``[dye id, dyeChemistry]`` of the dye of the curve's target, ``""`` for what the
      file does not declare;
    * ``target_type``: the declared type of the curve's target (``toi`` or ``ref``);
    * ``cycles``: the curve's number of cycles, counted as :func:`features_from_rdml` counts
      them (0 for a well without amplification data).

    Each is the sorted list of its distinct values: plain JSON, compared with the record in
    ``transfer.json``. Cached in the process by the file's SHA-256 (its content, wherever it
    lies), for up to :data:`FINGERPRINT_CACHE_SIZE` files.

    Raises:
        qpilot.io.rdml_io.RdmlLoadError: The file could not be loaded safely.
        CurveJudgeError: The file changed while it was being read.
        OSError: The file cannot be read.
    """
    from qpilot.qpcr.curves import file_sha256

    sha256 = file_sha256(rdml_path)
    with _FINGERPRINTS_LOCK:
        cached = _FINGERPRINTS.get(sha256)
        if cached is not None:
            _FINGERPRINTS.move_to_end(sha256)
    if cached is None:
        cached = _read_fingerprint(rdml_path)
        if file_sha256(rdml_path) != sha256:  # never file one file's reading under another
            raise CurveJudgeError("the file changed while it was being read")
        with _FINGERPRINTS_LOCK:
            _FINGERPRINTS[sha256] = cached
            while len(_FINGERPRINTS) > FINGERPRINT_CACHE_SIZE:
                _FINGERPRINTS.popitem(last=False)
    return json.loads(cached)


def _read_fingerprint(path: str | Path) -> str:
    """:func:`fingerprint` of ``path`` as JSON, read from the file (uncached)."""
    from qpilot.io.rdml_io import load, runs

    doc = load(path)
    chemistry = {dye["id"]: dye["dyeChemistry"] or "" for dye in doc.dyes()}
    targets = {t["id"]: (t["type"] or "", t["dyeId"] or "") for t in doc.targets()}
    seen: dict[str, set[Any]] = {key: set() for key in FINGERPRINT_KEYS}
    for run in runs(doc):
        instrument = (run["instrument"] or "").strip()
        for react in run.getreactjson(curves=True)["reacts"]:
            for data in react.get("datas", []):
                target_type, dye = targets.get(data.get("tar", ""), ("", ""))
                seen["instrument"].add(instrument)
                seen["dye"].add((dye, chemistry.get(dye, "")))
                seen["target_type"].add(target_type)
                seen["cycles"].add(_curve(data.get("adps", []))[1])
    return json.dumps({key: sorted(values) for key, values in seen.items()}, sort_keys=True)


def _tested_sha256(result: dict[str, Any]) -> str | None:
    """The SHA-256 of the file the transfer test ran on, when the record names a valid one."""
    data = result.get("data")
    sha256 = data.get("sha256") if isinstance(data, dict) else None
    if isinstance(sha256, str) and len(sha256) == 64 and set(sha256) <= _SHA256_HEX:
        return sha256
    return None


def _names_an_instrument(recorded: Any) -> bool:
    """The record can cover a file other than the tested one: it names at least one instrument.

    A file is covered by its fingerprint only when every run names its instrument, so a record
    whose only instrument is ``""`` (the tested file named none) covers no other file. Checked
    before any other file is read, so such a record costs nothing.
    """
    if not isinstance(recorded, dict) or not isinstance(recorded.get("instrument"), list):
        return False
    return any(isinstance(name, str) and name.strip() for name in recorded["instrument"])


def _within(observed: dict[str, list[Any]], recorded: Any) -> bool:
    """Every run names its instrument, and every value the file shows was in the transfer test.

    A run that names no instrument (``""``) never matches, whatever the record holds: "no
    instrument named" is true of files from any machine, so it ties a file to nothing.
    """
    if not isinstance(recorded, dict) or "" in observed.get("instrument", [""]):
        return False
    for key in FINGERPRINT_KEYS:
        allowed = recorded.get(key)
        if not isinstance(allowed, list) or not observed.get(key):
            return False
        known = {json.dumps(value) for value in allowed}
        if any(json.dumps(value) not in known for value in observed[key]):
            return False
    return True


def validated(
    rdml_path: str | Path | None = None, *, transfer_path: str | Path | None = None
) -> bool:
    """True only if the transfer test passed for the shipped model and covers this input file.

    No file, no claim: without ``rdml_path`` the answer is False. With one, ``transfer.json``
    must name the SHA-256 of the model that actually loads (the packaged one, verified) and
    every criterion must say ``passed: true``. Then the file is covered when either

    * it is the transfer-tested file itself: its SHA-256 equals ``data.sha256`` in the record
      (nothing else is read), or
    * every run in it names its instrument and its :func:`fingerprint` stays within the one
      recorded for the tested file: every instrument, dye, target type and cycle count it
      shows was in the transfer test.

    A file that names no instrument in some run is therefore validated only by its hash.
    Anything missing, unreadable or mismatched counts as not validated.

    Args:
        rdml_path: The input file the learned call would be offered for.
        transfer_path: A ``transfer.json`` other than the packaged one (tests).
    """
    from qpilot.io.rdml_io import RdmlLoadError
    from qpilot.qpcr.curves import file_sha256

    if rdml_path is None:
        return False
    result = transfer_result(transfer_path)
    if result is None:
        return False
    try:
        model = shipped_model()
    except ModelIntegrityError as err:
        log.warning("Curve Judge model refused: %s", err)
        return False
    criteria = result.get("criteria")
    if result.get("model_sha256") != model.sha256 or not isinstance(criteria, dict) or not criteria:
        return False
    if not all(isinstance(c, dict) and c.get("passed") is True for c in criteria.values()):
        return False
    recorded = result.get("fingerprint")
    try:
        tested = _tested_sha256(result)
        if tested is not None and file_sha256(rdml_path) == tested:
            return True
        if not _names_an_instrument(recorded):
            return False  # the record covers the tested file only
        observed = fingerprint(rdml_path)
    except (RdmlLoadError, CurveJudgeError, OSError) as err:
        log.info("no Curve Judge fingerprint for this input: %s", err)
        return False
    return _within(observed, recorded)


def status(rdml_path: str | Path | None = None, *, transfer_path: str | Path | None = None) -> str:
    """``"validated"`` or ``"not validated for this instrument"`` for this input file."""
    return "validated" if validated(rdml_path, transfer_path=transfer_path) else NOT_VALIDATED
