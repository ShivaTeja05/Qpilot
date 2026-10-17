"""Provenance that travels with the Prism project: ``qpilot_provenance.json`` beside it.

Step 2.3 of the Studio plan. Prism keeps no audit trail ("Prism does not maintain an audit
trail", GraphPad KB 872 [V]) and cannot link a number back to the curves, wells and choices
behind it, so the bundle carries that itself:

* the record ref and the short chain head in every data table's title (and in the project file
  names, see :mod:`qpilot.prism.script`); the Info sheet note reads :data:`INFO_NOTE`;
* ``qpilot_provenance.json``: qPilot's version and the vendored LinRegPCR commit, the study id,
  input sha256, chain head and design hash, every choice with the actor who made it, each
  exported gene's holds fraction and confidence level with its reasons, the conclusion rule,
  every file's sha256 and the bundle sha256;
* ``qpilot_bundle.json``: the :class:`~qpilot.schemas_studio.PrismBundle` itself, which a later
  round trip is compared against. ``bundle_sha256`` is the sha256 of the canonical JSON of the
  bundle without ``bundle_sha256`` (:func:`qpilot.prism.tables.bundle_digest`).

:func:`verify_provenance` re-checks all of it and lists every problem (empty = OK). It does not
complain about files Prism adds later (projects, graphs, ``sent_back/``).

Every caption sentence with a number is built from ``{{fact_id}}`` tokens and passes
:func:`qpilot.core.validator.validate` before it is written; the numbers are the study's facts at
the recommended analysis, so a caption is only numeric when the export used those choices.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from qpilot.core.facts import slug
from qpilot.core.record import versions
from qpilot.core.store import dump_json
from qpilot.core.validator import names_from_result, render_tokens, validate
from qpilot.prism.tables import (
    INFO_NOTE,
    NOT_AFFILIATED,
    PrismExportError,
    bundle_digest,
    write_bytes,
)
from qpilot.qpcr.export import ExportInputs
from qpilot.schemas_studio import PrismBundle

PROVENANCE_FILE = "qpilot_provenance.json"
BUNDLE_FILE = "qpilot_bundle.json"
FORMAT = "qpilot-prism-provenance/1"
MAX_JSON_BYTES = 5 * 1024 * 1024
METHOD_NAMES = frozenset({"log2"})  # the scale's name, not a number from the data

# Step 0.1 of the plan: what only a real Prism seat can confirm. Until then each is [R].
UNVERIFIED: tuple[str, ...] = (
    "Prism version, operating system and default save format of the seat used",
    "that Open <template>.pzt, GoTo, Import <csv>, Save <name>.pzfx works on that version "
    "and the analyses recalculate (and which import options Import applies)",
    "whether ExportTable keeps excluded values, and how they appear in the CSV",
    "whether a script can set Info notes or constants (SetInfo) and table titles (SetSheetTitle)",
    "the launch route on that OS (prism.exe @script on Windows, AppleScript on macOS) and "
    "the done-file pattern",
    "the TableType values Prism writes for Nested and Multiple-variables tables, and how a "
    "CSV fills a nested table's subcolumns",
    "which t test the dialog pre-selects (Welch in the current guide) and whether the "
    "lognormal t tests (Prism 10.5 and later) are present",
)


# ---------------------------------------------------------------------------------------------
# Caption (fact tokens only)
# ---------------------------------------------------------------------------------------------


def caption(inputs: ExportInputs, genes: Sequence[str]) -> dict[str, str]:
    """The figure caption as ``{{fact_id}}`` tokens and rendered, validated.

    Raises:
        PrismExportError: The caption does not pass the validator (a bug, never shipped).
    """
    result = inputs.result
    first, second = inputs.group_order[0], inputs.group_order[1]
    head = (
        f"log2 relative quantities per biological unit, {first} versus {second}, normalised "
        f"to {', '.join(inputs.refs)}; Welch's t test on the log2 scale."
    )
    if result is None or not inputs.at_primary:
        tokens = (
            f"{head} Fold changes and p-values at these choices are shown in qPilot; the "
            "study's facts describe the recommended analysis."
        )
        facts: dict = {} if result is None else result.facts
    else:
        facts = result.facts
        sentences = [head]
        for gene in genes:
            s = slug(gene)
            ids = [
                f"f_fc_{s}_recommended",
                f"f_ci_lo_{s}_recommended",
                f"f_ci_hi_{s}_recommended",
                f"f_p_{s}_recommended",
                f"f_holds_{s}",
                "f_n_cells",
            ]
            if not all(fid in facts for fid in ids):
                sentences.append(f"{gene}: shown in qPilot.")
                continue
            t = ["{{" + fid + "}}" for fid in ids]
            sentences.append(
                f"{gene}: {t[0]} in {first} versus {second} (95 % confidence interval {t[1]} "
                f"to {t[2]}; p = {t[3]}); the conclusion holds in {t[4]} of {t[5]} reasonable "
                "analyses."
            )
        tokens = " ".join(sentences)
    names = set(genes) | set(inputs.refs) | set(inputs.group_order) | METHOD_NAMES
    if result is not None:
        names |= names_from_result(result)
    check = validate(tokens, facts, names)
    if not check.ok:
        raise PrismExportError(f"caption failed the validator: {check.error()}")
    return {"caption_tokens": tokens, "caption": render_tokens(tokens, facts)}


# ---------------------------------------------------------------------------------------------
# Finalising the bundle and the provenance file
# ---------------------------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    """Hex sha256 of bytes."""
    return hashlib.sha256(data).hexdigest()


def finalize(bundle: PrismBundle, out_dir: str | Path, names: Iterable[str]) -> PrismBundle:
    """The bundle with ``files`` = every file written (by relative path) and its sha256.

    ``names`` are paths relative to ``out_dir`` (the CSVs are always included).
    """
    directory = Path(out_dir)
    files = dict(bundle.files)
    for name in [*(t.csv for t in bundle.tables), *names]:
        files[name] = sha256_bytes((directory / name).read_bytes())
    for table in bundle.tables:
        if files[table.csv] != table.csv_sha256:
            raise PrismExportError(f"{table.csv} changed after it was written")
    updated = bundle.model_copy(update={"files": dict(sorted(files.items()))})
    return updated.model_copy(update={"bundle_sha256": bundle_digest(updated)})


def provenance_dict(bundle: PrismBundle, inputs: ExportInputs) -> dict[str, Any]:
    """What ``qpilot_provenance.json`` holds (deterministic: no timestamps)."""
    result = inputs.result
    genes: dict[str, Any] = {}
    for table in bundle.tables:
        entry: dict[str, Any] = {"table": table.name, "csv": table.csv, "layout": table.layout}
        if result is not None and table.gene in result.contrasts:
            contrast = result.contrasts[table.gene]
            grade = result.confidence.get(table.gene)
            robust = result.robustness.get(table.gene)
            entry["recommended_analysis"] = {
                "conclusion": contrast.conclusion,
                "fc": contrast.fc,
                "ci": list(contrast.ci),
                "p": contrast.p,
                "holds": robust.holds if robust else None,
                "n_cells": robust.n_cells if robust else None,
                "level": grade.level if grade else None,
                "reasons": list(grade.reasons) if grade else [],
            }
        genes[table.gene] = entry
    return {
        "format": FORMAT,
        "note": INFO_NOTE,
        "not_affiliated": NOT_AFFILIATED,
        "versions": versions(),
        "study": {
            "study_id": inputs.study_id,
            "input_sha256": inputs.input_sha256,
            "record_ref": bundle.record_ref,
            "chain_head": bundle.chain_head,
            "design_hash": bundle.design_hash,
            "design_note": inputs.design_note,
        },
        "mode": bundle.mode,
        "template_id": bundle.template_id,
        "test": bundle.test,
        "scale": bundle.scale,
        "groups": list(inputs.group_order),
        "refs": list(inputs.refs),
        "undetermined": inputs.undetermined,
        "conclusion_rule": {**inputs.rule.as_dict(), "text": inputs.rule.describe()},
        "choices": [choice.as_dict() for choice in inputs.choices],
        "at_recommended_choices": inputs.at_primary,
        "genes": genes,
        "caption_tokens": bundle.info.get("caption_tokens", ""),
        "caption": bundle.info.get("caption", ""),
        "files": dict(bundle.files),
        "bundle_sha256": bundle.bundle_sha256,
        "unverified_until_step_0_1": list(UNVERIFIED),
    }


def write_provenance(bundle: PrismBundle, inputs: ExportInputs, out_dir: str | Path) -> Path:
    """Write ``qpilot_bundle.json`` and ``qpilot_provenance.json``; return the latter's path.

    Raises:
        PrismExportError: ``bundle_sha256`` is not the digest of the bundle (finalize first).
    """
    if bundle.bundle_sha256 != bundle_digest(bundle):
        raise PrismExportError("bundle_sha256 is out of date; call finalize() first")
    directory = Path(out_dir)
    write_bytes(directory / BUNDLE_FILE, dump_json(bundle.model_dump(mode="json")).encode("utf-8"))
    path = directory / PROVENANCE_FILE
    write_bytes(path, dump_json(provenance_dict(bundle, inputs)).encode("utf-8"))
    return path


# ---------------------------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    if not path.is_file() or path.is_symlink():
        raise ValueError("missing")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("too large")
    return json.loads(path.read_bytes().decode("utf-8"))


def load_bundle(directory: str | Path) -> PrismBundle:
    """Read ``qpilot_bundle.json`` from a bundle folder (size-capped, schema-validated).

    Raises:
        PrismExportError: Missing, too large or not a bundle.
    """
    try:
        return PrismBundle.model_validate(_read_json(Path(directory) / BUNDLE_FILE))
    except (OSError, ValueError, ValidationError, UnicodeDecodeError, RecursionError) as err:
        raise PrismExportError(f"{BUNDLE_FILE} unreadable: {err}") from err


def _safe_relative(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def verify_provenance(directory: str | Path) -> list[str]:
    """Every problem with a bundle folder's provenance (an empty list means it verifies)."""
    directory = Path(directory)
    problems: list[str] = []
    try:
        provenance = _read_json(directory / PROVENANCE_FILE)
        if not isinstance(provenance, dict):
            raise ValueError("not an object")
    except (OSError, ValueError, UnicodeDecodeError, RecursionError) as err:
        return [f"{PROVENANCE_FILE} unreadable ({err})"]
    try:
        bundle = load_bundle(directory)
    except PrismExportError as err:
        return [str(err)]
    if bundle_digest(bundle) != bundle.bundle_sha256:
        problems.append(f"{BUNDLE_FILE}: bundle_sha256 is not the digest of its contents")
    if provenance.get("bundle_sha256") != bundle.bundle_sha256:
        problems.append(f"{PROVENANCE_FILE}: bundle_sha256 differs from {BUNDLE_FILE}")
    if provenance.get("files") != bundle.files:
        problems.append(f"{PROVENANCE_FILE}: file list differs from {BUNDLE_FILE}")
    study = provenance.get("study") if isinstance(provenance.get("study"), dict) else {}
    for key in ("record_ref", "chain_head", "design_hash"):
        if study.get(key) != getattr(bundle, key):
            problems.append(f"{PROVENANCE_FILE}: {key} differs from {BUNDLE_FILE}")
    if study.get("study_id") != bundle.study_id:
        problems.append(f"{PROVENANCE_FILE}: study_id differs from {BUNDLE_FILE}")
    if provenance.get("note") != INFO_NOTE:
        problems.append(f"{PROVENANCE_FILE}: the Info note was changed")
    for name, digest in sorted(bundle.files.items()):
        if not _safe_relative(name):
            problems.append(f"unsafe file name in the bundle: {name!r}")
            continue
        path = directory / name
        if not path.is_file() or path.is_symlink():
            problems.append(f"missing: {name}")
        elif sha256_bytes(path.read_bytes()) != digest:
            problems.append(f"changed: {name}")
    for table in bundle.tables:
        if bundle.files.get(table.csv) != table.csv_sha256:
            problems.append(f"table {table.name}: its CSV checksum is not the listed one")
        if bundle.record_ref not in table.title or bundle.chain_head[:12] not in table.title:
            problems.append(f"table {table.name}: title lacks the record ref or chain head")
    return problems


__all__ = [
    "BUNDLE_FILE",
    "INFO_NOTE",
    "PROVENANCE_FILE",
    "UNVERIFIED",
    "caption",
    "finalize",
    "load_bundle",
    "provenance_dict",
    "verify_provenance",
    "write_provenance",
]
