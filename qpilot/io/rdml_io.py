"""Load RDML files safely: the only place in qPilot that opens an instrument export.

RDML is the open XML exchange format that QuantStudio, CFX Maestro and LightCycler software
can export. Files may come from a collaborator or a shared instrument PC, so they are treated
as untrusted:

* size caps run *before* parsing (a zipped ``rdml_data.xml`` or a plain XML file must be at
  most ``MAX_XML_BYTES`` uncompressed, and a zip may not inflate more than ``MAX_ZIP_RATIO``
  times), which stops decompression bombs;
* lxml's default parser is replaced, on every call, by one with entity resolution and network
  access switched off. The vendored ``rdml.py`` parses with ``etree.fromstring`` and no parser
  argument, so this hardens it without editing the vendored file. lxml keeps the default parser
  per thread, which is why it is set inside :func:`load` rather than once at import.

Upstream rdmlpython additionally strips ``<!ENTITY>`` declarations before parsing; qPilot relies
on both layers. A connector for another file format is any function ``path -> rdml.Rdml``
registered in :data:`CONNECTORS` (see ``qpilot/io/README.md``).
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path

from lxml import etree

from qpilot.vendor.rdmlpython import rdml

MAX_XML_BYTES = 1 << 30  # 1 GiB of uncompressed XML
MAX_ZIP_RATIO = 100  # real exports inflate about 9-11x
RDML_MEMBER = "rdml_data.xml"
LATEST_VERSION = "1.4"

_MIGRATIONS: dict[str, tuple[str, str]] = {
    "1.0": ("migrate_version_1_0_to_1_1", "1.1"),
    "1.1": ("migrate_version_1_1_to_1_2", "1.2"),
    "1.2": ("migrate_version_1_2_to_1_3", "1.3"),
    "1.3": ("migrate_version_1_3_to_1_4", "1.4"),
}


class RdmlLoadError(Exception):
    """The file is not a loadable, safe, valid RDML file."""


def hardened_parser() -> etree.XMLParser:
    """Return an lxml parser that never resolves entities or touches the network."""
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
        load_dtd=False,
    )


def _check_size(path: Path) -> None:
    """Refuse oversized or suspiciously compressed inputs before any XML is parsed."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            try:
                info = archive.getinfo(RDML_MEMBER)
            except KeyError as err:
                raise RdmlLoadError(
                    f"{path.name}: no {RDML_MEMBER} inside the RDML archive"
                ) from err
        if info.file_size > MAX_XML_BYTES:
            raise RdmlLoadError(f"{path.name}: input too large ({info.file_size} bytes of XML)")
        if info.compress_size and info.file_size / info.compress_size > MAX_ZIP_RATIO:
            raise RdmlLoadError(
                f"{path.name}: input too large (compression ratio above {MAX_ZIP_RATIO}:1)"
            )
    elif path.stat().st_size > MAX_XML_BYTES:
        raise RdmlLoadError(f"{path.name}: input too large ({path.stat().st_size} bytes)")


def _migrate_to_latest(doc: rdml.Rdml) -> None:
    """Upgrade an older RDML document in memory, one version at a time, to RDML 1.4."""
    version = doc.version()
    while version != LATEST_VERSION:
        if version not in _MIGRATIONS:
            raise RdmlLoadError(f"unsupported RDML version {version!r}")
        method, version = _MIGRATIONS[version]
        getattr(doc, method)()


def load(path: str | Path, *, migrate: bool = True, validate: bool = True) -> rdml.Rdml:
    """Open an RDML file safely and return the vendored rdmlpython document.

    Args:
        path: An ``.rdml`` file (zipped, as instruments export it) or a plain RDML XML file.
        migrate: Upgrade older RDML versions to 1.4 in memory, as LinRegPCR expects.
        validate: Check the document against the RDML schema (about 2 s for 64 plates).

    Returns:
        The loaded ``rdml.Rdml`` document.

    Raises:
        RdmlLoadError: The file is missing, too large, not RDML, of an unsupported version,
            or fails schema validation.
    """
    file = Path(path)
    if not file.is_file():
        raise RdmlLoadError(f"not a file: {file}")
    _check_size(file)
    etree.set_default_parser(hardened_parser())
    try:
        doc = rdml.Rdml(str(file))
    except rdml.RdmlError as err:
        raise RdmlLoadError(f"{file.name}: {err}") from err
    except (UnicodeDecodeError, zipfile.BadZipFile, etree.XMLSyntaxError) as err:
        raise RdmlLoadError(f"{file.name}: not a valid RDML or XML file ({err})") from err
    if migrate:
        _migrate_to_latest(doc)
    if validate and not doc.isvalid():
        failures = [line for line in doc.validate().splitlines() if "\tFalse\t" in line]
        raise RdmlLoadError(f"{file.name}: fails the RDML schema: {'; '.join(failures[:3])}")
    return doc


def runs(doc: rdml.Rdml, experiment_id: str | None = None) -> list:
    """Return the runs (plates) of one experiment, or of every experiment when no id is given.

    Raises:
        RdmlLoadError: ``experiment_id`` is not in the document.
    """
    experiments = doc.experiments()
    if experiment_id is None:
        return [run for experiment in experiments for run in experiment.runs()]
    for experiment in experiments:
        if experiment["id"] == experiment_id:
            return list(experiment.runs())
    known = ", ".join(experiment["id"] for experiment in experiments)
    raise RdmlLoadError(f"no experiment {experiment_id!r} (found: {known})")


#: File-format connectors: suffix -> function returning an ``rdml.Rdml``. Add new formats here.
CONNECTORS: dict[str, Callable[[str | Path], rdml.Rdml]] = {".rdml": load, ".xml": load}
