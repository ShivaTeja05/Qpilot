"""What qPilot knows about a file before any study design exists (``qpcr_inspect``).

:func:`inspect` reads an RDML file (only through :func:`qpilot.io.rdml_io.load`) and, if given,
a sample sheet (only through :func:`qpilot.io.sheets.read_sheet`), runs LinRegPCR on every
experiment (:func:`qpilot.qpcr.curves.analyse_study`, cached on disk by content hash) and
returns a deterministic :class:`~qpilot.schemas_studio.InspectSummary`:

* every experiment and run (plate), with its wells and targets;
* every sample as declared in the file: its declared type(s), wells, experiments and targets;
* every target: declared type (``toi``/``ref``), wells, wells with a Cq and the median
  LinRegPCR efficiency of the plates it is on.

Every free-text name in the file (sample, target, experiment and run ids, descriptions,
sample annotations) and every non-empty sheet cell becomes a
:class:`~qpilot.schemas_studio.QuarantineEntry` (``text_id_for(origin, value)``, origins such
as ``rdml:sample.id``). The summary carries the engine's safe identifier for each name
(:func:`qpilot.qpcr.curves.safe_name`) plus the ``text_id`` of the original; the original
text is only in the returned quarantine entries, which the caller stores.

Nothing here interprets names; that is :mod:`qpilot.qpcr.design_rules` (deterministic) and the
AI interpreter (proposals only). Results are cached in the process by the files' sha256.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from qpilot.io import rdml_io
from qpilot.io.sheets import SheetRead, read_sheet, sheet_sha256
from qpilot.qpcr import curves
from qpilot.schemas_studio import (
    InspectRun,
    InspectSample,
    InspectSummary,
    InspectTarget,
    QuarantineEntry,
    text_id_for,
)

log = logging.getLogger(__name__)

#: Columns of :attr:`FileFacts.wells`: the curve table plus the experiment it belongs to.
WELL_COLUMNS = ("experiment_id", *curves.COLUMN_ORDER)


@dataclass
class FileFacts:
    """Everything :func:`inspect` learned, kept for the design rules and the design checks.

    Attributes:
        path: The RDML file.
        sha256: Its sha256 (the cache key).
        summary: The summary :func:`inspect` returns.
        quarantine: The quarantine entries :func:`inspect` returns.
        wells: One row per well and target, every experiment (columns :data:`WELL_COLUMNS`);
            names are safe identifiers.
        sample_types: Safe sample id -> declared ``(type, target)`` pairs (target is the engine
            target name, ``""`` when the type applies to every target).
        sample_quantities: Safe sample id -> declared ``(value, unit, target)`` triples.
        target_types: Engine target name -> declared target type (``toi`` or ``ref``).
        sample_text_ids: Safe sample id -> ``text_id`` of its original id.
        target_text_ids: Engine target name -> ``text_id`` of its original id.
        sheet: The sample sheet as read, or ``None``.
        target_dyes: Engine target name -> the dye it is read in (RDML ``dyeId``, as a safe
            identifier; absent when the file names none): the curves of a multiplex well differ
            by dye.
    """

    path: Path
    sha256: str
    summary: InspectSummary
    quarantine: list[QuarantineEntry]
    wells: pd.DataFrame
    sample_types: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    sample_quantities: dict[str, tuple[tuple[float, str, str], ...]] = field(default_factory=dict)
    target_types: dict[str, str] = field(default_factory=dict)
    sample_text_ids: dict[str, str] = field(default_factory=dict)
    target_text_ids: dict[str, str] = field(default_factory=dict)
    sheet: SheetRead | None = None
    target_dyes: dict[str, str] = field(default_factory=dict)

    def quarantined(self, text_id: str) -> str | None:
        """The original text behind a ``text_id`` (for deterministic rules, never for prompts)."""
        for entry in self.quarantine:
            if entry.text_id == text_id:
                return entry.value
        return None


_CACHE: dict[tuple[str, str | None, str | None], FileFacts] = {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(
    rdml_path: str | Path,
    sheet_path: str | Path | None = None,
    *,
    cache_dir: str | Path | None = None,
) -> tuple[InspectSummary, list[QuarantineEntry]]:
    """Summarise an RDML file (and optional sample sheet) before any design exists.

    Args:
        rdml_path: The instrument export (RDML).
        sheet_path: An optional sample sheet (``.xlsx`` or ``.csv``).
        cache_dir: Curve cache directory (default ``$QPILOT_CACHE_DIR`` or ``~/.cache/qpilot``).

    Returns:
        The summary and every quarantined text (names, descriptions, sheet cells), deduplicated
        by ``text_id``; the caller stores the entries.

    Raises:
        qpilot.io.rdml_io.RdmlLoadError: The RDML file could not be loaded safely.
        qpilot.io.sheets.SheetError: The sheet could not be read safely.
    """
    facts = file_facts(rdml_path, sheet_path, cache_dir=cache_dir)
    return facts.summary.model_copy(deep=True), [e.model_copy() for e in facts.quarantine]


def file_facts(
    rdml_path: str | Path,
    sheet_path: str | Path | None = None,
    *,
    cache_dir: str | Path | None = None,
) -> FileFacts:
    """:func:`inspect`'s full result, cached in the process by the files' sha256.

    The cache is looked up by both files' hashes before anything is parsed, so a session that
    asks again (every Studio render does) never reads its sheet a second time. The returned
    object is shared; treat it as read-only.
    """
    path = Path(rdml_path)
    if not path.is_file():
        raise rdml_io.RdmlLoadError(f"not a file: {path}")
    sha = _sha256(path)
    where = str(cache_dir) if cache_dir else None
    sheet_sha = sheet_sha256(sheet_path) if sheet_path is not None else None
    key = (sha, sheet_sha, where)
    if key not in _CACHE:
        sheet = read_sheet(sheet_path) if sheet_path is not None else None
        key = (sha, sheet.sha256 if sheet else None, where)  # the bytes actually read
        if key not in _CACHE:
            _CACHE[key] = _build(path, sha, sheet, cache_dir)
    return _CACHE[key]


def cached_facts(input_sha256: str) -> FileFacts | None:
    """Facts already built in this process for an input (any sheet), or ``None``.

    ``input_sha256`` may be a prefix of at least six hex characters, as study ids are.
    """
    if len(input_sha256) < 6:
        return None
    for (sha, _, _), facts in _CACHE.items():
        if sha.startswith(input_sha256):
            return facts
    return None


def clear_cache() -> None:
    """Forget every file inspected in this process (tests use it)."""
    _CACHE.clear()


# ---------------------------------------------------------------------------------------------
# Building the summary
# ---------------------------------------------------------------------------------------------


class _Names:
    """Safe identifiers, ``text_id``s and quarantine entries for the file's free text."""

    def __init__(self) -> None:
        self.entries: dict[str, QuarantineEntry] = {}
        self.replaced = 0
        self.seen: dict[tuple[str, str], str] = {}  # (kind, safe) -> original
        self.collisions = 0

    def quarantine(self, origin: str, value: str | None) -> str | None:
        if value is None or str(value) == "":
            return None
        text = str(value)
        text_id = text_id_for(origin, text)
        self.entries.setdefault(
            text_id, QuarantineEntry(text_id=text_id, origin=origin, value=text)
        )
        return text_id

    def name(self, kind: str, origin: str, value: str) -> tuple[str, str]:
        """(safe identifier, text_id) for a name from the file."""
        text_id = self.quarantine(origin, value) or text_id_for(origin, "")
        safe = curves.safe_name(value, kind)
        if safe != value:
            self.replaced += 1
        previous = self.seen.setdefault((kind, safe), value)
        if previous != value:
            self.collisions += 1
        return safe, text_id


