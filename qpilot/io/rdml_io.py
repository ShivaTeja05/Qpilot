"""Load RDML files safely: the only place in qPilot that opens an instrument export.

RDML is the open XML exchange format that QuantStudio, CFX Maestro and LightCycler software
can export. Files may come from a collaborator or a shared instrument PC, so they are treated
as untrusted:

* size caps run *before* parsing (the archive's RDML member or a plain XML file must be at most
  ``MAX_XML_BYTES`` uncompressed, and a zip member may not inflate more than ``MAX_ZIP_RATIO``
  times), which stops decompression bombs; the member is read in chunks and never past the cap;
* lxml's default parser is replaced, on every call, by one with entity resolution and network
  access switched off. The vendored ``rdml.py`` parses with ``etree.fromstring`` and no parser
  argument, so this hardens it without editing the vendored file. lxml keeps the default parser
  per thread, which is why it is set inside :func:`load` rather than once at import.

Upstream rdmlpython additionally strips ``<!ENTITY>`` declarations before parsing; qPilot relies
on both layers. A connector for another file format is any function ``path -> rdml.Rdml``
registered in :data:`CONNECTORS` (see ``qpilot/io/README.md``).

**What real files need** (``tests/fixtures/corpus/rdml``). Each repair below runs only when its
defect is present, changes no measured value, and is said in :attr:`LoadNotes.notes` (kept on
the document as ``doc.qpilot_notes``), so a clean RDML 1.4 file (the demo) is read exactly as
before:

* an archive whose one XML member is not named ``rdml_data.xml`` (CFX Manager 3.0 names it
  after the file) is read from that member; several XML members and none named so is refused;
* rdmlpython's upgrade to RDML 1.4 writes the elements it adds (``dye``, ``pcrFormat``,
  ``Ncopy``) without the RDML namespace, so the upgraded file fails the schema: they are put in it;
* RDML 1.0 named wells ``A1``, ``B12``; when the upgrade leaves them so (a "free format" plate),
  they are numbered as RDML 1.1 and later number them, on the smallest standard plate holding
  them, so every well keeps its name;
* elements out of the schema's order are put in its order (same-named elements keep theirs);
* LightCycler 96 names each sample by an opaque id (a GUID) and writes the name typed in the
  software as its ``<description>``, and names a target ``<dye>@<target>``: the sample takes its
  description and the target its own name (its dye is still the target's ``dyeId``), unless two
  would then share one name. The file's own ids stay in :attr:`LoadNotes.renamed`.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import zipfile
import zlib
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from lxml import etree

from qpilot.vendor.rdmlpython import rdml

MAX_XML_BYTES = 1 << 30  # 1 GiB of uncompressed XML
MAX_ZIP_RATIO = 100  # real exports inflate about 9-11x
RDML_MEMBER = "rdml_data.xml"
LATEST_VERSION = "1.4"
NS = "{http://www.rdml.org}"
SCHEMA_14 = Path(rdml.__file__).resolve().parent / "schema" / "RDML_v1_4_CR.xsd"
_CHUNK = 1 << 20

_MIGRATIONS: dict[str, tuple[str, str]] = {
    "1.0": ("migrate_version_1_0_to_1_1", "1.1"),
    "1.1": ("migrate_version_1_1_to_1_2", "1.2"),
    "1.2": ("migrate_version_1_2_to_1_3", "1.3"),
    "1.3": ("migrate_version_1_3_to_1_4", "1.4"),
}

#: An opaque id: a GUID (``1c76448f-03d2-453f-8628-d764e1ca1d55``, braces allowed).
OPAQUE_ID = re.compile(
    r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$"
)
_WELL_LABEL = re.compile(r"^([A-Za-z]{1,2})0*([1-9][0-9]{0,2})$")
#: Standard plates (rows, columns), smallest first: a "free format" RDML 1.0 plate is numbered
#: on the first that holds every well it names.
STANDARD_PLATES = ((6, 8), (8, 12), (16, 24), (32, 48))


class RdmlLoadError(Exception):
    """The file is not a loadable, safe, valid RDML file.

    ``kind`` says which refusal it is, so the page can say it in plain words:
    ``missing``, ``too_large``, ``compression``, ``damaged``, ``no_member``, ``ambiguous``,
    ``not_rdml``, ``entities``, ``version`` or ``schema``.
    """

    def __init__(self, message: str, kind: str = "not_rdml") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class LoadNotes:
    """What :func:`load` repaired in a file to read it (empty for a clean RDML 1.4 file).

    Attributes:
        member: The archive member read (``""`` for a plain XML file).
        version: The RDML version the file was written in.
        notes: One plain sentence per repair or upgrade step, for the person.
        renamed: ``{"sample": {file id: name}, "target": {file id: name}}`` for names taken
            from elsewhere in the file (see the module docstring).
    """

    member: str = ""
    version: str = ""
    notes: list[str] = field(default_factory=list)
    renamed: dict[str, dict[str, str]] = field(default_factory=dict)


def hardened_parser() -> etree.XMLParser:
    """Return an lxml parser that never resolves entities or touches the network."""
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
        load_dtd=False,
    )


# ---------------------------------------------------------------------------------------------
# The bytes: which member, how large
# ---------------------------------------------------------------------------------------------


def rdml_member(infos: Iterable[zipfile.ZipInfo], name: str) -> zipfile.ZipInfo:
    """The RDML data of an archive: ``rdml_data.xml``, else its only XML member.

    Raises:
        RdmlLoadError: No XML member, or several and none named ``rdml_data.xml``.
    """
    files = [info for info in infos if not info.is_dir()]
    for info in files:
        if info.filename == RDML_MEMBER:
            return info
    xml = [info for info in files if info.filename.lower().endswith(".xml")]
    if len(xml) == 1:
        return xml[0]
    if not xml:
        raise RdmlLoadError(
            f"{name}: no {RDML_MEMBER} inside the RDML archive (it holds no XML file)", "no_member"
        )
    raise RdmlLoadError(
        f"{name}: the archive holds {len(xml)} XML files and none is named {RDML_MEMBER}, so "
        "qPilot cannot tell which one is the RDML data",
        "ambiguous",
    )


def _check_member(info: zipfile.ZipInfo, name: str) -> None:
    if info.file_size > MAX_XML_BYTES:
        raise RdmlLoadError(f"{name}: input too large ({info.file_size} bytes of XML)", "too_large")
    if info.compress_size and info.file_size / info.compress_size > MAX_ZIP_RATIO:
        raise RdmlLoadError(
            f"{name}: input too large (compression ratio above {MAX_ZIP_RATIO}:1)", "compression"
        )
    if not info.compress_size and info.file_size > 1024:
        raise RdmlLoadError(
            f"{name}: input too large (compression ratio above {MAX_ZIP_RATIO}:1)", "compression"
        )


def _open_zip(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as err:
        raise RdmlLoadError(f"{path.name}: a damaged zip archive ({err})", "damaged") from err


def _check_size(path: Path) -> None:
    """Refuse oversized or suspiciously compressed inputs before any XML is parsed."""
    if zipfile.is_zipfile(path):
        with _open_zip(path) as archive:
            _check_member(rdml_member(archive.infolist(), path.name), path.name)
    elif path.stat().st_size > MAX_XML_BYTES:
        raise RdmlLoadError(
            f"{path.name}: input too large ({path.stat().st_size} bytes)", "too_large"
        )


def _read_capped(stream, name: str, limit: int | None = None) -> bytes:
    """Every byte of ``stream``, refusing more than ``limit`` (default :data:`MAX_XML_BYTES`)."""
    cap = MAX_XML_BYTES if limit is None else limit
    parts: list[bytes] = []
    size = 0
    while chunk := stream.read(_CHUNK):
        size += len(chunk)
        if size > cap:
            raise RdmlLoadError(f"{name}: input too large (over {cap} bytes of XML)", "too_large")
        parts.append(chunk)
    return b"".join(parts)


def read_xml(path: Path) -> tuple[bytes, str]:
    """The RDML XML of a file (zipped or plain) and the member it came from (``""``: plain).

    Raises:
        RdmlLoadError: Too large, a bomb, a damaged archive, or no RDML member.
    """
    if zipfile.is_zipfile(path):
        with _open_zip(path) as archive:
            info = rdml_member(archive.infolist(), path.name)
            _check_member(info, path.name)
            try:
                with archive.open(info) as member:
                    # never more than the member says it holds (a lying header is a bomb)
                    data = _read_capped(member, path.name, info.file_size)
            except (zipfile.BadZipFile, zlib.error, EOFError, OSError, ValueError) as err:
                raise RdmlLoadError(
                    f"{path.name}: a damaged zip archive ({err})", "damaged"
                ) from err
        return data, info.filename
    if path.stat().st_size > MAX_XML_BYTES:
        raise RdmlLoadError(
            f"{path.name}: input too large ({path.stat().st_size} bytes)", "too_large"
        )
    with path.open("rb") as handle:
        return _read_capped(handle, path.name), ""


# ---------------------------------------------------------------------------------------------
# Upgrade and repairs (each only when its defect is there)
# ---------------------------------------------------------------------------------------------


def _migrate_to_latest(doc: rdml.Rdml) -> list[str]:
    """Upgrade an older RDML document in memory, one version at a time, to RDML 1.4.

    Returns:
        What rdmlpython's upgrade steps say they changed (``"Migration to v1.1 deleted ..."``).
    """
    said: list[str] = []
    version = doc.version()
    while version != LATEST_VERSION:
        if version not in _MIGRATIONS:
            raise RdmlLoadError(f"unsupported RDML version {version!r}", "version")
        method, version = _MIGRATIONS[version]
        said.extend(str(hint) for hint in (getattr(doc, method)() or []) if hint)
    return said


def _namespace_slips(root: etree._Element) -> list[str]:
    """Put elements written without the RDML namespace into it; their names, once each."""
    slipped: list[str] = []
    for element in root.iter():
        tag = element.tag
        if isinstance(tag, str) and not tag.startswith("{"):
            element.tag = NS + tag
            if tag not in slipped:
                slipped.append(tag)
    return slipped


def _child(element: etree._Element, tag: str) -> etree._Element | None:
    return element.find(NS + tag)


def _text(element: etree._Element, tag: str) -> str:
    child = _child(element, tag)
    return (child.text or "").strip() if child is not None else ""


def _label_position(label: str) -> tuple[int, int] | None:
    match = _WELL_LABEL.match(label.strip())
    if match is None:
        return None
    row = 0
    for letter in match.group(1).upper():
        row = row * 26 + ord(letter) - ord("A") + 1
    return row, int(match.group(2))


def _number_labelled_wells(root: etree._Element) -> list[str]:
    """Number the reactions of runs that name their wells (RDML 1.0 ``A1``): what changed."""
    changed: list[str] = []
    for run in root.iter(NS + "run"):
        reacts = run.findall(NS + "react")
        ids = [react.get("id", "") for react in reacts]
        if not reacts or all(i.isdigit() for i in ids):
            continue
        positions = [_label_position(i) for i in ids]
        if any(p is None for p in positions) or len(set(ids)) != len(ids):
            continue  # not well names: the schema check says so
        rows_needed = max(p[0] for p in positions if p)
        columns_needed = max(p[1] for p in positions if p)
        fmt = _child(run, "pcrFormat")
        declared = (0, 0)
        if fmt is not None:
            try:
                declared = (int(_text(fmt, "rows")), int(_text(fmt, "columns")))
            except ValueError:
                declared = (0, 0)
        if declared[0] >= rows_needed and declared[1] >= columns_needed:
            rows, columns = declared
        else:
            plate = next(
                (p for p in STANDARD_PLATES if p[0] >= rows_needed and p[1] >= columns_needed),
                None,
            )
            if plate is None:
                continue
            rows, columns = plate
        if fmt is None:
            continue  # rdmlpython's upgrade always writes one; without it, leave the file be
        for tag, value in (("rows", rows), ("columns", columns)):
            element = _child(fmt, tag)
            if element is not None:
                element.text = str(value)
        for tag in ("rowLabel", "columnLabel"):
            element = _child(fmt, tag)
            if element is not None:
                element.text = "ABC" if tag == "rowLabel" else "123"
        for react, (row, column) in zip(reacts, positions, strict=True):  # type: ignore[misc]
            react.set("id", str((row - 1) * columns + column))
        changed.append(f"{rows * columns}-well plate ({rows} x {columns})")
    return changed


@cache
def _schema_order() -> tuple[dict[str, dict[str, int]], dict[str, dict[str, str]]]:
    """From the RDML 1.4 schema: each content model's child order and each child's model.

    A content model is a named complex type (``"sampleType"``), ``"element:rdml"`` for the
    root or ``"<parent model>/<name>"`` for an inline one. Children of an ``xs:choice`` or
    ``xs:all`` share one position (any order).
    """
    xs = "{http://www.w3.org/2001/XMLSchema}"
    tree = etree.parse(str(SCHEMA_14), hardened_parser())
    order: dict[str, dict[str, int]] = {}
    child_model: dict[str, dict[str, str]] = {}

    def model_of(declaration: etree._Element, parent: str) -> str | None:
        kind = declaration.get("type", "")
        if kind.startswith("rdml:"):
            return kind.split(":", 1)[1]
        if declaration.find(xs + "complexType") is not None:  # an inline type, named by place
            return f"{parent}/{declaration.get('name')}"
        return None

    def collect(node: etree._Element, key: str, position: list[int], shared: bool) -> None:
        for child in node:
            if not isinstance(child.tag, str):
                continue
            local = child.tag.replace(xs, "")
            if local == "element" and child.get("name"):
                name = child.get("name") or ""
                order[key].setdefault(name, position[0])
                if not shared:
                    position[0] += 1
                found = model_of(child, key)
                if found is not None:
                    child_model[key].setdefault(name, found)
                    if "/" in found:
                        build(found, child.find(xs + "complexType"))
            elif local in ("sequence",):
                collect(child, key, position, shared)
            elif local in ("choice", "all"):
                collect(child, key, position, True)
                position[0] += 1

    def build(key: str, complex_type: etree._Element | None) -> None:
        if key in order or complex_type is None:
            return
        order[key] = {}
        child_model[key] = {}
        collect(complex_type, key, [0], False)

    root = tree.getroot()
    for complex_type in root.findall(xs + "complexType"):
        build(complex_type.get("name") or "", complex_type)
    for element in root.findall(xs + "element"):
        name = element.get("name") or ""
        build(f"element:{name}", element.find(xs + "complexType"))
    return order, child_model


def _schema_names() -> frozenset[str]:
    """Every element name the RDML 1.4 schema declares."""
    order, _ = _schema_order()
    return frozenset(name for positions in order.values() for name in positions)


def _reorder(root: etree._Element) -> int:
    """Put children in the schema's order (same-named ones keep theirs); elements reordered."""
    order, child_model = _schema_order()
    moved = 0
    stack: list[tuple[etree._Element, str]] = [(root, "element:rdml")]
    while stack:
        element, model = stack.pop()
        positions = order.get(model)
        if positions is None:
            continue
        children = list(element)
        named = [c for c in children if isinstance(c.tag, str)]
        locals_ = [c.tag.replace(NS, "") for c in named]
        known = len(named) == len(children) and all(n in positions for n in locals_)
        if known:
            ranked = sorted(range(len(named)), key=lambda i: positions[locals_[i]])
            if ranked != list(range(len(named))):
                tails = [c.tail for c in named]
                for c in named:
                    element.remove(c)
                for index, i in enumerate(ranked):
                    named[i].tail = tails[index]
                    element.append(named[i])
                moved += 1
        for child, name in zip(named, locals_, strict=True):
            sub = child_model.get(model, {}).get(name)
            if sub is not None:
                stack.append((child, sub))
    return moved


