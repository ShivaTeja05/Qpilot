"""What an RDML file says about how the experiment was done (for the MIQE table only).

Streams the record's ``input.rdml`` once with a hardened lxml parser (no entities, no DTD, no
network; the same size caps as :mod:`qpilot.io.rdml_io` before anything is parsed) and keeps
only counts, enumerations and a few short descriptive strings: dyes and their chemistry, targets
with sequences or commercial assays, cross-references, instrument and software, Cq and
background methods, thermal-cycling programmes, reverse-transcription settings, sample types,
reaction volumes and how many reactions carry raw fluorescence. Fluorescence values are skipped.

Every string kept here came from the file, so it is untrusted: the report shows it only as
escaped data. Enumerated fields (sample type, dye chemistry, priming method) are checked against
the RDML schema's values and anything else becomes ``other``.
"""

from __future__ import annotations

import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from qpilot.io.rdml_io import RDML_MEMBER, RdmlLoadError, _check_size

SAMPLE_TYPES = {"unkn", "ntc", "nac", "std", "ntp", "nrt", "pos", "opt"}
DYE_CHEMISTRY = {
    "non-saturating DNA binding dye",
    "saturating DNA binding dye",
    "hybridization probe",
    "hydrolysis probe",
    "labelled forward primer",
    "labelled reverse primer",
    "DNA-zyme probe",
}
PRIMING = {"oligo-dt", "random", "target-specific", "oligo-dt and random", "other"}
OLIGOS = ("forwardPrimer", "reversePrimer", "probe1", "probe2")
MAX_TEXT = 120  # longest descriptive string kept
WATCHED = (
    "rdml",
    "target",
    "dyeChemistry",
    "sample",
    "run",
    "react",
    "thermalCyclingConditions",
)


@dataclass
class RdmlMeta:
    """Counts and short strings read from an RDML file (see the module docstring)."""

    version: str = ""
    n_targets: int = 0
    n_targets_with_primers: int = 0
    n_targets_with_amplicon: int = 0
    n_targets_with_assay: int = 0
    n_targets_with_xref: int = 0
    n_oligo_tags: int = 0
    dye_chemistry: list[str] = field(default_factory=list)
    n_runs: int = 0
    instruments: list[str] = field(default_factory=list)
    software: list[str] = field(default_factory=list)
    cq_methods: list[str] = field(default_factory=list)
    background_methods: list[str] = field(default_factory=list)
    n_cycling_programmes: int = 0
    n_cycling_steps: int = 0
    priming: list[str] = field(default_factory=list)
    dnase: list[bool] = field(default_factory=list)
    sample_types: dict[str, int] = field(default_factory=dict)
    n_template_quantities: int = 0
    n_reactions: int = 0
    n_reactions_with_curves: int = 0
    volumes: list[float] = field(default_factory=list)


def _local(tag: object) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _short(text: str | None) -> str:
    return " ".join((text or "").split())[:MAX_TEXT]


def _real_sequence(text: str | None) -> bool:
    """A sequence with at least one base that is not ``N`` (masked sequences do not count)."""
    seq = (text or "").strip().upper()
    return bool(seq) and any(ch in "ACGTU" for ch in seq)


def _stream(path: Path):
    _check_size(path)
    if zipfile.is_zipfile(path):
        archive = zipfile.ZipFile(path)
        return archive, archive.open(RDML_MEMBER)
    return None, path.open("rb")


