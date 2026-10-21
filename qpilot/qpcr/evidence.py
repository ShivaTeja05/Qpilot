"""Evidence Ledger: what a study's data can show, and what nobody recorded.

Bench errors that leave no trace in the curves can only be stated: no no-RT control, RNA
integrity unknown, RT never replicated, no reference set that meets geNorm's cut-offs. The
ledger is a fixed list of evidence items (:data:`ITEMS`). Each item has

* a status: ``present``, ``absent``, ``not_applicable`` or ``unknown``;
* the facts behind it, with ids ``f_ev_<item>_<field>`` (every number the ledger shows);
* a one-line consequence: a code and its template text with ``{{fact_id}}`` tokens
  (:data:`CONSEQUENCES`), rendered by :mod:`qpilot.explain.evidence_text`;
* the MIQE 2.0 item(s) it answers (:data:`MIQE_ITEMS`).

Rules:

* An absent item is a reported check. It never downgrades a confidence grade, never changes
  ``conclude()`` and never enters ``StudyResult``: the ledger is its own output (stored as
  ``evidence.json`` by the store's artifact writer), built after the study from the same inputs.
* Free text from the file is never copied. A sample annotation's property is only classified
  (RNA integrity, lot, RT batch) and counted; run descriptions and instrument strings are only
  tested for being present.
* MIQE 2.0 item numbers follow Table 1 of the article as abbreviated in the repository's
  research notes (:data:`MIQE_SOURCE`); they are to be checked against the article.

Entry points: :func:`evidence_for` (per-well table + study model, pure) and
:func:`evidence_store` (a stored study, read-only). Deterministic: no model call and no network.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel

from qpilot.core.facts import FactRegistry, slug
from qpilot.core.store import dump_json
from qpilot.core.validator import validate
from qpilot.io.rdml_io import RdmlLoadError, load
from qpilot.qpcr.curves import analyse_study
from qpilot.qpcr.designs import design_curves
from qpilot.qpcr.gate_rt import g_rt, rt_labels
from qpilot.qpcr.quant import EXCLUDED
from qpilot.qpcr.study import StudyModel, StudySettings, build_model
from qpilot.schemas import Fact, GenormResult
from qpilot.schemas_studio import StudyDesign

Status = Literal["present", "absent", "not_applicable", "unknown"]
EfficiencySource = Literal["per_well_raw", "standard_curve", "assumed"]
STATUSES: tuple[str, ...] = ("present", "absent", "not_applicable", "unknown")

LEDGER_VERSION = 1
METHOD_CARD_PATH = "methods/evidence.md"
GENORM_MIN_CANDIDATES = 3  # geNorm gives V only from three candidates (study._stability)
STD_MIN_LEVELS = 3  # a standard series needs three levels (design_checks.MIN_LEVELS, D-SERIES)
COUNT_FMT = "{:,}"  # 24576 -> 24,576, as the study facts show counts

ITEMS: tuple[str, ...] = (
    "ntc",
    "no_rt",
    "reference_genes",
    "efficiency",
    "rawness",
    "rna_integrity",
    "rt_replicates",
    "biological_units",
    "inter_run_calibrator",
    "lots",
    "instrument",
)
ITEM_TITLES: dict[str, str] = {
    "ntc": "NTC on every plate and target",
    "no_rt": "No-RT control",
    "reference_genes": "Reference candidates with geNorm M and V",
    "efficiency": "Efficiency source",
    "rawness": "Raw-ness of the curves",
    "rna_integrity": "RNA integrity",
    "rt_replicates": "RT replicates or RT batch",
    "biological_units": "Biological units",
    "inter_run_calibrator": "Inter-run calibrator",
    "lots": "Reagent and primer lots",
    "instrument": "Instrument and calibration dates",
}
MIQE_VERSION = "2.0"
MIQE_SOURCE = (
    "MIQE 2.0 (Bustin et al., Clin Chem 2025;71(6):634-651, doi:10.1093/clinchem/hvaf043) "
    "Table 1 numbering, as abbreviated in "
    "research_notes/qPilot niche discovery and features/14-publication-reviewers-teaching.md "
    "(machine-checkability map); item ids to verify against the article"
)
MIQE_ITEMS: dict[str, tuple[str, ...]] = {
    "ntc": ("5.5", "5.6"),  # details of negative controls; frequency and Cq of them
    "no_rt": ("3.5",),  # estimated copies with and without RT
    "reference_genes": ("5.15",),  # method of validation of reference genes
    "efficiency": ("5.8",),  # PCR efficiency estimation and method
    "rawness": ("5.3", "5.1"),  # baseline correction and Cq method; raw fluorescence data
    "rna_integrity": ("2.9",),  # method to evaluate quality and quantity
    "rt_replicates": ("5.10",),  # description of replicates (Section 3 has no RT-replicate item)
    "biological_units": ("5.10",),  # description of replicates
    "inter_run_calibrator": ("5.12",),  # reproducibility (inter-run)
    "lots": ("3.6", "4.4"),  # reagent manufacturer, catalogue, lot; buffer or kit lot
    "instrument": ("4.6",),  # manufacturer and type of instrument (calibration: no item)
}

# Consequence code -> one line of template text. Every token names a fact of that item.
CONSEQUENCES: dict[str, str] = {
    "ntc_every_pair_clean": (
        "NTC wells are typed on all {{f_ev_ntc_n_pairs}} plate × target pairs, and none of the "
        "{{f_ev_ntc_n_wells}} amplified."
    ),
    "ntc_every_pair_signal": (
        "NTC wells are typed on all {{f_ev_ntc_n_pairs}} plate × target pairs; "
        "{{f_ev_ntc_n_wells_with_value}} of {{f_ev_ntc_n_wells}} amplified, on "
        "{{f_ev_ntc_n_plates_with_value}} plates, and no Run Gate rule checks what that means "
        "for the samples yet."
    ),
    "ntc_some_pairs": (
        "NTC wells are typed on {{f_ev_ntc_n_pairs_with_ntc}} of {{f_ev_ntc_n_pairs}} plate × "
        "target pairs; contamination cannot be checked on the others."
    ),
    "ntc_none": "No well is typed NTC, so contamination cannot be checked from this file.",
    "no_rt_typed": (
        "{{f_ev_no_rt_n_wells}} wells are typed no-RT, on {{f_ev_no_rt_n_pairs_with_nrt}} of "
        "{{f_ev_no_rt_n_pairs}} plate × target pairs; no rule compares them with the samples yet."
    ),
    "no_rt_none": (
        "No well is typed no-RT (RDML type nrt), so genomic DNA carry-over cannot be checked "
        "from this file."
    ),
    "refs_meet_cutoffs": (
        "{{f_ev_reference_genes_n_candidates}} reference candidates with geNorm M and V; a "
        "reference set meets geNorm's cut-offs (M below {{f_ev_reference_genes_cutoff_m}}, V "
        "below {{f_ev_reference_genes_cutoff_v}})."
    ),
    "refs_below_cutoffs": (
        "{{f_ev_reference_genes_n_candidates}} reference candidates with geNorm M and V, but "
        "no reference set meets geNorm's cut-offs: {{f_ev_reference_genes_n_below_m}} "
        "candidates have M below {{f_ev_reference_genes_cutoff_m}}, and the lowest V is "
        "{{f_ev_reference_genes_v_min}} against {{f_ev_reference_genes_cutoff_v}}. Which set to "
        "use is a judgement call; the reference-set card shows what it changes."
    ),
    "refs_too_few": (
        "Reference candidates named: {{f_ev_reference_genes_n_candidates}}; geNorm needs at "
        "least {{f_ev_reference_genes_min_candidates}} to give M and V, so reference stability "
        "is not shown."
    ),
    "eff_per_well_raw": (
        "Efficiency is measured per well from the raw curves (LinRegPCR) on "
        "{{f_ev_efficiency_n_wells_with_eff}} of {{f_ev_efficiency_n_wells}} study wells and "
        "used as the plate mean per gene; gene medians run from {{f_ev_efficiency_min}} to "
        "{{f_ev_efficiency_max}}."
    ),
    "eff_per_well_raw_series_unused": (
        "Efficiency is measured per well from the raw curves (LinRegPCR) on "
        "{{f_ev_efficiency_n_wells_with_eff}} of {{f_ev_efficiency_n_wells}} study wells and "
        "used as the plate mean per gene; gene medians run from {{f_ev_efficiency_min}} to "
        "{{f_ev_efficiency_max}}. A standard series is on "
        "{{f_ev_efficiency_n_plates_with_series}} of {{f_ev_efficiency_n_plates}} plates; it "
        "is not used for efficiency."
    ),
    "eff_assumed": (
        "No study well has a measured efficiency, so quantities rest on an assumed efficiency."
    ),
    "rawness_unknown_consistent": (
        "Not judged: qPilot's raw-ness check reads an instrument export when it is opened, and "
        "this study's file did not go through it. The cheap signs are consistent with raw "
        "curves: {{f_ev_rawness_n_wells_with_curves}} wells were analysed from their "
        "amplification curves and none has a baseline at or below zero."
    ),
    "rawness_unknown_low_baseline": (
        "Not judged: qPilot's raw-ness check reads an instrument export when it is opened, and "
        "this study's file did not go through it. "
        "{{f_ev_rawness_n_wells_baseline_not_positive}} of "
        "{{f_ev_rawness_n_wells_with_curves}} wells have a baseline at or below zero, as "
        "baseline-subtracted data would; treat the curves as possibly processed."
    ),
    "rawness_unknown_no_baseline": (
        "Not judged: qPilot's raw-ness check reads an instrument export when it is opened, and "
        "this study's file did not go through it; the table carries no baseline to look at."
    ),
    # The import's own check (qpilot.io.rawness, run when an instrument export is opened).
    "rawness_import_raw": (
        "The import's raw-ness check read the curves as raw fluorescence on "
        "{{f_ev_rawness_n_plates_raw}} of {{f_ev_rawness_n_plates_judged}} plates, so LinRegPCR "
        "estimates each well's baseline and efficiency itself."
    ),
    "rawness_import_normalized": (
        "The import's raw-ness check read the curves as normalised to a passive reference (Rn) "
        "on {{f_ev_rawness_n_plates_judged}} plates; the ground phase is kept, so LinRegPCR "
        "still estimates each well's baseline and efficiency."
    ),
    "rawness_import_baseline_subtracted": (
        "The import's raw-ness check found baseline-subtracted curves on "
        "{{f_ev_rawness_n_plates_not_raw}} of {{f_ev_rawness_n_plates_judged}} plates: per-well "
        "efficiency is weakened there. Re-export the raw fluorescence to restore it."
    ),
    "rawness_import_scaled": (
        "The import's raw-ness check found curves rescaled to a fixed range on "
        "{{f_ev_rawness_n_plates_not_raw}} of {{f_ev_rawness_n_plates_judged}} plates; whether "
        "a baseline was subtracted first cannot be seen."
    ),
    "rawness_import_cq_only": (
        "The import holds Cq values only: efficiency is assumed, not measured from curves."
    ),
    "rawness_import_unknown": (
        "The import's raw-ness check could not tell whether the curves were processed "
        "({{f_ev_rawness_n_plates_judged}} plates judged); treat per-well efficiencies with "
        "caution."
    ),
    "rin_absent": (
        "No RNA integrity value (RIN or similar) is recorded for any of the "
        "{{f_ev_rna_integrity_n_samples}} study samples, so RNA quality cannot be related to Cq."
    ),
    "rin_present": (
        "An RNA integrity value is recorded for {{f_ev_rna_integrity_n_annotated}} of "
        "{{f_ev_rna_integrity_n_samples}} study samples; no rule reads it yet."
    ),
    "rt_not_measured": "RT variability not measured: no RT replicates or RT batches are annotated.",
    "rt_batch_in_file": (
        "An RT batch is annotated in the file for {{f_ev_rt_replicates_n_samples_rt_in_file}} "
        "samples, but no sample sheet names RT replicates of one biological unit, so RT "
        "variability not measured."
    ),
    "rt_not_measurable": (
        "RT replicates are annotated for {{f_ev_rt_replicates_n_units}} biological units, but "
        "no unit × target has RT replicates with a Cq to compare, so RT variability not measured."
    ),
    "rt_within_limit": (
        "RT replicates are annotated for {{f_ev_rt_replicates_n_units}} biological units; all "
        "{{f_ev_rt_replicates_n_pairs}} unit × target RT-replicate ranges are below "
        "{{f_ev_rt_replicates_limit}} (largest {{f_ev_rt_replicates_max_range}})."
    ),
    "rt_over_limit": (
        "RT replicates are annotated for {{f_ev_rt_replicates_n_units}} biological units; "
        "{{f_ev_rt_replicates_n_over}} of {{f_ev_rt_replicates_n_pairs}} unit × target "
        "RT-replicate ranges reach {{f_ev_rt_replicates_limit}} or more (largest "
        "{{f_ev_rt_replicates_max_range}}), so RT variability is part of those fold changes."
    ),
    "units_known": (
        "A sample sheet names every study sample: {{f_ev_biological_units_n_samples}} samples "
        "in {{f_ev_biological_units_n_units}} biological units; replicates are averaged within "
        "a unit and never counted as n."
    ),
    "units_partial": (
        "A sample sheet names {{f_ev_biological_units_n_listed}} of "
        "{{f_ev_biological_units_n_samples}} study samples; the others count as their own unit."
    ),
    "units_unknown": (
        "No sample sheet names the biological units, so each of the "
        "{{f_ev_biological_units_n_samples}} study samples counts as its own unit; that holds "
        "only if no two samples come from the same animal, patient or culture."
    ),
    "irc_not_needed": (
        "Each of the {{f_ev_inter_run_calibrator_n_targets}} targets is measured on a single "
        "plate, so no inter-run calibrator is needed."
    ),
    "irc_every_plate": (
        "{{f_ev_inter_run_calibrator_n_spanning}} targets span more than a single plate, "
        "and each has a calibrator sample on every one of its plates."
    ),
    "irc_missing": (
        "{{f_ev_inter_run_calibrator_n_unbridged}} of "
        "{{f_ev_inter_run_calibrator_n_spanning}} targets that span plates have no "
        "calibrator sample on every plate, so plate-to-plate offsets enter their fold changes."
    ),
    "lots_absent": (
        "No reagent or primer lot is recorded, so drift cannot be tied to a lot change later."
    ),
    "lots_present": (
        "Lot annotations are recorded for {{f_ev_lots_n_samples_annotated}} samples; no rule "
        "reads them yet."
    ),
    "instrument_absent": (
        "None of the {{f_ev_instrument_n_runs}} runs in the file names an instrument or a run "
        "date, and RDML has no field for calibration dates, so the instrument's history cannot "
        "be checked from this file."
    ),
    "instrument_partial": (
        "{{f_ev_instrument_n_runs_with_instrument}} of {{f_ev_instrument_n_runs}} runs name an "
        "instrument and {{f_ev_instrument_n_runs_with_date}} carry a run date; RDML has no "
        "field for calibration dates."
    ),
    "instrument_present": (
        "All {{f_ev_instrument_n_runs}} runs name an instrument and a run date; calibration "
        "dates are not an RDML field and need the instrument's own files."
    ),
    "file_not_read": "Not looked for: the input file was not read.",
    "no_study_wells": "Not judged: the table has no study wells.",
}

METHOD_CARD: dict[str, Any] = {
    "id": "evidence",
    "version": str(LEDGER_VERSION),
    "title": "Evidence Ledger",
    "source": (
        "qPilot's own checklist; items mapped to MIQE 2.0 (Bustin et al., Clin Chem 2025); "
        "geNorm cut-offs from Vandesompele et al., Genome Biol 2002"
    ),
    "implementation": "qpilot/qpcr/evidence.py",
    "inputs": [
        "per-well table (curves.COLUMN_ORDER)",
        "StudyModel (geNorm result, candidates, experiment)",
        "StudyDesign (optional)",
        "the RDML document (optional): run and sample fields, counted only",
    ],
    "outputs": ["EvidenceLedger: eleven items, each with status, facts, consequence, MIQE ids"],
    "acceptance_tests": [
        "tests/engine/test_evidence.py::test_demo_ledger_equals_the_fixture",
        "tests/engine/test_evidence.py::test_every_item_has_present_absent_and_other_cases",
        "tests/engine/test_evidence.py::test_rendered_ledger_passes_the_validator",
    ],
    "licence": "Apache-2.0",
    "card": METHOD_CARD_PATH,
}


class EvidenceError(ValueError):
    """A ledger cannot be built: the input file is missing or does not reproduce the study."""


# ---------- the ledger ----------


class Consequence(BaseModel):
    """What an item's status means for the study: a stable code and its template text."""

    code: str
    text: str  # ``{{fact_id}}`` tokens; render with qpilot.explain.evidence_text