def _schema_problem(doc: rdml.Rdml) -> tuple[int, str]:
    """How many schema errors the document has and the element of the first, in words."""
    failures = [line for line in doc.validate().splitlines() if "\tFalse\t" in line]
    errors = [line for line in failures if "validation error" in line]
    where = ""
    for line in errors:
        match = re.search(r"Element '(?:\{[^}]*\})?([A-Za-z]+)'", line)
        if match:
            where = match.group(1)
            break
    return len(errors) or len(failures), where


# ---------------------------------------------------------------------------------------------
# Names (LightCycler 96)
# ---------------------------------------------------------------------------------------------


def _engine_name(name: str) -> str:
    """The name the engine will use (:func:`qpilot.qpcr.curves.safe_name`, quietly)."""
    from qpilot.qpcr.curves import _SAFE_NAME, slug

    return name if _SAFE_NAME.match(name) else (slug(name)[:64] or "unnamed")


def name_repairs(root: etree._Element) -> dict[str, dict[str, str]]:
    """Which samples and targets take a name from elsewhere in the file (see module docstring).

    Only the declarations are read (``<sample>`` and ``<target>`` under the root), so this works
    on a whole document or on its head alone. A name that would be shared, or would equal another
    sample's or target's id, is not taken: two samples are never merged into one.
    """
    out: dict[str, dict[str, str]] = {}
    samples = [(s.get("id", ""), _text(s, "description")) for s in root.findall(NS + "sample")]
    proposed = {sid: text for sid, text in samples if OPAQUE_ID.match(sid) and text}
    out["sample"] = _unique(proposed, [sid for sid, _ in samples])
    dyes = {d.get("id", "") for d in root.findall(NS + "dye")}
    targets: dict[str, str] = {}
    ids: list[str] = []
    for target in root.findall(NS + "target"):
        tid = target.get("id", "")
        ids.append(tid)
        own = _child(target, "dyeId")
        dye_id = (own.get("id") or own.text or "").strip() if own is not None else ""
        dye, at, name = tid.partition("@")
        if not at or not name.strip() or not dye or dye not in ({dye_id} | dyes):
            continue
        name = name.strip()
        # LightCycler 96 names the target of its "no target present" wells by an opaque id
        targets[tid] = f"no target ({dye})" if OPAQUE_ID.match(name) else name
    out["target"] = _unique(targets, ids)
    return {kind: names for kind, names in out.items() if names}