def _build(
    path: Path, sha: str, sheet: SheetRead | None, cache_dir: str | Path | None
) -> FileFacts:
    doc = rdml_io.load(path)
    names = _Names()
    loaded = rdml_io.load_notes(doc)
    notes: list[str] = list(loaded.notes)  # what the loader repaired (none for a clean file)
    for kind, renamed in sorted(loaded.renamed.items()):
        for original in renamed:  # the file's own ids, quarantined like every name in it
            names.quarantine(f"rdml:{kind}.id", original)

    target_names: dict[str, str] = {}  # original target id -> engine target name
    target_types: dict[str, str] = {}
    target_text_ids: dict[str, str] = {}
    target_order: list[tuple[str, str]] = []  # (engine name, original id)
    target_dyes: dict[str, str] = {}
    for target in doc.targets():
        original = str(target["id"])
        safe, text_id = names.name("target", "rdml:target.id", original)
        engine = curves.normalise_target(safe)
        names.quarantine("rdml:target.description", target["description"])
        target_names[original] = engine
        target_types.setdefault(engine, str(target["type"] or "toi"))
        target_text_ids.setdefault(engine, text_id)
        target_order.append((engine, original))
        dye = str(target["dyeId"] or "").strip()
        if dye:
            target_dyes.setdefault(engine, curves.safe_name(dye, "dye"))

    sample_types: dict[str, tuple[tuple[str, str], ...]] = {}
    sample_quantities: dict[str, tuple[tuple[float, str, str], ...]] = {}
    sample_text_ids: dict[str, str] = {}
    sample_order: list[str] = []
    for sample in doc.samples():
        original = str(sample["id"])
        safe, text_id = names.name("sample", "rdml:sample.id", original)
        names.quarantine("rdml:sample.description", sample["description"])
        for annotation in sample.annotations():
            names.quarantine("rdml:sample.annotation", annotation.get("property"))
            names.quarantine("rdml:sample.annotation", annotation.get("value"))
        types = tuple(
            (str(t["type"]), target_names.get(t.get("targetId") or "", ""))
            for t in sample.types()
            if t.get("type")
        ) or (("unkn", ""),)
        quantities = []
        for quantity in sample.quantitys():
            try:
                value = float(quantity.get("value", ""))
            except ValueError:
                continue
            target = target_names.get(quantity.get("targetId") or "", "")
            quantities.append((value, str(quantity.get("unit") or ""), target))
        sample_types[safe] = types
        sample_quantities[safe] = tuple(quantities)
        sample_text_ids.setdefault(safe, text_id)
        if safe not in sample_order:
            sample_order.append(safe)

    tables: list[pd.DataFrame] = []
    experiments: dict[str, int] = {}
    run_rows: list[InspectRun] = []
    for experiment in doc.experiments():
        original = str(experiment["id"])
        exp_safe, exp_text_id = names.name("experiment", "rdml:experiment.id", original)
        names.quarantine("rdml:experiment.description", experiment["description"])
        runs = list(experiment.runs())
        experiments[exp_safe] = len(runs)
        for run in runs:
            names.name("run", "rdml:run.id", str(run["id"]))
            names.quarantine("rdml:run.description", run["description"])
        if not runs:
            continue
        try:
            table = curves.analyse_study(path, original, cache_dir=cache_dir)
        except curves.CurveAnalysisError as err:
            log.warning("LinRegPCR failed on an experiment of %s: %s", path.name, err)
            curveless = not any(_has(run, "adp") for run in runs)
            if curveless and any(_has(run, "cq") for run in runs):
                notes.append(  # a Cq table or a Cq-only RDML: nothing to fit, nothing failed
                    f"Experiment {exp_text_id} holds Cq values only (no amplification curves), "
                    "so LinRegPCR has nothing to fit; only those Cq values can be analysed."
                )
            else:
                notes.append(
                    f"LinRegPCR could not analyse experiment {exp_text_id}; its wells are listed "
                    "without Cq or efficiency."
                )
            table = _wells_without_curves(runs, sample_types, target_names)
        table = table.copy()
        table.insert(0, "experiment_id", exp_safe)
        tables.append(table)
        for run in runs:
            run_id = curves.safe_name(str(run["id"]), "run")
            on_run = table[table["run_id"] == run_id]
            run_rows.append(
                InspectRun(
                    experiment_id=exp_safe,
                    run_id=run_id,
                    n_wells=int(on_run["well"].nunique()),
                    targets=sorted(on_run["target"].unique().tolist()),
                )
            )

    wells = (
        pd.concat(tables, ignore_index=True)
        if tables
        else pd.DataFrame({column: pd.Series(dtype=object) for column in WELL_COLUMNS})
    )
    samples = _samples(wells, sample_order, sample_types, sample_text_ids)
    targets = _targets(wells, target_order, target_types, target_text_ids)
    declared = Counter(s.declared_type for s in samples)
    if names.replaced:
        notes.append(
            f"{names.replaced} names in the file were not plain identifiers; qPilot uses a safe "
            "identifier for each (the original is quarantined)."
        )
    if names.collisions:
        notes.append(
            f"{names.collisions} different names in the file share one safe identifier; check "
            "them before confirming a design."
        )
    if any(len(t) > 1 or t[0][1] for t in sample_types.values()):
        notes.append("Some samples declare a type for one target only (RDML per-target types).")
    entries = dict(names.entries)
    summary = InspectSummary(
        input_sha256=sha,
        n_samples=len(samples),
        declared_types=dict(sorted(declared.items())),
        experiments=experiments,
        runs=run_rows,
        samples=samples,
        targets=targets,
        notes=notes,
    )
    if sheet is not None:
        summary.sheet = list(sheet.cells)
        summary.sheet_sha256 = sheet.sha256
        summary.notes.extend(sheet.notes)
        for entry in sheet.quarantine:
            entries.setdefault(entry.text_id, entry)
    return FileFacts(
        path=path,
        sha256=sha,
        summary=summary,
        quarantine=list(entries.values()),
        wells=wells,
        sample_types=sample_types,
        sample_quantities=sample_quantities,
        target_types=target_types,
        sample_text_ids=sample_text_ids,
        target_text_ids=target_text_ids,
        sheet=sheet,
        target_dyes=target_dyes,
    )