class EvidenceItem(BaseModel):
    """One evidence item: its status, the facts behind it and what follows from it."""

    id: str
    title: str
    status: Status
    value: str | None = None  # e.g. the efficiency source or the G-RT verdict
    consequence: Consequence
    miqe: list[str]
    facts: list[str]  # ids of this item's facts in EvidenceLedger.facts


class EvidenceLedger(BaseModel):
    """The Evidence Ledger of one study: :data:`ITEMS` in order, and every fact they cite.

    JSON-stable: :meth:`to_json` is byte-identical for the same inputs. A ledger never changes
    a conclusion or a confidence grade; it is not part of ``StudyResult``.
    """

    version: int = LEDGER_VERSION
    study_id: str | None = None
    input_sha256: str | None = None
    experiment_id: str | None = None
    miqe_source: str = MIQE_SOURCE
    items: list[EvidenceItem]
    facts: dict[str, Fact]

    def item(self, item_id: str) -> EvidenceItem:
        """The item with this id; ``KeyError`` if there is none."""
        for entry in self.items:
            if entry.id == item_id:
                return entry
        raise KeyError(f"no evidence item {item_id!r}; known: {', '.join(ITEMS)}")

    def statuses(self) -> dict[str, str]:
        """Item id -> status, in :data:`ITEMS` order."""
        return {entry.id: entry.status for entry in self.items}

    def counts(self) -> dict[str, int]:
        """How many items have each status (every status listed, zero included)."""
        found = [entry.status for entry in self.items]
        return {status: found.count(status) for status in STATUSES}

    def to_json(self) -> str:
        """The stored form: sorted keys, two-space indent, trailing newline."""
        return dump_json(self.model_dump(mode="json"))


