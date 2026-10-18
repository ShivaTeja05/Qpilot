"""Open a lab's own RDML file on the results screen.

The screen needs one run of the engine per file. :func:`prepare` reuses a run whose
``summary.json`` was made from the same bytes (same SHA-256), or makes a quick one in
``<results>/plates/<first 12 hex digits of the SHA-256>/``. The quick run is the full
analysis sweep with influence, the joint test and troubleshooting. It skips the planted-fault
benchmark, the small-experiment draws and the cheaper-search check, which test the method rather
than the file and take minutes.

Before the run, :func:`check` tests that the file fits the current two-group design: the
experiment, the marker gene, the reference genes, one well per sample and gene, and enough
samples in each group. When it does not fit, :class:`PlateProblem` says why in plain words.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from qpilot.io.rdml_io import RdmlLoadError
from qpilot.qpcr.curves import (
    DEMO_EXPERIMENT,
    REFERENCE_TARGETS,
    CurveAnalysisError,
    analyse_study,
)
from qpilot.qpcr.design import DEMO_MARKER

from qsim.data import BENCHMARK_NAME, Study, sha256, study_from_curves

PLATES = "plates"
INPUT = "input.rdml"
MAX_BYTES = 32 << 20  # a 64-plate LightCycler export is 7 MB
MIN_GROUP = 3  # fewest samples in either group, at every group cut-off
# the quick run: no planted faults, no small-experiment draws, no cheaper-search check
QUICK = {"permutations": 199, "bench_trials": 0, "design_draws": 0, "explorer": False}
# the files the screen cannot do without (validation and one-sample flips are optional)
REQUIRED = ("explain.json", "genes.csv", "issues.json", "summary.json", "decisions.csv")

Progress = Callable[[str], None]


class PlateProblem(Exception):
    """A file the screen cannot analyse, with the reason in plain words.

    ``design`` marks a file that does not fit the two-group design; the terminal then adds
    :func:`design_words` (the page shows them above its file picker already).
    """

    def __init__(self, message: str, detail: str = "", design: bool = False):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.design = design

    def full(self) -> str:
        return f"{self.message} {design_words()}" if self.design else self.message


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def design_words() -> str:
    """The current two-group design, as the screen states it."""
    return (
        f"The current design compares samples high in {DEMO_MARKER} with the rest. It reads the "
        f"plates of an experiment named “{DEMO_EXPERIMENT}”, normalises to the reference genes "
        f"{_join(list(REFERENCE_TARGETS))}, and expects one well per sample and gene."
    )


NOT_YET = "Other designs, such as dilution series or groups you define, are not supported yet."


def plate_dir(results: str | Path, digest: str) -> Path:
    return Path(results) / PLATES / digest[:12]


def has_run(folder: Path, digest: str) -> bool:
    """True when ``folder`` holds a complete run made from the file with this SHA-256."""
    if not all((folder / f).exists() for f in REQUIRED):
        return False
    try:
        return json.loads((folder / "summary.json").read_text())["input_sha256"] == digest
    except (ValueError, KeyError):
        return False


def check(rdml: str | Path, progress: Progress = print) -> Study:
    """Read every curve and test the file against the two-group design.

    Raises :class:`PlateProblem` with a plain-language reason when the file cannot be analysed.
    """
    path = Path(rdml)
    progress("Reading every curve with LinRegPCR")
    try:
        curves = analyse_study(path, DEMO_EXPERIMENT, REFERENCE_TARGETS)
    except RdmlLoadError as err:
        found = re.match(r"no experiment '.*' \(found: (.*)\)$", str(err))
        if found:
            names = [f"“{n}”" for n in found.group(1).split(", ") if n]
            its = (
                f"Its only experiment is {names[0]}. "
                if len(names) == 1
                else f"Its experiments are {_join(names)}. "
                if names
                else ""
            )
            raise PlateProblem(
                "This file cannot be analysed with the current two-group design: it has no "
                f"experiment named “{DEMO_EXPERIMENT}”. {its}{NOT_YET}",
                str(err),
                design=True,
            ) from err
        raise PlateProblem(
            "This file could not be read as an RDML file. Export the run from your "
            "instrument's software as RDML (.rdml) and open that file.",
            str(err),
        ) from err
    except CurveAnalysisError as err:
        raise PlateProblem(
            "LinRegPCR could not analyse the curves on one of the plates in this file.", str(err)
        ) from err

    progress("Checking the file fits the two-group design")
    marker = DEMO_MARKER.split("(")[0]
    unknown = curves[curves["sample_type"] == "unkn"]
    if unknown.empty:
        raise PlateProblem(
            "This file has only standards and controls, no sample wells, so there are no two "
            "groups to compare.",
            design=True,
        )
    targets = sorted(set(unknown["target"]))
    shown = _join(targets[:12] + ([f"{len(targets) - 12} more"] if len(targets) > 12 else []))
    if DEMO_MARKER not in targets:
        raise PlateProblem(
            f"This file has no {DEMO_MARKER} wells, so its samples cannot be split into "
            f"{marker}-high and the rest. Genes in this file: {shown}. {NOT_YET}",
            design=True,
        )
    missing = [g for g in REFERENCE_TARGETS if g not in targets]
    if missing:
        raise PlateProblem(
            f"This file has no wells for the reference gene{'s' if len(missing) > 1 else ''} "
            f"{_join(missing)}. Genes in this file: {shown}. {NOT_YET}",
            design=True,
        )
    if unknown.duplicated(["sample", "target"]).any():
        raise PlateProblem(
            "This file has more than one well for the same sample and gene (technical "
            "replicates). Replicate wells are not combined yet.",
            design=True,
        )
    try:
        study = study_from_curves(curves, sha256(path))
    except (ValueError, KeyError) as err:
        raise PlateProblem(
            "The samples could not be split into two groups.", str(err), design=True
        ) from err
    for cut, (high, rest) in sorted(study.groups.items()):
        if min(len(high), len(rest)) < MIN_GROUP:
            raise PlateProblem(
                f"Too few samples: with the top {cut:.0%} by {marker} expression, the "
                f"{marker}-high group has {len(high)} sample{'s' if len(high) != 1 else ''} and "
                f"the rest has {len(rest)}. Each group needs at least {MIN_GROUP}, so the file "
                f"needs at least {math.ceil(MIN_GROUP / min(study.groups))} samples with "
                f"{DEMO_MARKER} and every reference gene measured."
            )
    if not study.items:
        raise PlateProblem(
            f"This file has no genes to compare: it measures only {DEMO_MARKER} and the "
            "reference genes."
        )
    return study


def prepare(
    rdml: str | Path,
    results: str | Path = "results",
    *,
    name: str | None = None,
    progress: Progress = print,
) -> Path:
    """The results folder for this file: an existing run of the same bytes, or a quick new one."""
    from qsim.report import run_all
    from qsim.study_space import space_for

    path = Path(rdml)
    if not path.is_file():
        raise PlateProblem(f"There is no file at {path}.")
    digest = sha256(path)
    for folder in (Path(results), plate_dir(results, digest)):
        if has_run(folder, digest):
            return folder
    study = check(path, progress)
    cells = math.prod(space_for(study)[0].levels)
    out = plate_dir(results, digest)
    progress(
        f"Running all {cells:,} analyses of {len(study.samples)} samples and "
        f"{len(study.items)} genes"
    )
    try:
        run_all(str(path), out, **QUICK, source=name or path.name)
    except Exception as err:  # the design check passed, so this is a gap in the engine
        raise PlateProblem(
            "The file fits the design, but the analysis stopped part way. The details below "
            "say where.",
            f"{type(err).__name__}: {err}",
        ) from err
    return out


def looks_like_rdml(data: bytes) -> bool:
    """A zip archive (how instruments export RDML) or an XML document."""
    return data.startswith(b"PK\x03\x04") or data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] == b"<"


def save_upload(data: bytes, results: str | Path) -> Path:
    """Keep an uploaded file as ``plates/<sha>/input.rdml``; the name a user gave is not used."""
    if len(data) > MAX_BYTES:
        raise PlateProblem(f"This file is larger than {MAX_BYTES >> 20} MB.")
    if not looks_like_rdml(data):
        raise PlateProblem(
            "This is not an RDML file. Export the run from your instrument's software as RDML "
            "(.rdml) and open that file."
        )
    folder = plate_dir(results, hashlib.sha256(data).hexdigest())
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / INPUT
    if not target.exists():
        tmp = folder / (INPUT + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
    return target


def discard(results: str | Path, folder: Path) -> None:
    """Remove a plate folder whose run never finished (only inside ``results/plates``)."""
    root = (Path(results) / PLATES).resolve()
    folder = folder.resolve()
    if folder.parent == root and not (folder / "summary.json").exists():
        shutil.rmtree(folder, ignore_errors=True)


def opened(results: str | Path) -> list[dict]:
    """Every complete run under ``results``: the main one first, then each opened plate."""
    out = []
    root = Path(results)
    for folder in [root, *sorted((root / PLATES).glob("*/"))]:
        summary = folder / "summary.json"
        if not all((folder / f).exists() for f in REQUIRED):
            continue
        try:
            s = json.loads(summary.read_text())
        except ValueError:
            continue
        out.append(
            {
                "id": "" if folder == root else folder.name,
                "name": (s.get("source") or {}).get("name") or BENCHMARK_NAME,
                "samples": s["study"]["samples"],
                "genes": s["study"]["genes_compared"],
                "dir": folder,
                "time": summary.stat().st_mtime,
            }
        )
    return out[:1] + sorted(out[1:], key=lambda p: -p["time"])