def _has(run, tag: str) -> bool:
    """Whether any reaction of an RDML run holds a ``tag`` element (``adp``, ``cq``)."""
    return next(run._node.iter(f"{rdml_io.NS}{tag}"), None) is not None


def declared_type_label(types: tuple[tuple[str, str], ...]) -> str:
    """One label for a sample's declared types: ``unkn``, or ``pos@MYCN,unkn`` for mixed ones."""
    labels = sorted({f"{t}@{target}" if target else t for t, target in types})
    return ",".join(labels) if labels else "unkn"


def _samples(
    wells: pd.DataFrame,
    order: list[str],
    sample_types: dict[str, tuple[tuple[str, str], ...]],
    text_ids: dict[str, str],
) -> list[InspectSample]:
    grouped = {name: group for name, group in wells.groupby("sample", sort=False)}
    out = []
    for sample in order:
        group = grouped.get(sample)
        if group is None:
            n_wells, experiments, targets = 0, [], []
        else:
            n_wells = int(group[["run_id", "well"]].drop_duplicates().shape[0])
            experiments = sorted(group["experiment_id"].unique().tolist())
            targets = sorted(group["target"].unique().tolist())
        out.append(
            InspectSample(
                sample=sample,
                text_id=text_ids[sample],
                declared_type=declared_type_label(sample_types[sample]),
                n_wells=n_wells,
                experiments=experiments,
                targets=targets,
            )
        )
    return out