def _unique(proposed: dict[str, str], ids: list[str]) -> dict[str, str]:
    """``proposed`` without the names two items would then share (as the engine names them)."""
    accepted = dict(proposed)
    while True:
        final = {i: _engine_name(accepted.get(i, i)) for i in ids}
        counts = Counter(final.values())
        clash = [i for i in accepted if counts[final[i]] > 1]
        if not clash:
            break
        for i in clash:
            del accepted[i]
    return {i: name for i, name in accepted.items() if name != i}


def _apply_names(root: etree._Element, renamed: dict[str, dict[str, str]]) -> None:
    samples = renamed.get("sample", {})
    targets = renamed.get("target", {})
    for sample in root.findall(NS + "sample"):
        if sample.get("id") in samples:
            sample.set("id", samples[sample.get("id", "")])
    for target in root.findall(NS + "target"):
        if target.get("id") in targets:
            target.set("id", targets[target.get("id", "")])
    for react in root.iter(NS + "react"):
        ref = _child(react, "sample")
        if ref is not None and ref.get("id") in samples:
            ref.set("id", samples[ref.get("id", "")])
        for tar in react.iter(NS + "tar"):
            if tar.get("id") in targets:
                tar.set("id", targets[tar.get("id", "")])
    for element in root.iter():  # sample <type targetId> / <quantity targetId> (RDML 1.3+)
        if isinstance(element.tag, str) and element.get("targetId") in targets:
            element.set("targetId", targets[element.get("targetId", "")])


