"""RDML files: the first connector. Loading goes through :func:`qpilot.io.rdml_io.load`.

An RDML file is already what the engine reads, so this connector never rewrites it: the
registry hands the engine the file itself (its path and sha256 stay the study's identity). It
still describes the file the way every other connector does (plates, wells, layers, sample
types, the free text in it) so that the raw-ness detector and the Import Trust Card work the
same for RDML as for a vendor export. :func:`plates_from_document` walks the XML directly
(namespace-aware), which is much faster than rdmlpython's JSON views on a 64-plate file.
"""

from __future__ import annotations

from pathlib import Path

from qpilot.io import rdml_io
from qpilot.io.connectors.base import (
    CaptureError,
    Curve,
    PlateData,
    Probe,
    Reaction,
    Sniff,
    Source,
)
from qpilot.io.connectors.builder import well_name
from qpilot.io.connectors.tables import number

NS = "{http://www.rdml.org}"


class RdmlConnector:
    """RDML 1.0-1.4 (zipped ``.rdml``/``.rdm`` or plain XML), loaded with every hardening layer."""

    id = "rdml"
    version = "1"
    label = "RDML file"
    suffixes = (".rdml", ".rdm", ".xml")

    def sniff(self, probe: Probe) -> Sniff | None:
        """An RDML zip (``rdml_data.xml``, or one XML member holding ``<rdml``) or RDML XML.

        CFX Manager 3.0 names the archive's member after the file; a zip of another kind with
        an ``.rdml`` suffix is still claimed, so its refusal speaks of RDML.
        """
        if probe.kind == "zip":
            import zipfile
            import zlib

            try:
                with zipfile.ZipFile(probe.path) as archive:
                    infos = archive.infolist()
                    if any(i.filename == rdml_io.RDML_MEMBER for i in infos):
                        return Sniff(100, "rdml.zip")
                    xml = [i for i in infos if i.filename.lower().endswith(".xml")]
                    if len(xml) == 1 and not xml[0].is_dir():
                        with archive.open(xml[0]) as member:
                            head = member.read(4096)  # a few KB, whatever the member holds
                        if b"<rdml" in head or b":rdml" in head:
                            return Sniff(95, "rdml.zip.member")
            except (zipfile.BadZipFile, zlib.error, OSError, EOFError, ValueError):
                return None
            if probe.suffix in (".rdml", ".rdm"):
                return Sniff(60, "rdml.zip.misnamed")
            return None
        if probe.kind == "text":
            text = "\n".join(probe.head[:20]).lstrip("﻿").lstrip()
            if text.startswith("<") and "<rdml" in text[:2000]:
                return Sniff(95, "rdml.xml")
        return None

    def load(self, path: Path):  # -> rdml.Rdml
        """The document, through ``rdml_io.load`` (size caps, hardened parser, migration).

        Raises:
            CaptureError: The file is not loadable, safe, valid RDML.
        """
        try:
            return rdml_io.load(path)
        except rdml_io.RdmlLoadError as err:
            raise CaptureError(str(err)) from err

    def read(self, sources: list[Source]) -> list[PlateData]:
        """The plates of one RDML file (every experiment)."""
        if len(sources) != 1:
            raise CaptureError("import one RDML file at a time (it can hold many plates)")
        source = sources[0]
        doc = self.load(source.path)
        plates = plates_from_document(doc, source.path.name)
        if plates:  # what the loader repaired to read the file, said once
            plates[0].notes.extend(rdml_io.load_notes(doc).notes)
        return plates


def _text(element, tag: str) -> str:
    child = element.find(f"{NS}{tag}")
    return (child.text or "").strip() if child is not None and child.text else ""


def _id(element, tag: str) -> str:
    child = element.find(f"{NS}{tag}")
    return child.get("id", "") if child is not None else ""


def plates_from_document(doc, file_name: str = "") -> list[PlateData]:
    """Every run of every experiment of an RDML document as :class:`PlateData`.

    Sample types come from the document's ``sample/type`` elements (per target where given);
    the vendor Cq from ``data/cq``; curves from ``adp``/``mdp``. Run ids are
    ``<run>`` (or ``<experiment>/<run>`` when two experiments share a run id).
    """
    root = doc._node
    sample_types: dict[str, dict[str, str]] = {}
    sample_quantity: dict[str, dict[str, float]] = {}
    for sample in root.findall(f"{NS}sample"):
        sid = sample.get("id", "")
        types: dict[str, str] = {}
        for element in sample.findall(f"{NS}type"):
            types[element.get("targetId", "")] = (element.text or "unkn").strip()
        sample_types[sid] = types
        quantities: dict[str, float] = {}
        for element in sample.findall(f"{NS}quantity"):
            value = number(_text(element, "value"))
            if value is not None:
                quantities[element.get("targetId", "")] = value
        sample_quantity[sid] = quantities
    target_dye = {t.get("id", ""): _id(t, "dyeId") for t in root.findall(f"{NS}target")}

    runs = [
        (experiment.get("id", ""), run)
        for experiment in root.findall(f"{NS}experiment")
        for run in experiment.findall(f"{NS}run")
    ]
    counts: dict[str, int] = {}
    for _, run in runs:
        counts[run.get("id", "")] = counts.get(run.get("id", ""), 0) + 1
    plates = []
    for experiment_id, run in runs:
        run_id = run.get("id", "")
        name = f"{experiment_id}/{run_id}" if counts[run_id] > 1 else run_id
        fmt = run.find(f"{NS}pcrFormat")
        rows = int(number(_text(fmt, "rows")) or 0) if fmt is not None else 0
        columns = int(number(_text(fmt, "columns")) or 0) if fmt is not None else 0
        plate = PlateData(run_id=name, rows=rows, columns=columns, value_kind="fluorescence")
        plate.sources.append((file_name, "plate"))
        width = columns if columns > 0 else 12
        for react in run.findall(f"{NS}react"):
            try:
                position = int(react.get("id", "0"))
            except ValueError as err:
                raise CaptureError(f"run {run_id}: a reaction id is not a number") from err
            if position < 1:
                raise CaptureError(f"run {run_id}: a reaction id below 1")
            row, column = (position - 1) // width + 1, (position - 1) % width + 1
            sample = _id(react, "sample")
            for data in react.findall(f"{NS}data"):
                target = _id(data, "tar")
                types = sample_types.get(sample, {})
                quantities = sample_quantity.get(sample, {})
                plate.reactions.append(
                    Reaction(
                        well=well_name(row, column),
                        row=row,
                        column=column,
                        sample=sample,
                        target=target,
                        dye=target_dye.get(target, ""),
                        sample_type=types.get(target, types.get("", "unkn")),
                        cq=_cq(data),
                        quantity=quantities.get(target, quantities.get("")),
                        omitted=bool(_text(data, "excl")),
                        amp=_curve(data, "adp", "cyc"),
                        melt=_curve(data, "mdp", "tmp"),
                    )
                )
        plates.append(plate)
    return plates


def _cq(data) -> float | None:
    value = number(_text(data, "cq"))
    return value if value is not None and value > 0 else None


def _curve(data, tag: str, x_tag: str) -> Curve | None:
    points = []
    for point in data.findall(f"{NS}{tag}"):
        x = number(_text(point, x_tag))
        y = number(_text(point, "fluor"))
        if x is not None and y is not None:
            points.append((x, y))
    if not points:
        return None
    points.sort()
    return Curve(x=tuple(p[0] for p in points), y=tuple(p[1] for p in points))


CONNECTOR = RdmlConnector()

__all__ = ["CONNECTOR", "RdmlConnector", "plates_from_document"]
