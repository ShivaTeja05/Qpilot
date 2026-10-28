"""The study's RDML file with qPilot's per-well results written back into it (for a supplement).

RDML (Lefever et al. 2009; RDML 1.3/1.4) has a place for each reaction's results: ``<cq>``,
``<N0>``, ``<ampEffMet>``, ``<ampEff>`` and ``<excl>`` inside each ``<data>`` element, where
LinRegPCR itself writes them back. :func:`write_back` copies the study's input file and fills
those elements from the per-well table (:mod:`qpilot.report.tables`), in the order the RDML
schema requires:

* ``cq``: the Cq of qPilot's curve analysis (LinRegPCR's TD0), as LinRegPCR writes it back;
* ``N0``, ``ampEffMet`` (``LinRegPCR``) and ``ampEff`` (the assay's mean efficiency on the
  plate): RDML 1.3 and later only (older versions have no such elements, so a 1.0–1.2 file gets
  the Cq and the exclusions);
* ``excl``: for a well a person left out, ``qPilot: left out by a person: <their reason>``,
  after any exclusion text the file already had.

A study whose quantities come from the instrument's Cq (an import without curves) keeps its Cq
and gets only the exclusions. Wells, runs and targets are found by the names the per-well table
uses (:func:`qpilot.qpcr.curves.safe_name`, the plate width, :func:`normalise_target`); nothing
else in the file changes. The result is checked against the RDML schema of its version; a file
that would not pass is never written: the caller ships the original file and the per-well CSV
instead, and says so. Deterministic: the same study gives the same bytes.
"""

from __future__ import annotations

import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

#: Child order of ``<data>`` per RDML version (from the schemas vendored with rdmlpython).
DATA_ORDER: dict[str, tuple[str, ...]] = {
    "1.0": ("tar", "cq", "quantity", "excl", "adp", "mdp", "endPt", "bgFluor", "quantFluor"),
    "1.1": ("tar", "cq", "excl", "adp", "mdp", "endPt", "bgFluor", "quantFluor"),
    "1.2": ("tar", "cq", "excl", "adp", "mdp", "endPt", "bgFluor", "bgFluorSlp", "quantFluor"),
    "1.3": (
        "tar", "cq", "N0", "ampEffMet", "ampEff", "ampEffSE", "corrF", "corrP", "corrCq",
        "meltTemp", "excl", "note", "adp", "mdp", "endPt", "bgFluor", "bgFluorSlp", "quantFluor",
    ),
    "1.4": (
        "tar", "cq", "N0", "Ncopy", "ampEffMet", "ampEff", "ampEffSE", "corrF", "corrP",
        "corrCq", "meltTemp", "excl", "note", "adp", "mdp", "endPt", "bgFluor", "bgFluorSlp",
        "quantFluor",
    ),
}  # fmt: skip
QUANT_VERSIONS = ("1.3", "1.4")
EXCL_PREFIX = "qPilot: left out by a person: "
RDML_MEMBER = "rdml_data.xml"


class RdmlOutError(ValueError):
    """The results cannot be written into this RDML file (the message says why)."""


@dataclass(frozen=True)
class WriteBack:
    """An RDML archive with qPilot's results, and what was written into it."""

    data: bytes
    version: str
    n_wells: int
    n_cq: int
    n_n0: int
    n_excluded: int
    quantities: bool

    def describe(self) -> str:
        """One line for a README."""
        what = ["Cq"] if self.n_cq else []
        if self.quantities:
            what.append("N0 and efficiency")
        if not what:
            what = ["exclusions only"]
        return (
            f"RDML {self.version}: {self.n_wells} reactions matched; written: "
            f"{', '.join(what)}; {self.n_excluded} wells marked left out (excl)."
        )


def _xml(source: Path) -> bytes:
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            member = RDML_MEMBER if RDML_MEMBER in names else None
            if member is None:
                xml = [n for n in names if n.lower().endswith(".xml")]
                if len(xml) != 1:
                    raise RdmlOutError("the RDML archive has no single XML document")
                member = xml[0]
            return archive.read(member)
    return source.read_bytes()


def _local(el: Any) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _child(parent: Any, name: str) -> Any:
    return next((c for c in parent if _local(c) == name), None)


def _set(data: Any, name: str, text: str, order: tuple[str, ...]) -> None:
    """Set (or add, in schema order) one child element's text."""
    existing = _child(data, name)
    if existing is not None:
        existing.text = text
        return
    rank = order.index(name)
    position = 0
    for i, c in enumerate(data):
        local = _local(c)
        if local in order and order.index(local) < rank:
            position = i + 1
    el = etree.Element(etree.QName(etree.QName(data).namespace, name) if
                       etree.QName(data).namespace else name)  # fmt: skip
    el.text = text
    data.insert(position, el)


