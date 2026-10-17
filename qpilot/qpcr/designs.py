"""Study designs: what each sample is, which groups are compared, and which wells count.

The engine runs from a confirmed :class:`~qpilot.schemas_studio.StudyDesign` and from nothing
else. A design comes from one of three places:

* a preset: :func:`vermeulen_design` is the demo analysis (MYCN-high = top 15 % by MYCN
  expression vs the rest), and runs byte for byte as the engine always has;
* a file: :func:`load_design` reads a ``study.yaml`` and, optionally, a sample sheet (CSV);
* a person's decisions: :func:`design_from_proposals` applies the proposals a person accepted
  (or edited and accepted) to a base design, in order. A proposal that is only proposed,
  rejected or superseded has no effect, so the AI can never change a number on its own.

:func:`design_curves` applies a design's well-level choices to the per-well table (re-typed
wells, sample roles, excluded wells) before any quantity is computed; :func:`study_key` names a
study by its input file and design.

Deterministic; no model call, no network.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, ValidationError

from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS, AmpCallError, get_rule, well_keys
from qpilot.qpcr.curves import DEMO_EXPERIMENT, REFERENCE_TARGETS
from qpilot.qpcr.design import DEMO_GROUP_VAR, DEMO_MARKER
from qpilot.qpcr.quant import EXCLUDED
from qpilot.schemas_studio import (
    CONTROL_ROLES,
    Comparison,
    MarkerSplit,
    Proposal,
    SampleDesign,
    StudyDesign,
    TargetDesign,
)

log = logging.getLogger(__name__)

HEADLINE_GENES: tuple[str, ...] = ("ODC1", "BIRC5", "NTRK1", "NM23A")
LEGACY_DESIGN_ID = "vermeulen_expression_defined"
MAX_FILE_BYTES = 1 << 20  # design files and sample sheets: 1 MiB is far more than any needs
APPLIED = frozenset({"accepted", "edited"})  # the only proposal statuses the engine reads
SHEET_REQUIRED = ("sample", "group")
SHEET_OPTIONAL = ("biological_unit", "role", "quantity")
_WELL_KEY = re.compile(r"^[^/]+/[^/]+$")


class DesignError(ValueError):
    """A design file, sample sheet or accepted proposal that cannot be turned into a design."""


# ---------- presets ----------


def vermeulen_design() -> StudyDesign:
    """The demo study as a design: expression-defined groups, five candidate control genes.

    ``StudySettings.from_design(vermeulen_design())`` equals ``StudySettings()`` and gives the
    same output byte for byte.
    """
    return StudyDesign(
        design_id=LEGACY_DESIGN_ID,
        experiment_id=DEMO_EXPERIMENT,
        mode="marker_split",
        marker_split=MarkerSplit(
            marker=DEMO_MARKER, cut=0.15, cuts=(0.10, 0.15, 0.20), group_var=DEMO_GROUP_VAR
        ),
        reference_candidates=REFERENCE_TARGETS,
        headline=HEADLINE_GENES,
        amp_calls=("linregpcr",),
    )


PRESETS: dict[str, Callable[[], StudyDesign]] = {LEGACY_DESIGN_ID: vermeulen_design}


def is_legacy_design(design: StudyDesign | None) -> bool:
    """True for no design or the demo preset unchanged (the engine's original analysis)."""
    return design is None or design.design_hash() == vermeulen_design().design_hash()


def study_key(input_sha256: str, design: StudyDesign | None) -> str:
    """The 64-hex key of a study: its workspace name; the study id is its first 12 characters.

    The input file's sha256 for the legacy default (so every existing workspace keeps its
    name); otherwise sha256 of the input sha256 followed by the design hash, so the same file
    under two designs is two studies.
    """
    if is_legacy_design(design):
        return input_sha256
    joined = input_sha256 + design.design_hash()  # type: ignore[union-attr]
    return hashlib.sha256(joined.encode("ascii")).hexdigest()


# ---------- checks shared by every source ----------


def check_design(design: StudyDesign) -> StudyDesign:
    """Rules the schema cannot express; returns the design or raises :class:`DesignError`."""
    problems = []
    if design.marker_split is not None:
        split = design.marker_split
        bad = [c for c in (split.cut, *split.cuts) if not 0 < c < 1]
        if bad:
            problems.append(f"marker_split cut-offs must be between 0 and 1, not {bad}")
        if split.cut not in split.cuts:
            problems.append(f"marker_split.cut {split.cut} is not one of cuts {list(split.cuts)}")
    if design.comparison is not None and design.comparison.group_a == design.comparison.group_b:
        problems.append("comparison.group_a and group_b are the same group")
    for name, values in (
        ("reference_candidates", design.reference_candidates),
        ("headline", design.headline),
        ("amp_calls", design.amp_calls),
    ):
        repeated = sorted({v for v in values if values.count(v) > 1})
        if repeated:
            problems.append(f"{name} lists {repeated} more than once")
    for rule_id in design.amp_calls:
        try:
            get_rule(rule_id)
        except AmpCallError as err:
            problems.append(str(err))
    for key, sample in design.samples.items():
        if key != sample.sample:
            problems.append(f"samples[{key!r}] describes sample {sample.sample!r}")
    for key, target in design.targets.items():
        if key != target.target:
            problems.append(f"targets[{key!r}] describes target {target.target!r}")
    wells = [*design.well_roles, *design.well_calls, *design.excluded_wells]
    bad_keys = sorted({k for k in wells if not _WELL_KEY.match(k)})
    if bad_keys:
        problems.append(f"well keys must look like '<run_id>/<well>': {bad_keys[:5]}")
    unit_groups(design, problems)
    if problems:
        raise DesignError("; ".join(problems))
    return design


def unit_groups(design: StudyDesign, problems: list[str] | None = None) -> dict[str, str]:
    """Biological unit -> group, from the samples that have a group.

    All samples of one unit must be in the same group (technical replicates of one animal
    cannot be split across groups); a conflict is an error.
    """
    out: dict[str, str] = {}
    conflicts = []
    for sample in design.samples.values():
        if not sample.group:
            continue
        unit = sample.unit()
        if out.setdefault(unit, sample.group) != sample.group:
            conflicts.append(unit)
    if conflicts:
        message = f"biological units in more than one group: {sorted(set(conflicts))[:5]}"
        if problems is None:
            raise DesignError(message)
        problems.append(message)
    return out


def design_units(design: StudyDesign) -> dict[str, str]:
    """Sample -> biological unit, for the samples whose unit is not the sample itself."""
    return {s: d.unit() for s, d in design.samples.items() if d.unit() != s}


# ---------- reading a design from files ----------


class _StrictLoader(yaml.SafeLoader):
    """``yaml.safe_load`` that also refuses aliases and duplicate keys."""

    def compose_node(self, parent, index):
        """Refuse ``*alias`` references (they can multiply a small file's size)."""
        if self.check_event(yaml.AliasEvent):
            mark = self.peek_event().start_mark
            raise DesignError(f"line {mark.line + 1}: YAML aliases are not allowed in a design")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        """Refuse a key that appears twice (plain YAML silently keeps the last one)."""
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                line = key_node.start_mark.line + 1
                raise DesignError(f"line {line}: key {key!r} appears twice")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _read_text(path: str | Path, what: str) -> str:
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as err:
        raise DesignError(f"{what} {path}: {err.strerror or err}") from err
    if size > MAX_FILE_BYTES:
        raise DesignError(f"{what} {path.name} is {size:,} bytes; the limit is {MAX_FILE_BYTES:,}")
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as err:
        raise DesignError(f"{what} {path.name} is not UTF-8 text") from err


def _check_keys(data: Any, model: type[BaseModel], where: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DesignError(f"{where}: expected a mapping, not {type(data).__name__}")
    unknown = sorted(str(k) for k in data if k not in model.model_fields)
    if unknown:
        allowed = ", ".join(model.model_fields)
        raise DesignError(f"{where}: unknown field(s) {unknown}; allowed: {allowed}")
    return data


def _named_entries(data: Any, model: type[BaseModel], field: str, where: str) -> dict:
    """``samples`` / ``targets`` as ``{id: {...}}``; the id may be left out of each entry."""
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise DesignError(f"{where}: expected a mapping of {field} -> fields")
    out = {}
    for key, entry in data.items():
        if not isinstance(key, str):
            raise DesignError(f"{where}: name {key!r} must be text; put it in quotes")
        entry = _check_keys({} if entry is None else entry, model, f"{where}.{key}")
        if entry.get(field, key) != key:
            raise DesignError(f"{where}.{key}: {field} is {entry[field]!r}, not {key!r}")
        out[key] = {**entry, field: key}
    return out


def _validate(data: dict[str, Any], where: str) -> StudyDesign:
    try:
        design = StudyDesign.model_validate(data)
    except ValidationError as err:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'design'}: {e['msg']}" for e in err.errors()
        )
        raise DesignError(f"{where}: {details}") from None
    return check_design(design)