# ---------- what the RDML file says (counted, never copied) ----------


@dataclass(frozen=True)
class RunFlags:
    """Which optional fields one RDML run fills; the values themselves are not kept."""

    experiment_id: str
    run_id: str
    instrument: bool
    run_date: bool
    background_method: bool


@dataclass(frozen=True)
class SampleFlags:
    """What one RDML sample's optional fields and annotations record, classified only."""

    inter_run_calibrator: bool = False
    integrity: bool = False
    lot: bool = False
    rt_batch: bool = False


@dataclass(frozen=True)
class RdmlEvidence:
    """The RDML facts the ledger reads, extracted once by :func:`rdml_evidence`."""

    runs: tuple[RunFlags, ...] = ()
    samples: Mapping[str, SampleFlags] = field(default_factory=dict)


_INTEGRITY = re.compile(r"(^|_)(rin|rin_?e|rqi|rqn|dv_?200|integrity|rna_?quality)(_|$)")
_LOT = re.compile(r"(^|_)lot(s|_?no|_?number)?(_|$)")
_RT_BATCH = re.compile(r"(^|_)(rt|cdna|reverse_?transcription)_?(batch|replicate|date)(_|$)")


def _normalised(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def classify_property(name: object) -> tuple[bool, bool, bool]:
    """(integrity, lot, RT batch) for an annotation property name such as ``RIN`` or ``Lot``.

    Only the classification is ever used; the name itself is not kept or shown.
    """
    key = _normalised(name)
    return bool(_INTEGRITY.search(key)), bool(_LOT.search(key)), bool(_RT_BATCH.search(key))


def rdml_evidence(doc: Any) -> RdmlEvidence:
    """Count the optional run and sample fields of a loaded RDML document.

    Args:
        doc: An ``rdml.Rdml`` document (:func:`qpilot.io.rdml_io.load`).

    Returns:
        Per run (every experiment): whether it names an instrument, a run date and a background
        method. Per sample: the inter-run-calibrator flag and whether an annotation records RNA
        integrity, a lot or an RT batch. No text from the file is kept.
    """
    runs = []
    for experiment in doc.experiments():
        for run in experiment.runs():
            runs.append(
                RunFlags(
                    experiment_id=str(experiment["id"]),
                    run_id=str(run["id"]),
                    instrument=bool((run["instrument"] or "").strip()),
                    run_date=bool((run["runDate"] or "").strip()),
                    background_method=bool((run["backgroundDeterminationMethod"] or "").strip()),
                )
            )
    samples = {}
    for sample in doc.samples():
        integrity = lot = rt_batch = False
        for annotation in sample.annotations():
            a, b, c = classify_property(annotation.get("property"))
            integrity, lot, rt_batch = integrity or a, lot or b, rt_batch or c
        samples[str(sample["id"])] = SampleFlags(
            inter_run_calibrator=sample["interRunCalibrator"] is True,
            integrity=integrity,
            lot=lot,
            rt_batch=rt_batch,
        )
    return RdmlEvidence(runs=tuple(runs), samples=samples)


# ---------- the items ----------


@dataclass
class _Draft:
    """One item before its facts are registered: status, code and ``field -> fact`` values."""

    item: str
    status: Status
    code: str
    values: dict[str, tuple[float | int | str, str, str]] = field(default_factory=dict)
    value: str | None = None

    def put(self, name: str, value: float | int | str, fmt: str = "{}", unit: str = "") -> None:
        self.values[name] = (value, fmt, unit)


def _study_wells(table: pd.DataFrame) -> pd.DataFrame:
    wells = table[table["sample_type"] == "unkn"]
    if EXCLUDED in wells.columns:
        wells = wells[~wells[EXCLUDED].astype(bool)]
    return wells


def _pairs(frame: pd.DataFrame) -> set[tuple[str, str]]:
    return set(zip(frame["run_id"].astype(str), frame["target"].astype(str), strict=True))


def _ntc(table: pd.DataFrame, study: pd.DataFrame) -> _Draft:
    pairs = _pairs(study)
    ntc = table[table["sample_type"] == "ntc"]
    covered = pairs & _pairs(ntc)
    with_value = ntc[ntc["n0"].notna()]
    if not pairs:
        return _Draft("ntc", "unknown", "no_study_wells")
    if not covered:
        draft = _Draft("ntc", "absent", "ntc_none")
    elif covered != pairs:
        draft = _Draft("ntc", "absent", "ntc_some_pairs")
    else:
        code = "ntc_every_pair_signal" if len(with_value) else "ntc_every_pair_clean"
        draft = _Draft("ntc", "present", code)
    draft.put("n_pairs", len(pairs))
    draft.put("n_pairs_with_ntc", len(covered))
    draft.put("n_wells", len(ntc), COUNT_FMT)
    draft.put("n_wells_with_value", len(with_value), COUNT_FMT)
    draft.put("n_plates_with_value", int(with_value["run_id"].nunique()))
    return draft


def _no_rt(table: pd.DataFrame, study: pd.DataFrame) -> _Draft:
    pairs = _pairs(study)
    nrt = table[table["sample_type"] == "nrt"]
    if not pairs and nrt.empty:
        return _Draft("no_rt", "unknown", "no_study_wells")
    if len(nrt):
        draft = _Draft("no_rt", "present", "no_rt_typed")
    else:
        draft = _Draft("no_rt", "absent", "no_rt_none")
    draft.put("n_wells", len(nrt), COUNT_FMT)
    draft.put("n_pairs", len(pairs))
    draft.put("n_pairs_with_nrt", len(pairs & _pairs(nrt)))
    return draft


def meets_genorm_cutoffs(genorm: GenormResult) -> bool:
    """At least two references below the M cut-off and some V below the V cut-off.

    The same rule as ``confidence_checks.normalisation_passes`` (which takes a whole
    ``StudyResult``); the tests check that the two agree.
    """
    stable = [m for m in genorm.M_initial.values() if m < genorm.cutoff_M]
    return len(stable) >= 2 and any(v < genorm.cutoff_V for v in genorm.V.values())


def _reference_genes(genorm: GenormResult, candidates: tuple[str, ...]) -> _Draft:
    n = len(candidates)
    if n < GENORM_MIN_CANDIDATES or not genorm.V:
        draft = _Draft("reference_genes", "absent", "refs_too_few")
    elif meets_genorm_cutoffs(genorm):
        draft = _Draft("reference_genes", "present", "refs_meet_cutoffs")
    else:
        draft = _Draft("reference_genes", "present", "refs_below_cutoffs")
    draft.put("n_candidates", n)
    draft.put("min_candidates", GENORM_MIN_CANDIDATES)
    draft.put("cutoff_m", float(genorm.cutoff_M), "{:g}")
    draft.put("cutoff_v", float(genorm.cutoff_V), "{:g}")
    draft.put("n_below_m", sum(1 for m in genorm.M_initial.values() if m < genorm.cutoff_M))
    for ref in sorted(genorm.M_initial):
        draft.put(f"m_{slug(ref)}", float(genorm.M_initial[ref]), "{:.2f}")
    for key in sorted(genorm.V):  # "V2/3" -> v_2_3
        draft.put(f"v_{slug(key[1:])}", float(genorm.V[key]), "{:.2f}")
    if genorm.V:
        draft.put("v_min", float(min(genorm.V.values())), "{:.2f}")
    return draft


def _efficiency(table: pd.DataFrame, study: pd.DataFrame) -> _Draft:
    if study.empty:
        return _Draft("efficiency", "unknown", "no_study_wells")
    measured = study["eff_indiv"].notna() if "eff_indiv" in study.columns else None
    n_with = int(measured.sum()) if measured is not None else 0
    if n_with == 0:
        draft = _Draft("efficiency", "absent", "eff_assumed", value="assumed")
        draft.put("n_wells", len(study), COUNT_FMT)
        draft.put("n_wells_with_eff", 0, COUNT_FMT)
        return draft
    per_gene = table.dropna(subset=["eff_target"]).groupby("target")["eff_target"].median()
    std = table[table["sample_type"] == "std"]
    levels = std.groupby("run_id")["sample"].nunique()
    n_series = int((levels >= STD_MIN_LEVELS).sum())
    code = "eff_per_well_raw_series_unused" if n_series else "eff_per_well_raw"
    draft = _Draft("efficiency", "present", code, value="per_well_raw")
    draft.put("n_wells", len(study), COUNT_FMT)
    draft.put("n_wells_with_eff", n_with, COUNT_FMT)
    if not per_gene.empty:
        draft.put("median", float(per_gene.median()), "{:.2f}")
        draft.put("min", float(per_gene.min()), "{:.2f}")
        draft.put("max", float(per_gene.max()), "{:.2f}")
    draft.put("n_plates", int(table["run_id"].nunique()))
    draft.put("n_plates_with_series", n_series)
    return draft


#: The import's raw-ness verdict (``qpilot.io.rawness``) -> the ledger's status for raw curves.
RAWNESS_STATUS: dict[str, Status] = {
    "raw": "present",
    "normalized": "present",
    "baseline_subtracted": "absent",
    "scaled": "unknown",
    "cq_only": "absent",
    "unknown": "unknown",
}


def _rawness_import(table: pd.DataFrame, rawness: Mapping[str, Any]) -> _Draft | None:
    """The rawness item from the import's own check, when the study came from one."""
    verdict = str(rawness.get("study_verdict") or "")
    if verdict not in RAWNESS_STATUS:
        return None
    plates = rawness.get("plate_verdicts")
    plates = dict(plates) if isinstance(plates, Mapping) else {}
    draft = _Draft("rawness", RAWNESS_STATUS[verdict], f"rawness_import_{verdict}", value=verdict)
    if verdict != "cq_only":
        raw = sum(v in ("raw", "normalized") for v in plates.values())
        draft.put("n_plates_judged", len(plates), COUNT_FMT)
        draft.put("n_plates_raw", raw, COUNT_FMT)
        draft.put("n_plates_not_raw", len(plates) - raw, COUNT_FMT)
    draft.put("n_wells_with_curves", len(table), COUNT_FMT)
    return draft


def _rawness(
    table: pd.DataFrame,
    file: RdmlEvidence | None,
    experiment_id: str | None,
    rawness: Mapping[str, Any] | None = None,
) -> _Draft:
    if table.empty:
        return _Draft("rawness", "unknown", "no_study_wells", value="unknown")
    if rawness:
        found = _rawness_import(table, rawness)
        if found is not None:
            return found
    if "baseline" in table.columns:
        low = int((pd.to_numeric(table["baseline"], errors="coerce") <= 0).sum())
        code = "rawness_unknown_low_baseline" if low else "rawness_unknown_consistent"
        draft = _Draft("rawness", "unknown", code, value="unknown")
        draft.put("n_wells_baseline_not_positive", low, COUNT_FMT)
    else:
        draft = _Draft("rawness", "unknown", "rawness_unknown_no_baseline", value="unknown")
    draft.put("n_wells_with_curves", len(table), COUNT_FMT)
    if file is not None:
        plates = set(table["run_id"].astype(str))
        runs = [r for r in file.runs if r.run_id in plates]
        if experiment_id is not None:
            runs = [r for r in runs if r.experiment_id == experiment_id]
        draft.put("n_runs", len(runs))
        draft.put("n_runs_background_stated", sum(r.background_method for r in runs))
    return draft


def _rna_integrity(samples: list[str], file: RdmlEvidence | None) -> _Draft:
    if not samples:
        return _Draft("rna_integrity", "unknown", "no_study_wells")
    if file is None:
        return _Draft("rna_integrity", "unknown", "file_not_read")
    k = sum(file.samples.get(s, SampleFlags()).integrity for s in samples)
    if k:
        draft = _Draft("rna_integrity", "present", "rin_present")
    else:
        draft = _Draft("rna_integrity", "absent", "rin_absent")
    draft.put("n_samples", len(samples), COUNT_FMT)
    draft.put("n_annotated", k, COUNT_FMT)
    return draft


def _rt_replicates(
    table: pd.DataFrame,
    design: StudyDesign | None,
    samples: list[str],
    file: RdmlEvidence | None,
) -> _Draft:
    line = g_rt(table, design)
    facts = {fid.removeprefix("f_grt_"): fact for fid, fact in line.facts.items()}
    labelled = rt_labels(design)
    in_file = sum(file.samples.get(s, SampleFlags()).rt_batch for s in samples) if file else 0
    if int(facts["n_units"].value):  # the G-RT codes for annotated units are ledger codes too
        draft = _Draft("rt_replicates", "present", line.code)
    elif in_file:
        draft = _Draft("rt_replicates", "present", "rt_batch_in_file")
    else:
        draft = _Draft("rt_replicates", "absent", "rt_not_measured")
    draft.value = f"{line.rule_id} {line.status}"
    draft.put("n_samples_annotated", sum(1 for s in samples if s in labelled), COUNT_FMT)
    if file is not None:
        draft.put("n_samples_rt_in_file", in_file, COUNT_FMT)
    for name, fact in facts.items():
        draft.put(name, fact.value, fact.fmt, fact.unit)
    return draft


def _biological_units(samples: list[str], design: StudyDesign | None) -> _Draft:
    if not samples:
        return _Draft("biological_units", "unknown", "no_study_wells")
    listed = design.samples if design is not None else {}
    named = [s for s in samples if s in listed]
    units = {listed[s].unit() if s in listed else s for s in samples}
    if named and len(named) == len(samples):
        draft = _Draft("biological_units", "present", "units_known")
    elif named:
        draft = _Draft("biological_units", "absent", "units_partial")
    else:
        draft = _Draft("biological_units", "absent", "units_unknown")
    draft.put("n_samples", len(samples), COUNT_FMT)
    draft.put("n_listed", len(named), COUNT_FMT)
    draft.put("n_units", len(units), COUNT_FMT)
    return draft


def _inter_run_calibrator(
    table: pd.DataFrame, study: pd.DataFrame, file: RdmlEvidence | None
) -> _Draft:
    if study.empty:
        return _Draft("inter_run_calibrator", "unknown", "no_study_wells")
    plates = study.groupby("target")["run_id"].agg(lambda runs: frozenset(runs.astype(str)))
    spanning = sorted(str(t) for t, runs in plates.items() if len(runs) > 1)
    marked = file.samples.items() if file is not None else ()
    flagged = {s for s, flags in marked if flags.inter_run_calibrator}
    candidates = table[
        table["sample_type"].isin(("unkn", "std")) | table["sample"].astype(str).isin(flagged)
    ]
    bridged = 0
    for target in spanning:
        rows = candidates[candidates["target"].astype(str) == target]
        on = rows.groupby("sample")["run_id"].agg(lambda runs: frozenset(runs.astype(str)))
        if any(plates[target] <= runs for runs in on):
            bridged += 1
    if not spanning:
        draft = _Draft("inter_run_calibrator", "not_applicable", "irc_not_needed")
    elif bridged == len(spanning):
        draft = _Draft("inter_run_calibrator", "present", "irc_every_plate")
    else:
        draft = _Draft("inter_run_calibrator", "absent", "irc_missing")
    draft.put("n_targets", len(plates))
    draft.put("n_spanning", len(spanning))
    draft.put("n_bridged", bridged)
    draft.put("n_unbridged", len(spanning) - bridged)
    if file is not None:
        in_table = set(table["sample"].astype(str))
        draft.put("n_samples_flagged", len(flagged & in_table))
    return draft


def _lots(samples: list[str], file: RdmlEvidence | None) -> _Draft:
    if file is None:
        return _Draft("lots", "unknown", "file_not_read")
    k = sum(file.samples.get(s, SampleFlags()).lot for s in samples)
    if k:
        draft = _Draft("lots", "present", "lots_present")
    else:
        draft = _Draft("lots", "absent", "lots_absent")
    draft.put("n_samples_annotated", k, COUNT_FMT)
    return draft


def _instrument(file: RdmlEvidence | None) -> _Draft:
    if file is None:
        return _Draft("instrument", "unknown", "file_not_read")
    n = len(file.runs)
    with_instrument = sum(r.instrument for r in file.runs)
    with_date = sum(r.run_date for r in file.runs)
    if n and with_instrument == n and with_date == n:
        draft = _Draft("instrument", "present", "instrument_present")
    elif with_instrument or with_date:
        draft = _Draft("instrument", "absent", "instrument_partial")
    else:
        draft = _Draft("instrument", "absent", "instrument_absent")
    draft.put("n_runs", n)
    draft.put("n_runs_with_instrument", with_instrument)
    draft.put("n_runs_with_date", with_date)
    return draft


# ---------- assembling ----------


def _assemble(drafts: Iterable[_Draft], experiment_id: str | None) -> EvidenceLedger:
    registry = FactRegistry()

    def add(fid: str, value: float | int | str, fmt: str = "{}", unit: str = "", path: str = ""):
        return registry.add(Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path)).id

    items = []
    for draft in drafts:
        item = draft.item
        ids = [
            add(f"f_ev_{item}_{name}", value, fmt, unit, f"evidence.{item}.{name}")
            for name, (value, fmt, unit) in draft.values.items()
        ]
        miqe = ", ".join(MIQE_ITEMS[item])
        ids.append(add(f"f_ev_{item}_status", draft.status, path=f"evidence.{item}.status"))
        ids.append(add(f"f_ev_{item}_code", draft.code, path=f"evidence.{item}.code"))
        ids.append(add(f"f_ev_{item}_miqe", miqe, path=f"evidence.{item}.miqe"))
        text = CONSEQUENCES[draft.code]
        facts = {fid: registry.get(fid) for fid in ids}
        check = validate(text, facts)
        if not check.ok:  # a template and its item disagree: a programming error, never data
            raise EvidenceError(f"evidence item {item} ({draft.code}): {check.error()}")
        items.append(
            EvidenceItem(
                id=item,
                title=ITEM_TITLES[item],
                status=draft.status,
                value=draft.value,
                consequence=Consequence(code=draft.code, text=text),
                miqe=list(MIQE_ITEMS[item]),
                facts=sorted(ids),
            )
        )
    found = [entry.status for entry in items]
    add("f_ev_n_items", len(items), path="evidence.items")
    for status in STATUSES:
        add(f"f_ev_n_{status}", found.count(status), path=f"evidence.counts.{status}")
    add("f_ev_miqe_version", MIQE_VERSION, path="evidence.miqe_source")
    facts = dict(sorted(registry.as_dict().items()))
    return EvidenceLedger(experiment_id=experiment_id, items=items, facts=facts)