def _has_partitions(path: Path) -> bool:
    if not zipfile.is_zipfile(path):
        return False
    with _open_zip(path) as archive:
        return any(n.startswith("partitions/") for n in archive.namelist())


_KEYS_LOCK = threading.Lock()
_KEYS: OrderedDict[tuple[str, int, int], str] = OrderedDict()


def names_key(path: str | Path) -> str:
    """A short key of the names :func:`load` takes from elsewhere in this file (``""``: none).

    Read from the file's declarations only (everything before the first ``<experiment>``), so
    a large clean file costs a few milliseconds; remembered per file path, size and time. The
    curve cache adds it to its key, so a table cached before the names were taken is not reused.
    """
    file = Path(path)
    stat = file.stat()
    memo = (str(file.resolve()), stat.st_size, stat.st_mtime_ns)
    with _KEYS_LOCK:
        if memo in _KEYS:
            return _KEYS[memo]
    try:
        root = _declarations(file)
        renamed = {} if root is None or _has_partitions(file) else name_repairs(root)
    except etree.XMLSyntaxError:  # an unusual head: read the whole file once
        try:
            renamed = load_notes(load(file, validate=False)).renamed
        except RdmlLoadError:
            renamed = {}
    except (RdmlLoadError, OSError, ValueError, EOFError, zlib.error, zipfile.BadZipFile):
        renamed = {}
    key = ""
    if renamed:
        payload = json.dumps(renamed, sort_keys=True).encode()
        key = hashlib.sha256(payload).hexdigest()[:12]
    with _KEYS_LOCK:
        _KEYS[memo] = key
        while len(_KEYS) > 64:
            _KEYS.popitem(last=False)
    return key