def read_sample_sheet(path: str | Path) -> dict[str, SampleDesign]:
    """Read a sample sheet (CSV): ``sample`` and ``group`` required; see the module docstring.

    Optional columns ``biological_unit``, ``role`` (an RDML sample type, default: as declared
    in the file) and ``quantity`` (standards). Other columns are ignored with a warning. Header
    names are matched case-insensitively; blank rows are skipped; a sample listed twice is
    refused.
    """
    text = _read_text(path, "sample sheet")
    name = Path(path).name
    reader = csv.reader(io.StringIO(text))
    rows = [(i, row) for i, row in enumerate(reader, start=1) if any(c.strip() for c in row)]
    if not rows:
        raise DesignError(f"sample sheet {name} is empty")
    header = [h.strip().lower() for h in rows[0][1]]
    missing = [c for c in SHEET_REQUIRED if c not in header]
    if missing:
        raise DesignError(f"sample sheet {name}: missing column(s) {missing}")
    repeated = sorted({h for h in header if h and header.count(h) > 1})
    if repeated:
        raise DesignError(f"sample sheet {name}: column(s) {repeated} appear twice")
    unknown = [h for h in header if h not in (*SHEET_REQUIRED, *SHEET_OPTIONAL)]
    if unknown:
        log.warning("sample sheet %s: ignoring column(s) %s", name, unknown)
    samples: dict[str, SampleDesign] = {}
    lines: dict[str, int] = {}
    for line, row in rows[1:]:
        cells = {h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(header)}
        sample = cells["sample"]
        if not sample:
            raise DesignError(f"sample sheet {name} line {line}: no sample name")
        if sample in samples:
            raise DesignError(
                f"sample sheet {name}: sample {sample!r} on lines {lines[sample]} and {line}"
            )
        fields: dict[str, Any] = {"sample": sample, "group": cells["group"] or None}
        if cells.get("biological_unit"):
            fields["biological_unit"] = cells["biological_unit"]
        if cells.get("role"):
            fields["role"] = cells["role"].lower()
        if cells.get("quantity"):
            try:
                fields["quantity"] = float(cells["quantity"])
            except ValueError:
                raise DesignError(
                    f"sample sheet {name} line {line}: quantity {cells['quantity']!r} "
                    "is not a number"
                ) from None
        try:
            samples[sample] = SampleDesign.model_validate(fields)
        except ValidationError as err:
            details = "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in err.errors())
            raise DesignError(f"sample sheet {name} line {line}: {details}") from None
        lines[sample] = line
    return samples