def _number(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return repr(v) if v == v and v not in (float("inf"), float("-inf")) else None


def write_back(
    source: str | Path,
    wells: Mapping[tuple[str, str, str], Mapping[str, Any]],
    *,
    experiment_id: str | None = None,
    quantities: bool = True,
    validate: bool = True,
) -> WriteBack:
    """The study's RDML with each matched well's results written into its ``<data>``.

    Args:
        source: The study's input file (an RDML archive or plain RDML XML).
        wells: ``(plate, well, target) -> {"cq", "n0", "efficiency", "left_out", "reason"}``,
            keyed as the per-well table names them.
        experiment_id: Only this experiment's runs (all when None).
        quantities: Write Cq, N0 and the efficiency (False: exclusions only, for a study whose
            quantities are the instrument's Cq).
        validate: Check the result against the RDML schema of its version.

    Raises:
        RdmlOutError: Not RDML, an unknown version, nothing matched, or the result fails the
            schema.
    """
    from qpilot.io.connectors.builder import rdml_archive
    from qpilot.io.rdml_io import hardened_parser
    from qpilot.qpcr.curves import normalise_target, react_well_label, safe_name

    path = Path(source)
    try:
        root = etree.fromstring(_xml(path), hardened_parser())
    except (etree.XMLSyntaxError, OSError, zipfile.BadZipFile) as err:
        raise RdmlOutError(f"the input file cannot be read as RDML ({err})") from err
    if _local(root) != "rdml":
        raise RdmlOutError("the input file is not RDML")
    version = str(root.get("version") or "")
    if version not in DATA_ORDER:
        raise RdmlOutError(f"RDML version {version!r} is not one qPilot can write into")
    order = DATA_ORDER[version]
    quant = quantities and version in QUANT_VERSIONS  # N0 and efficiency exist from RDML 1.3
    n_wells = n_cq = n_n0 = n_excl = 0
    for experiment in (c for c in root if _local(c) == "experiment"):
        if experiment_id is not None and experiment.get("id") != experiment_id:
            continue
        for run in (c for c in experiment if _local(c) == "run"):
            run_id = safe_name(str(run.get("id")), "run")
            fmt = _child(run, "pcrFormat")
            columns = _child(fmt, "columns") if fmt is not None else None
            try:
                n_columns = int(str(columns.text).strip()) if columns is not None else 0
            except ValueError:
                n_columns = 0
            if n_columns < 1:
                continue
            for react in (c for c in run if _local(c) == "react"):
                try:
                    well = react_well_label(str(react.get("id")), n_columns)
                except ValueError:
                    continue
                for data in (c for c in react if _local(c) == "data"):
                    tar = _child(data, "tar")
                    if tar is None:
                        continue
                    target = normalise_target(safe_name(str(tar.get("id")), "target"))
                    row = wells.get((run_id, well, target))
                    if row is None:
                        continue
                    n_wells += 1
                    cq = _number(row.get("cq")) if quantities else None
                    if cq is not None:
                        _set(data, "cq", cq, order)
                        n_cq += 1
                    if quant:
                        n0 = _number(row.get("n0"))
                        eff = _number(row.get("efficiency"))
                        if n0 is not None:
                            _set(data, "N0", n0, order)
                            n_n0 += 1
                        if eff is not None:
                            _set(data, "ampEffMet", "LinRegPCR", order)
                            _set(data, "ampEff", eff, order)
                    if row.get("left_out"):
                        old = _child(data, "excl")
                        before = (old.text or "").strip() if old is not None else ""
                        text = EXCL_PREFIX + str(row.get("reason") or "no reason recorded")
                        if before and EXCL_PREFIX not in before:
                            text = f"{before}; {text}"
                        _set(data, "excl", text, order)
                        n_excl += 1
    if not n_wells:
        raise RdmlOutError("no reaction of the file matched the study's wells")
    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    data = rdml_archive(xml)
    if validate:
        _validate(data)
    return WriteBack(data, version, n_wells, n_cq, n_n0, n_excl, quant)


def _validate(data: bytes) -> None:
    from qpilot.io.rdml_io import RdmlLoadError, load

    with tempfile.TemporaryDirectory(prefix="qpilot-rdml-") as tmp:
        path = Path(tmp) / "check.rdml"
        path.write_bytes(data)
        try:
            load(path, migrate=False, validate=True)
        except RdmlLoadError as err:
            raise RdmlOutError(f"the RDML with results does not pass its schema ({err})") from err


def wells_from_table(records: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """The per-well table's records keyed ``(plate, well, target)`` for :func:`write_back`."""
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in records:
        out[(str(r["plate"]), str(r["well"]), str(r["target"]))] = {
            "cq": r.get("cq"),
            "n0": r.get("n0"),
            "efficiency": r.get("efficiency_assay"),
            "left_out": bool(r.get("left_out")),
            "reason": r.get("left_out_reason"),
        }
    return out


__all__ = ("RdmlOutError", "WriteBack", "wells_from_table", "write_back")