def _targets(
    wells: pd.DataFrame,
    order: list[tuple[str, str]],
    target_types: dict[str, str],
    text_ids: dict[str, str],
) -> list[InspectTarget]:
    out = []
    done: set[str] = set()
    for engine, _original in order:
        if engine in done:
            continue
        done.add(engine)
        group = wells[wells["target"] == engine]
        with_cq = group[group["cq"].notna()]
        efficiencies = with_cq["eff_target"].dropna()
        eff = float(np.median(efficiencies)) if len(efficiencies) else None
        out.append(
            InspectTarget(
                target=engine,
                text_id=text_ids[engine],
                declared_type=target_types.get(engine, "toi"),
                n_wells=int(group[["run_id", "well"]].drop_duplicates().shape[0]),
                n_with_cq=int(len(with_cq)),
                eff_median=round(eff, 4) if eff is not None else None,
            )
        )
    return out


def _wells_without_curves(
    runs: list,
    sample_types: dict[str, tuple[tuple[str, str], ...]],
    target_names: dict[str, str],
) -> pd.DataFrame:
    """The wells of runs LinRegPCR could not analyse, from the reactions alone (no Cq)."""
    rows = []
    for run in runs:
        run_id = curves.safe_name(str(run["id"]), "run")
        for react in run.getreactjson(curves=False).get("reacts", []):
            sample = curves.safe_name(str(react.get("sample", "")), "sample")
            declared = sample_types.get(sample, (("unkn", ""),))[0][0]
            for data in react.get("datas", []):
                raw = str(data.get("tar", ""))
                rows.append(
                    {
                        "run_id": run_id,
                        "well": str(react.get("id", "")),
                        "sample": sample,
                        "sample_type": declared,
                        "target": target_names.get(raw, curves.normalise_target(raw)),
                        "target_raw": curves.safe_name(raw, "target"),
                        "target_type": "toi",
                        "excluded": "",
                        "note": "not analysed",
                        "amplification": False,
                        "plateau": False,
                    }
                )
    table = pd.DataFrame(rows, columns=list(curves.COLUMN_ORDER))
    for column in curves.NUMERIC_COLUMNS:
        table[column] = np.nan
    for column in curves.BOOL_COLUMNS:
        table[column] = table[column].fillna(False).astype(bool)
    return table


__all__ = [
    "WELL_COLUMNS",
    "FileFacts",
    "cached_facts",
    "clear_cache",
    "declared_type_label",
    "file_facts",
    "inspect",
]