_EXPERIMENT = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?experiment[\s>/]")
_ROOT = re.compile(rb"<((?:[A-Za-z_][\w.-]*:)?rdml)[\s>]")


def _declarations(path: Path) -> etree._Element | None:
    """The file's root with its declarations (samples, targets, dyes), without its runs."""
    head = b""
    if zipfile.is_zipfile(path):
        with _open_zip(path) as archive:
            info = rdml_member(archive.infolist(), path.name)
            _check_member(info, path.name)
            with archive.open(info) as member:
                head = _head(member)
    else:
        with path.open("rb") as handle:
            head = _head(handle)
    found = _EXPERIMENT.search(head)
    root_tag = _ROOT.search(head)
    if root_tag is None:
        return None
    text = head[: found.start()] if found else head
    if found is None and b"</" + root_tag.group(1) + b">" in text:
        pass  # the whole (small) file
    else:
        text += b"</" + root_tag.group(1) + b">"
    text = re.sub(rb"<!DOCTYPE[^>]*>", b"", text)
    return etree.fromstring(text, hardened_parser())


def _head(stream) -> bytes:
    """Bytes up to the first ``<experiment`` (at most 64 MB)."""
    parts: list[bytes] = []
    size = 0
    tail = b""
    while chunk := stream.read(_CHUNK):
        parts.append(chunk)
        size += len(chunk)
        if _EXPERIMENT.search(tail + chunk) or size > 64 * _CHUNK:
            break
        tail = chunk[-64:]
    return b"".join(parts)