def evidence_for(
    curves: pd.DataFrame,
    model: StudyModel,
    design: StudyDesign | None = None,
    rdml_doc: Any = None,
    rawness: Mapping[str, Any] | None = None,
) -> EvidenceLedger:
    """Build the Evidence Ledger of one study from its inputs (pure; nothing is written).

    Args:
        curves: The per-well table (``curves.COLUMN_ORDER``) the study was analysed from.
        model: The study's :class:`~qpilot.qpcr.study.StudyModel` (geNorm result, candidates,
            experiment); it is read, never changed.
        design: The confirmed design (default: the model's own, ``None`` for the legacy demo
            analysis); its well-level choices are applied to ``curves`` first.
        rdml_doc: The loaded RDML document, or an :class:`RdmlEvidence` already extracted from
            it. Without it, the items that need the file (RNA integrity, lots, instrument
            dates) are ``unknown``.
        rawness: The import's raw-ness block (``CaptureMeta.rawness``, from
            :mod:`qpilot.io.rawness`) when the study was opened from an instrument export; the
            rawness item then states its verdict instead of the cheap signs.

    Returns:
        The :class:`EvidenceLedger`, items in :data:`ITEMS` order, without ``study_id`` or
        ``input_sha256`` (:func:`evidence_store` fills them).

    Raises:
        DesignError: The design names wells that are not in the table.
    """
    design = design if design is not None else model.settings.design
    table = design_curves(curves, design) if design is not None else curves
    if rdml_doc is None or isinstance(rdml_doc, RdmlEvidence):
        file = rdml_doc
    else:
        file = rdml_evidence(rdml_doc)
    study = _study_wells(table)
    samples = sorted(set(study["sample"].astype(str)))
    drafts = [
        _ntc(table, study),
        _no_rt(table, study),
        _reference_genes(model.stability, tuple(model.settings.candidates)),
        _efficiency(table, study),
        _rawness(table, file, model.settings.experiment_id, rawness),
        _rna_integrity(samples, file),
        _rt_replicates(table, design, samples, file),
        _biological_units(samples, design),
        _inter_run_calibrator(table, study, file),
        _lots(samples, file),
        _instrument(file),
    ]
    return _assemble(drafts, model.settings.experiment_id)