def load_design(yaml_path: str | Path, samples_csv: str | Path | None = None) -> StudyDesign:
    """Read and check a ``study.yaml`` (and an optional sample sheet).

    The file is a mapping with the fields of :class:`~qpilot.schemas_studio.StudyDesign`;
    ``samples`` and ``targets`` are mappings keyed by name (the name may be left out of each
    entry). Unknown fields, YAML aliases, repeated keys and files over 1 MiB are refused.
    Samples from the sheet are added to the file's; a sample in both is refused.

    Raises:
        DesignError: With a message naming the file, line or field at fault.
    """
    text = _read_text(yaml_path, "design file")
    where = Path(yaml_path).name
    try:
        data = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as err:
        raise DesignError(f"{where}: not valid YAML ({err})") from None
    data = dict(_check_keys(data, StudyDesign, where))
    for field, model, attr in (
        ("samples", SampleDesign, "sample"),
        ("targets", TargetDesign, "target"),
    ):
        data[field] = _named_entries(data.get(field), model, attr, f"{where}: {field}")
    for field, model in (("marker_split", MarkerSplit), ("comparison", Comparison)):
        if data.get(field) is not None:
            _check_keys(data[field], model, f"{where}: {field}")
    if samples_csv is not None:
        sheet = read_sample_sheet(samples_csv)
        both = sorted(set(sheet) & set(data["samples"]))
        if both:
            raise DesignError(f"sample(s) in both {where} and the sample sheet: {both[:5]}")
        data["samples"].update({s: d.model_dump() for s, d in sheet.items()})
    return _validate(data, where)