# ---------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------


def load(path: str | Path, *, migrate: bool = True, validate: bool = True) -> rdml.Rdml:
    """Open an RDML file safely and return the vendored rdmlpython document.

    Args:
        path: An RDML file (zipped, as instruments export it, any suffix) or plain RDML XML.
        migrate: Upgrade older RDML versions to 1.4 in memory, as LinRegPCR expects.
        validate: Check the document against the RDML schema (about 2 s for 64 plates).

    Returns:
        The loaded ``rdml.Rdml`` document; what was repaired to read it is
        ``doc.qpilot_notes`` (a :class:`LoadNotes`).

    Raises:
        RdmlLoadError: The file is missing, too large, not RDML, of an unsupported version,
            or fails schema validation (after the repairs in the module docstring).
    """
    file = Path(path)
    if not file.is_file():
        raise RdmlLoadError(f"not a file: {file}", "missing")
    data, member = read_xml(file)
    notes = LoadNotes(member=member)
    if member and member != RDML_MEMBER:  # the member's name is file text: never said
        notes.notes.append(
            f"The RDML data in this archive is not named {RDML_MEMBER}; qPilot read the "
            "archive's one XML file."
        )
    etree.set_default_parser(hardened_parser())
    doc = rdml.Rdml()
    try:
        doc.loadXMLString(data.decode("utf-8"))
    except UnicodeDecodeError as err:
        raise RdmlLoadError(f"{file.name}: not a valid RDML or XML file ({err})") from err
    except rdml.RdmlError as err:
        raise RdmlLoadError(f"{file.name}: {err}", _load_kind(str(err))) from err
    except etree.XMLSyntaxError as err:
        raise RdmlLoadError(f"{file.name}: not a valid RDML or XML file ({err})") from err
    if member:
        doc._rdmlFilename = str(file)  # rdmlpython reads digital PCR partitions from the archive
    notes.version = doc.version()
    root = doc._node
    migrated = migrate and notes.version != LATEST_VERSION
    slipped: list[str] = []
    plates: list[str] = []
    if migrated:
        upgrade = _migrate_to_latest(doc)
        notes.notes.append(
            f"The file is RDML {notes.version}; qPilot upgraded it to RDML {LATEST_VERSION} in "
            "memory to read it (the file itself is not changed)."
        )
        notes.notes.extend(f"The upgrade says: {line}" for line in upgrade)  # fixed sentences
        slipped = _namespace_slips(root)  # rdmlpython's upgrade writes its elements bare
    if notes.version == "1.0":
        plates = _number_labelled_wells(root)
    moved = 0
    if validate and not doc.isvalid():
        # a file that fails as it is: the same repairs on a file that was not upgraded, then order
        repaired = False
        if not migrated:
            slipped = _namespace_slips(root)
            repaired = bool(slipped)
        if notes.version != "1.0":
            plates = _number_labelled_wells(root)
            repaired = repaired or bool(plates)
        moved = _reorder(root) if doc.version() == LATEST_VERSION else 0
        if not (repaired or moved) or not doc.isvalid():
            count, where = _schema_problem(doc)
            at = f" at a <{where}> element" if where else ""
            raise RdmlLoadError(
                f"{file.name}: fails the RDML schema: the file does not follow the RDML "
                f"standard{at} ({count} problem{'s' if count != 1 else ''})",
                "schema",
            )
    if slipped:
        known = _schema_names()  # element names are file text: only RDML's own are said
        said = [name for name in slipped if name in known][:6]
        notes.notes.append(
            "Some elements were written outside the RDML namespace"
            + (f" ({', '.join(said)})" if said else "")
            + "; qPilot put them in it. No value changed."
        )
    if plates:
        notes.notes.append(
            "The file names its wells A1, A2 ... as RDML 1.0 did; qPilot numbered them as "
            f"RDML 1.1 and later do, on a {plates[0]}, so every well keeps its name."
        )
    if moved:
        notes.notes.append(
            f"In {moved} place{'s' if moved != 1 else ''} the file lists elements out of the "
            "order the RDML standard sets; qPilot put them in order. No value changed."
        )
    renamed = {} if _has_partitions(file) else name_repairs(root)
    if renamed:
        _apply_names(root, renamed)
        notes.renamed = renamed
        if renamed.get("sample"):
            notes.notes.append(
                f"{len(renamed['sample'])} samples are named by an opaque id in the file; "
                "qPilot uses the sample name written beside it (its description)."
            )
        if renamed.get("target"):
            notes.notes.append(
                f"{len(renamed['target'])} targets are named '<dye>@<target>' in the file; "
                "qPilot uses the target's own name (the dye stays recorded with the target)."
            )
    doc.qpilot_notes = notes  # type: ignore[attr-defined]
    return doc


def _load_kind(message: str) -> str:
    return "version" if "unsupported RDML file version" in message else "not_rdml"


def load_notes(doc: rdml.Rdml) -> LoadNotes:
    """What :func:`load` repaired to read ``doc`` (empty for a document built in memory)."""
    found = getattr(doc, "qpilot_notes", None)
    return found if isinstance(found, LoadNotes) else LoadNotes()


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