def read_meta(path: str | Path) -> RdmlMeta:
    """Read the metadata of an RDML file (plain or zipped).

    Raises:
        RdmlLoadError: Missing, oversized, not RDML or not well-formed XML.
    """
    file = Path(path)
    if not file.is_file():
        raise RdmlLoadError(f"not a file: {file.name}")
    meta = RdmlMeta()
    types: Counter[str] = Counter()
    sets = {"instruments": set(), "software": set(), "cq": set(), "bg": set(), "dye": set()}
    archive, stream = _stream(file)
    try:
        events = etree.iterparse(
            stream,
            events=("end",),
            tag=[f"{{*}}{name}" for name in WATCHED],
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            huge_tree=False,
        )
        for _, elem in events:
            name = _local(elem.tag)
            up = elem.getparent()
            parent = _local(up.tag) if up is not None else ""
            if name == "rdml":
                meta.version = _short(elem.get("version"))
            elif name == "target" and parent == "rdml":
                _target(elem, meta)
            elif name == "dyeChemistry" and parent == "dye":
                text = _short(elem.text)
                sets["dye"].add(text if text in DYE_CHEMISTRY else "other")
            elif name == "sample" and parent == "rdml":
                for child in elem:
                    cname = _local(child.tag)
                    if cname == "type":
                        text = _short(child.text)
                        types[text if text in SAMPLE_TYPES else "other"] += 1
                    elif cname == "templateQuantity":
                        meta.n_template_quantities += 1
                    elif cname == "cdnaSynthesisMethod":
                        _cdna(child, meta)
            elif name == "run":
                meta.n_runs += 1
                _run(elem, sets)
                elem.clear()
            elif name == "react":
                meta.n_reactions += 1
                curves = False
                for child in elem:
                    cname = _local(child.tag)
                    if cname == "vol":
                        try:
                            meta.volumes.append(float(child.text or ""))
                        except ValueError:
                            pass
                    elif cname == "data" and any(_local(d.tag) == "adp" for d in child):
                        curves = True
                meta.n_reactions_with_curves += int(curves)
                elem.clear()
                prev = elem.getprevious()
                while prev is not None and _local(prev.tag) == "react" and up is not None:
                    up.remove(prev)  # free the reactions already counted
                    prev = elem.getprevious()
            elif name == "thermalCyclingConditions" and parent == "rdml":
                meta.n_cycling_programmes += 1
                meta.n_cycling_steps += sum(1 for c in elem if _local(c.tag) == "step")
    except etree.XMLSyntaxError as err:
        raise RdmlLoadError(f"{file.name}: not well-formed XML ({err})") from err
    finally:
        stream.close()
        if archive is not None:
            archive.close()
    meta.sample_types = dict(sorted(types.items()))
    meta.instruments = sorted(sets["instruments"])
    meta.software = sorted(sets["software"])
    meta.cq_methods = sorted(sets["cq"])
    meta.background_methods = sorted(sets["bg"])
    meta.dye_chemistry = sorted(sets["dye"])
    meta.volumes = sorted(set(meta.volumes))
    return meta


def _run(elem: etree._Element, sets: dict[str, set[str]]) -> None:
    for child in elem:
        cname = _local(child.tag)
        if cname == "instrument" and _short(child.text):
            sets["instruments"].add(_short(child.text))
        elif cname == "dataCollectionSoftware":
            label = " ".join(_short(c.text) for c in child if _short(c.text))
            if label:
                sets["software"].add(label[:MAX_TEXT])
        elif cname == "cqDetectionMethod" and _short(child.text):
            sets["cq"].add(_short(child.text))
        elif cname == "backgroundDeterminationMethod" and _short(child.text):
            sets["bg"].add(_short(child.text))


def _target(elem: etree._Element, meta: RdmlMeta) -> None:
    meta.n_targets += 1
    primers = amplicon = assay = xref = False
    for child in elem:
        cname = _local(child.tag)
        if cname == "xRef":
            xref = True
        elif cname == "commercialAssay":
            assay = True
        elif cname == "sequences":
            for seq in child:
                sname = _local(seq.tag)
                text = next((s.text for s in seq if _local(s.tag) == "sequence"), None)
                if sname in OLIGOS and _real_sequence(text):
                    primers = True
                if sname == "amplicon" and _real_sequence(text):
                    amplicon = True
                tags = sum(1 for s in seq if _local(s.tag) in ("threePrimeTag", "fivePrimeTag"))
                meta.n_oligo_tags += tags
    meta.n_targets_with_primers += int(primers)
    meta.n_targets_with_amplicon += int(amplicon)
    meta.n_targets_with_assay += int(assay)
    meta.n_targets_with_xref += int(xref)
    elem.clear()


def _cdna(elem: etree._Element, meta: RdmlMeta) -> None:
    for child in elem:
        cname = _local(child.tag)
        if cname == "primingMethod":
            text = _short(child.text)
            value = text if text in PRIMING else "other"
            if value not in meta.priming:
                meta.priming.append(value)
        elif cname == "dnaseTreatment":
            value = _short(child.text).lower() in ("true", "1")
            if value not in meta.dnase:
                meta.dnase.append(value)