# ---------- a design from a person's decisions ----------


def design_from_proposals(
    base: StudyDesign, accepted: Iterable[Proposal], curves: pd.DataFrame | None = None
) -> StudyDesign:
    """Apply the accepted (or edited and accepted) proposals to ``base``, in list order.

    Only ``accepted`` and ``edited`` proposals are read, through
    :meth:`~qpilot.schemas_studio.Proposal.effective_payload`; any other status has no effect.
    A later proposal on the same kind and subject wins. ``prism.exclusion_reason`` needs
    ``curves`` (the per-well table) to find the wells of a gene and sample.

    Raises:
        DesignError: A proposal cannot be applied, or the result is not a valid design.
    """
    data = base.model_dump()
    start_refs: tuple[str, ...] | None = None  # set once a target role changes
    for proposal in accepted:
        if proposal.status not in APPLIED:
            continue
        name = proposal.id or proposal.kind
        payload = proposal.effective_payload()
        if proposal.kind == "design.preset":
            start_refs = None
        elif proposal.kind == "design.target_role" and start_refs is None:
            start_refs = tuple(data["reference_candidates"])
        try:
            data = _apply(data, proposal.kind, proposal.subject, payload, curves)
        except (DesignError, AmpCallError) as err:
            raise DesignError(f"proposal {name}: {err}") from None
        except (KeyError, TypeError, ValueError) as err:
            raise DesignError(f"proposal {name}: payload not usable ({err!r})") from None
    if start_refs is not None:
        data["reference_candidates"] = _rebuild_references(start_refs, data["targets"])
    return _validate(data, "design from accepted proposals")


def _sample(data: dict[str, Any], sample: str) -> dict[str, Any]:
    if "/" in sample:
        raise DesignError(f"{sample!r} is a well, not a sample")
    return data["samples"].setdefault(sample, {"sample": sample})


def _target(data: dict[str, Any], target: str) -> dict[str, Any]:
    return data["targets"].setdefault(target, {"target": target})


def _rebuild_references(start: tuple[str, ...], targets: dict[str, Any]) -> tuple[str, ...]:
    """Reference candidates after target-role changes, independent of the order they came in.

    The candidates the design started with keep their order unless now marked ``toi``; targets
    newly marked ``ref`` follow, sorted by name.
    """
    roles = {t: entry.get("role", "toi") for t, entry in targets.items()}
    kept = [t for t in start if roles.get(t, "ref") == "ref"]
    added = sorted(t for t, role in roles.items() if role == "ref" and t not in kept)
    return (*kept, *added)


