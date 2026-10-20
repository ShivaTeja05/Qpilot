"""Raw amplification curves, read from the RDML file one plate at a time (for the curve viewer).

The Curve Judge reads every curve of an experiment normalised (each divided by its minimum);
the page shows the instrument's own fluorescence instead, so the Cq and LinRegPCR's baseline
(both in the file's units) sit on the same axis. The file is opened only through the hardened
loader (:func:`qpilot.io.rdml_io.load`); a loaded document and the plates read from it are kept
in memory for the few files this process shows.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_DOCS = 2
MAX_RUNS = 32


@dataclass(frozen=True)
class RawWell:
    """One curve of one well (one target) as the file holds it."""

    well: str
    sample: str
    target: str
    cycles: tuple[int, ...]
    values: tuple[float | None, ...]


_lock = threading.Lock()
_docs: OrderedDict[tuple[str, int, int], Any] = OrderedDict()
_runs: OrderedDict[tuple[tuple[str, int, int], str], dict[tuple[str, str], RawWell]] = OrderedDict()


def _file_key(path: Path) -> tuple[str, int, int]:
    st = path.stat()
    return (str(path.resolve()), st.st_mtime_ns, st.st_size)


def _doc(path: Path, key: tuple[str, int, int]) -> Any:
    from qpilot.io.rdml_io import load

    doc = _docs.get(key)
    if doc is None:
        # The session's file was validated when it was opened (and is bound by its sha256);
        # the hardened parser still reads it, the schema check is not repeated.
        doc = load(path, validate=False)
        _docs[key] = doc
        while len(_docs) > MAX_DOCS:
            _docs.popitem(last=False)
    else:
        _docs.move_to_end(key)
    return doc


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def raw_run(path: str | Path, run_id: str) -> dict[tuple[str, str], RawWell]:
    """Every curve of one plate, keyed by ``(well, target)`` (engine names, as in the tables).

    Raises:
        KeyError: The file has no plate ``run_id``.
        qpilot.io.rdml_io.RdmlLoadError: The file could not be loaded safely.
    """
    from qpilot.io.rdml_io import runs
    from qpilot.qpcr.curves import normalise_target, react_well_label, safe_name

    path = Path(path)
    with _lock:
        key = _file_key(path)
        cached = _runs.get((key, run_id))
        if cached is not None:
            return cached
        doc = _doc(path, key)
        found = None
        for run in runs(doc, None):
            if safe_name(str(run["id"]), "run") == run_id:
                found = run
                break
        if found is None:
            raise KeyError(f"no plate {run_id!r} in this file")
        n_columns = int(found["pcrFormat_columns"])
        out: dict[tuple[str, str], RawWell] = {}
        for react in found.getreactjson(curves=True)["reacts"]:
            well = react_well_label(react["id"], n_columns)
            sample = safe_name(str(react.get("sample", "")), "sample")
            for data in react.get("datas", []):
                target = normalise_target(safe_name(str(data.get("tar", "")), "target"))
                points: dict[int, float | None] = {}
                for point in data.get("adps", []):
                    try:
                        cycle = int(math.ceil(float(point[0])))
                    except (TypeError, ValueError, IndexError):
                        continue
                    points[cycle] = _number(point[1]) if len(point) > 1 else None
                cycles = tuple(sorted(points))
                out[(well, target)] = RawWell(
                    well, sample, target, cycles, tuple(points[c] for c in cycles)
                )
        _runs[(key, run_id)] = out
        while len(_runs) > MAX_RUNS:
            _runs.popitem(last=False)
        return out