def evidence_store(
    store: Any, study_id: str, *, rawness: Mapping[str, Any] | None = None
) -> EvidenceLedger:
    """The Evidence Ledger of a stored study, rebuilt read-only from its input file.

    The per-well table comes from the curve cache (LinRegPCR runs only if the cache is cold)
    and the study model is rebuilt from the stored design; nothing in the workspace is written.
    To keep it, the caller stores ``ledger.model_dump(mode="json")`` as ``evidence.json``.

    Args:
        store: A :class:`~qpilot.core.store.StudyStore`.
        study_id: The study id (or a unique prefix of it).
        rawness: The import's raw-ness block when the study came from an instrument export
            (see :func:`evidence_for`).

    Returns:
        The ledger with ``study_id`` and ``input_sha256`` set.

    Raises:
        EvidenceError: The input file is not available (moved, changed or never recorded),
            cannot be read again, or re-analysing it does not reproduce the stored geNorm
            result.
        StudyNotFound: No such study.
    """
    result = store.get(study_id)
    source = store.source(study_id)
    if source is None:
        raise EvidenceError(
            "the input file of this study is not available (moved, changed or never recorded); "
            "run the study again from its file"
        )
    design = store.design(study_id)
    settings = StudySettings.from_design(design) if design is not None else StudySettings()
    curves = analyse_study(source, settings.experiment_id, settings.candidates, settings.curves)
    model = build_model(curves, settings)
    if model.stability.model_dump(mode="json") != result.genorm.model_dump(mode="json"):
        raise EvidenceError("re-analysing the input file does not reproduce the stored study")
    try:
        doc = load(source, validate=False)
    except RdmlLoadError as err:
        raise EvidenceError(f"the input file cannot be read again: {err}") from err
    ledger = evidence_for(curves, model, design, doc, rawness=rawness)
    return ledger.model_copy(
        update={"study_id": result.study_id, "input_sha256": result.input_sha256}
    )