def _apply(
    data: dict[str, Any],
    kind: str,
    subject: str,
    payload: Mapping[str, Any],
    curves: pd.DataFrame | None,
) -> dict[str, Any]:
    """One accepted proposal applied to the design's plain-data form."""
    if kind == "design.preset":
        name = payload["preset"]
        if name not in PRESETS:
            raise DesignError(f"unknown preset {name!r} (known: {', '.join(PRESETS)})")
        return PRESETS[name]().model_dump()
    if kind == "design.well_role":
        if "/" in subject:
            data["well_roles"][subject] = payload["role"]
        else:
            _sample(data, subject)["role"] = payload["role"]
    elif kind == "design.group":
        _sample(data, subject)["group"] = payload["group"]
    elif kind == "design.bio_unit":
        _sample(data, subject)["biological_unit"] = payload["biological_unit"]
    elif kind == "design.target_role":  # reference_candidates are rebuilt once, at the end
        _target(data, subject)["role"] = payload["role"]
    elif kind == "design.gene_symbol":
        _target(data, subject)["symbol"] = payload["symbol"]
    elif kind == "design.comparison":
        data["comparison"] = {
            "group_a": payload["group_a"],
            "group_b": payload["group_b"],
            "label": payload.get("label", ""),
        }
        data["mode"] = "groups"
        data["marker_split"] = None
    elif kind == "design.dilution_series":
        for sample, quantity in dict(payload["samples"]).items():
            entry = _sample(data, str(sample))
            entry["role"] = "std"
            entry["quantity"] = float(quantity)
    elif kind == "curve.call_rule":
        chosen = get_rule(payload["rule"]).id
        current = tuple(data["amp_calls"])
        others = STUDIO_AMP_CALLS if len(current) <= 1 else current
        data["amp_calls"] = (chosen, *(r for r in others if r != chosen))
    elif kind == "curve.well_call":
        amplified = payload["amplified"]
        if not isinstance(amplified, bool):
            raise DesignError(f"amplified must be true or false, not {amplified!r}")
        data["well_calls"][subject] = amplified
    elif kind == "prism.exclusion_reason":
        _exclusion(data, payload, curves)
    return data  # prism.project and prism.value_edit do not change the design


def _exclusion(data: dict[str, Any], payload: Mapping[str, Any], curves: pd.DataFrame | None):
    action, gene, sample = payload["action"], payload["gene"], payload["sample"]
    if action not in ("exclude", "restore"):
        raise DesignError(f"action must be 'exclude' or 'restore', not {action!r}")
    if curves is None:
        raise DesignError("an exclusion needs the per-well table to find the wells")
    units = {s: (e.get("biological_unit") or s) for s, e in data["samples"].items()}
    in_sample = curves["sample"].map(lambda s: s == sample or units.get(s, s) == sample)
    rows = curves[(curves["target"] == gene) & in_sample]
    if rows.empty:
        raise DesignError(f"no well of {gene!r} for sample {sample!r}")
    wells = set(well_keys(rows))
    current = set(data["excluded_wells"])
    current = current | wells if action == "exclude" else current - wells
    data["excluded_wells"] = tuple(sorted(current))


# ---------- the per-well table as the design says ----------


def design_curves(curves: pd.DataFrame, design: StudyDesign) -> pd.DataFrame:
    """A copy of the per-well table with the design's well-level choices applied.

    * ``well_roles`` re-type single wells; a sample's ``role`` re-types all its wells, except
      that ``"unkn"`` (the default) keeps the type declared in the file. A well re-typed away
      from ``"unkn"`` leaves the matrix of study samples.
    * ``excluded_wells`` are marked in the boolean column ``design_excluded``: they still show
      that the sample was measured, but their values are never used.

    ``well_calls`` are applied with the amplification rule
    (:func:`qpilot.qpcr.amp_call.apply_rule`), not here.

    Raises:
        DesignError: The design would turn a declared control (NTC, no-RT, no-amplification)
            into another role, or names a well that is not in the table.
    """
    out = curves.copy()
    keys = well_keys(out)
    named = [*design.well_roles, *design.well_calls, *design.excluded_wells]
    unknown = sorted(set(named) - set(keys))
    if unknown:
        raise DesignError(f"wells named in the design but not in the data: {unknown[:5]}")
    declared = out["sample_type"]
    roles = {s: d.role for s, d in design.samples.items() if d.role != "unkn"}
    sample_type = out["sample"].map(roles).fillna(declared)
    if design.well_roles:
        sample_type = keys.map(design.well_roles).fillna(sample_type)
    demoted = declared.isin(CONTROL_ROLES) & ~sample_type.isin(CONTROL_ROLES)
    if demoted.any():
        wells = sorted(keys[demoted])[:5]
        raise DesignError(f"a declared control cannot be re-typed as another role: {wells}")
    out["sample_type"] = sample_type.astype(str)
    if design.excluded_wells:
        out[EXCLUDED] = keys.isin(set(design.excluded_wells)).to_numpy()
    return out
