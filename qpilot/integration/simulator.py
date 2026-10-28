"""Run the Decision Simulator (``qsim``) on a study qPilot analysed, and bind the audit to it.

The simulator is a separate package that re-runs one study under every combination of eight
analysis decisions. On its own it reads an RDML file and assumes the demo's design. Here it is
given exactly what qPilot analysed instead:

* the per-well table **after** the confirmed design (well roles, wells a person excluded) and
  the primary amplification-call rule, from :func:`qpilot.qpcr.study.build_model`;
* the comparison groups qPilot compared (the demo's MYCN split, or the design's two named
  groups) and the control-gene candidates;
* qPilot's own conclusion rule.

**The contract.** Before any alternative is computed, the simulator's baseline analysis must
reproduce qPilot's stored result for every gene (the same genes, fold change and p-value to
:data:`TOLERANCE`, the same conclusion). If it does not, :class:`AuditRefused` is raised and
nothing is written: the audit never describes numbers other than the study's.

**What does not fit.** A study whose design has technical replicates (several wells per
biological unit and gene) is refused with :class:`NotApplicable`: the simulator needs one well
per sample and gene. So is a marker split whose cut-offs are not the simulator's 10/15/20 %.

**What is written** (all inside ``out_dir``): the simulator's own results folder
(``lock.json`` first, then ``genes.csv``, ``explain.json``, ``summary.json``, ``REPORT.md``, ...),
plus ``your_choices.csv`` (the analysis the person chose on the Decision Cards against the
prespecified one), ``audit_manifest.json`` (what was audited: study id, input sha256, chain
head, design hash, the reproduction check) and ``AUDIT.sha256`` over every file.
:func:`verify_audit` checks those, and that the audit belongs to a given Analysis Record.

Nothing here writes to the study store, the decision record or a Prism file.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qpilot.core.store import StudyStore
from qpilot.io.inputs import input_label

TOLERANCE = 1e-9  # |log2 fold change| and |p| differences allowed between qsim and qPilot
AUDIT_DIR_FILES = ("lock.json", "summary.json", "genes.csv", "explain.json", "REPORT.md")
MANIFEST = "audit_manifest.json"
CHECKSUMS = "AUDIT.sha256"
SIM_CUTS = (0.10, 0.15, 0.20)  # the simulator's group cut-off options (marker split)
PRESPECIFIED_CUT = 0.15  # the simulator's modules key the comparison groups on this value
GROUPS_OPTION = "design"  # the single "cut" option of a design with two named groups
#: qPilot's amplification-call rule -> the simulator's late-Cq option (same meaning: wells with
#: a Cq above the line count as not detected). ``cq_le_40`` and ``learned`` have no counterpart.
AMP_TO_LATE_CQ = {"linregpcr": "none", "cq_le_35": "cq35", "cq_le_38": "cq38"}
UNDETERMINED_TO_NONDETECT = {"drop": "drop", "cap": "cap_min"}
#: qPilot's efficiency models (``qpilot/qpcr/axes``) -> the simulator's ``efficiency`` options.
#: One efficiency per amplicon over its plates has no counterpart there.
EFFICIENCY_TO_SIM = {
    "linregpcr": "assay_mean",
    "per_well": "per_well",
    "assumed_2": "assume_100",
    "standard_curve": "std_curve",
}


class SimulatorUnavailable(RuntimeError):
    """The ``qsim`` package is not installed in this environment."""


class NotApplicable(ValueError):
    """The study's design is outside what the simulator can audit; the reason says why."""


class AuditRefused(RuntimeError):
    """The simulator's baseline does not reproduce qPilot's stored result; nothing is written."""


def available() -> bool:
    """True when the Decision Simulator (``qsim``) can be imported."""
    try:
        import qsim  # noqa: F401
    except ImportError:
        return False
    return True


def _require_qsim() -> None:
    if not available():
        raise SimulatorUnavailable(
            "the Decision Simulator (qsim) is not installed; from a qPilot clone run "
            "pip install -e '.[sim]' to audit a study"
        )


# ---------------------------------------------------------------------------------------------
# What qPilot analysed
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Analysis:
    """One stored study, rebuilt read-only: the inputs the audit is built from."""

    study_id: str
    input_sha256: str
    source: Path
    settings: Any  # qpilot.qpcr.study.StudySettings
    model: Any  # qpilot.qpcr.study.StudyModel
    inputs: Any  # qpilot.qpcr.export.ExportInputs (choices, chain head, design hash)
    result: Any  # qpilot.schemas.StudyResult

    @property
    def mode(self) -> str:
        """``groups`` for a design with two named groups, else ``marker_split``."""
        return "groups" if self.model.labels is not None else "marker_split"


def load_analysis(store: StudyStore, study_id: str) -> Analysis:
    """Rebuild a stored study read-only (the Prism bridge's own route: same numbers or refuse)."""
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.export import study_inputs
    from qpilot.qpcr.study import StudySettings, build_model

    inputs = study_inputs(store, study_id, read_only=True)  # raises if it does not reproduce
    design = store.design(study_id)
    settings = StudySettings.from_design(design) if design is not None else StudySettings()
    source = store.source(study_id)
    if source is None:
        raise NotApplicable("the study's input file is missing or has changed")
    curves = analyse_study(source, settings.experiment_id, settings.candidates, settings.curves)
    model = build_model(curves, settings)
    return Analysis(
        study_id=study_id,
        input_sha256=inputs.input_sha256,
        source=Path(source),
        settings=settings,
        model=model,
        inputs=inputs,
        result=store.get(study_id),
    )


# ---------------------------------------------------------------------------------------------
# The simulator's study, built from qPilot's table
# ---------------------------------------------------------------------------------------------


@dataclass
class Prepared:
    """A qsim study, space and engine for one qPilot study, plus how it was built."""

    study: Any  # qsim.data.Study
    space: Any  # qsim.decisions.Space
    space_info: dict
    engine: Any  # ExcludingEngine
    scope: dict[str, Any] = field(default_factory=dict)


def _technical_replicates(table: pd.DataFrame, units: Mapping[str, str] | None) -> bool:
    unknown = table[table["sample_type"] == "unkn"]
    if unknown.duplicated(["sample", "target"]).any():
        return True
    if units:
        counts = pd.Series([units.get(s, s) for s in unknown["sample"].unique()]).value_counts()
        return bool((counts > 1).any())
    return False


def _aligned_table(table: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Undetermined means the same in both: a study well with no quantity has no Cq either.

    qPilot treats a well without ``n0`` as undetermined (an amplification rule only clears
    ``n0``); the simulator reads undetermined from a missing Cq. Clearing Cq where ``n0`` is
    missing makes both use one definition. Returns the table and how many Cqs were cleared.
    """
    out = table.copy()
    mask = (out["sample_type"] == "unkn") & out["n0"].isna() & out["cq"].notna()
    out.loc[mask, "cq"] = np.nan
    return out, int(mask.sum())


def _exclusion_mask(table: pd.DataFrame, samples: list[str], genes: list[str]) -> np.ndarray:
    from qpilot.qpcr.quant import EXCLUDED

    if EXCLUDED not in table.columns:
        return np.zeros((len(samples), len(genes)), dtype=bool)
    unknown = table[table["sample_type"] == "unkn"]
    pivot = unknown.pivot(index="sample", columns="target", values=EXCLUDED)
    pivot = pivot.reindex(index=samples, columns=genes)
    return pivot.astype("boolean").fillna(False).to_numpy(dtype=bool)


def _groups_study(table: pd.DataFrame, digest: str, candidates: tuple[str, ...], groups) -> Any:
    """A qsim Study for a design with two named groups (no marker gene, one comparison).

    The arrays are built the way :func:`qsim.data.study_from_curves` builds them; only the
    groups come from the design instead of a marker split.
    """
    from qsim.data import EFFICIENCY_NOTES, LOW_COPY_NOTE, Study, standard_curve_efficiency

    from qpilot.qpcr.quant import log2_matrix
    from qpilot.qpcr.refgenes import genorm

    matrix = log2_matrix(table)
    samples, genes = list(matrix.index), list(matrix.columns)
    unknown = table[table["sample_type"] == "unkn"]
    unknown = unknown[unknown["sample"].isin(samples)]

    def grid(column: str, fill: object = np.nan, dtype: object = float) -> np.ndarray:
        pivot = unknown.pivot(index="sample", columns="target", values=column)
        return pivot.reindex(index=samples, columns=genes).fillna(fill).to_numpy(dtype=dtype)

    cq, n0 = grid("cq"), grid("n0")
    eff_assay, eff_well = grid("eff_target"), grid("eff_indiv")
    notes = grid("note", "", object)
    with np.errstate(divide="ignore", invalid="ignore"):
        log2_n0 = np.log2(n0)
    log2_nq = log2_n0 + cq * np.log2(eff_assay)
    flag_eff = np.vectorize(lambda s: any(k in str(s) for k in EFFICIENCY_NOTES))(notes)
    flag_low = np.vectorize(lambda s: LOW_COPY_NOTE in str(s))(notes)
    eff_std = standard_curve_efficiency(table)
    runs = grid("run_id", "", object)
    eff_std_grid = np.vectorize(lambda r: eff_std.get(r, np.nan))(runs).astype(float)
    stability = genorm(matrix, list(candidates)) if len(candidates) >= 3 else None
    primary = (
        tuple(g for g in candidates if g in set(stability.recommended))
        if stability is not None
        else tuple(candidates)
    )
    return Study(
        curves=table,
        input_sha256=digest,
        samples=samples,
        genes=genes,
        candidates=tuple(candidates),
        primary_refs=primary,
        marker="",
        items=[g for g in genes if g not in set(candidates)],
        cq=cq,
        log2_n0=log2_n0,
        log2_nq=log2_nq,
        eff_well=eff_well,
        eff_assay=eff_assay,
        eff_std=eff_std_grid,
        flag_eff=flag_eff.astype(bool),
        flag_low=flag_low.astype(bool),
        run=runs,
        well=grid("well", "", object),
        groups={PRESPECIFIED_CUT: groups},
    )


def _excluding_engine_class() -> type:
    from qsim.engine import Engine

    class ExcludingEngine(Engine):
        """qsim's engine with the wells a person excluded left out of every analysis.

        An excluded value is missing, never undetermined, so no non-detect rule fills it in
        (qPilot's rule, :func:`qpilot.qpcr.quant.excluded_cells`).
        """

        def __init__(self, study, space, excluded: np.ndarray, rule=None) -> None:
            self.excluded = excluded
            if rule is None:
                super().__init__(study, space)
            else:
                super().__init__(study, space, rule)

        def matrix(self, efficiency, flagged, nondetect, drop=None, late=None):
            if self.excluded.any():
                drop = self.excluded if drop is None else (drop | self.excluded)
            return super().matrix(efficiency, flagged, nondetect, drop, late)

    return ExcludingEngine


def _groups_space(space, labels: tuple[str, str]):
    """The simulator's space with the cut-off replaced by the design's one comparison."""
    from qsim.decisions import Decision, Option, Space

    decisions = []
    for d in space.decisions:
        if d.id == "cut":
            d = Decision(
                "cut",
                d.stage,
                d.kind,
                "Which groups are compared?",
                (
                    Option(
                        GROUPS_OPTION,
                        PRESPECIFIED_CUT,
                        "prespecified",
                        f"the confirmed design: {labels[0]} vs {labels[1]}",
                    ),
                ),
                role="question",
            )
        decisions.append(d)
    return Space(tuple(decisions), {**space.baseline, "cut": GROUPS_OPTION}, notes=space.notes)


def prepare(analysis: Analysis) -> Prepared:
    """The simulator's study, space and engine for this analysis (nothing written).

    Raises:
        NotApplicable: Technical replicates, or a marker split the simulator cannot vary.
    """
    _require_qsim()
    from qsim.data import study_from_curves
    from qsim.study_space import space_for

    from qpilot.qpcr.contrast import DEFAULT_RULE

    model, settings = analysis.model, analysis.settings
    table = model.inputs.primary_table
    units = model.inputs.units
    if _technical_replicates(table, units):
        raise NotApplicable(
            "the design has technical replicates (several wells per biological unit and gene); "
            "the simulator needs one well per sample and gene"
        )
    table, aligned = _aligned_table(table)
    candidates = tuple(settings.candidates)
    if analysis.mode == "marker_split":
        if tuple(settings.cuts) != SIM_CUTS or settings.cut != PRESPECIFIED_CUT:
            raise NotApplicable(
                f"the simulator varies the cut-off over {SIM_CUTS} around {PRESPECIFIED_CUT}; "
                f"this design uses {tuple(settings.cuts)} around {settings.cut}"
            )
        study = study_from_curves(
            table,
            analysis.input_sha256,
            candidates=candidates,
            marker=settings.marker,
            cuts=SIM_CUTS,
        )
        space, info = space_for(study)
        labels = (f"{settings.marker_label}-high", "rest")
    else:
        unit_of = units or {}
        to_samples = {}
        for sample in table.loc[table["sample_type"] == "unkn", "sample"].unique():
            to_samples.setdefault(unit_of.get(sample, sample), sample)
        groups = tuple(frozenset(to_samples[u] for u in side) for side in (model.high, model.rest))
        study = _groups_study(table, analysis.input_sha256, candidates, groups)
        primary = tuple(model.space.primary["refs"])
        if set(study.primary_refs) != set(primary):
            study = dataclasses.replace(
                study, primary_refs=tuple(g for g in candidates if g in set(primary))
            )
        base_space, info = space_for(study)
        labels = tuple(model.labels)
        space = _groups_space(base_space, labels)
    primary_refs = set(model.space.primary["refs"])
    if set(study.primary_refs) != primary_refs:
        raise AuditRefused(
            f"the simulator's prespecified control genes {sorted(study.primary_refs)} are not "
            f"qPilot's {sorted(primary_refs)}"
        )
    rule = settings.rule if settings.rule != DEFAULT_RULE else None
    excluded = _exclusion_mask(table, study.samples, study.genes)
    engine = _excluding_engine_class()(study, space, excluded, rule)
    scope = {
        "mode": analysis.mode,
        "groups": list(labels),
        "n_samples": len(study.samples),
        "n_genes_compared": len(study.items),
        "n_in_groups": [
            len(study.groups[PRESPECIFIED_CUT][0]),
            len(study.groups[PRESPECIFIED_CUT][1]),
        ],
        "control_gene_candidates": list(candidates),
        "prespecified_control_genes": list(study.primary_refs),
        "amplification_rule": settings.amp_calls[0],
        "wells_excluded_by_a_person": int(excluded.sum()),
        "undetermined_aligned": aligned,
        "decisions": {d.id: [o.id for o in d.options] for d in space.decisions if d.id != "refs"},
        "reference_sets": len(space.decision("refs").options),
        "analyses_in_full_grid": int(np.prod(space.levels)),
    }
    return Prepared(study, space, info, engine, scope)


# ---------------------------------------------------------------------------------------------
# The contract: the simulator's baseline is qPilot's result
# ---------------------------------------------------------------------------------------------


def reproduction(prepared: Prepared, result: Any) -> dict[str, Any]:
    """Compare the simulator's baseline with qPilot's stored contrasts, gene by gene."""
    from qsim.engine import CALL_NAMES

    engine, space = prepared.engine, prepared.space
    base = engine.evaluate(space.baseline_index())
    stored = result.contrasts
    sim_genes, qp_genes = set(engine.items), set(stored)
    worst_fc = worst_p = 0.0
    mismatched: list[str] = []
    for i, gene in enumerate(engine.items):
        if gene not in stored:
            continue
        c = stored[gene]
        d_fc = abs(float(base["log2fc"][i]) - float(c.log2fc))
        p_sim, p_qp = float(base["p"][i]), float(c.p)
        d_p = 0.0 if (math.isnan(p_sim) and math.isnan(p_qp)) else abs(p_sim - p_qp)
        call = CALL_NAMES[int(base["call"][i])]
        worst_fc, worst_p = max(worst_fc, d_fc), max(worst_p, d_p)
        if not (d_fc <= TOLERANCE and d_p <= TOLERANCE and call == c.conclusion):
            mismatched.append(gene)
    ok = sim_genes == qp_genes and not mismatched
    return {
        "ok": ok,
        "genes": len(qp_genes),
        "genes_only_in_qpilot": sorted(qp_genes - sim_genes),
        "genes_only_in_simulator": sorted(sim_genes - qp_genes),
        "mismatched": mismatched,
        "max_abs_diff_log2fc": worst_fc,
        "max_abs_diff_p": worst_p,
        "tolerance": TOLERANCE,
    }


def chosen_changes(prepared: Prepared, choices) -> tuple[dict[str, str], list[str]]:
    """The person's Decision Card choices as simulator options (and what has no counterpart)."""
    space = prepared.space
    changes: dict[str, str] = {}
    notes: list[str] = []
    for choice in choices:
        if choice.dimension == "refs":
            wanted = set(choice.value)
            match = [o.id for o in space.decision("refs").options if set(o.value) == wanted]
            if match:
                changes["refs"] = match[0]
            else:
                notes.append(f"control genes {sorted(wanted)}: no simulator option")
        elif choice.dimension == "cut":
            match = [o.id for o in space.decision("cut").options if o.value == float(choice.value)]
            if match:
                changes["cut"] = match[0]
            else:
                notes.append(f"cut-off {choice.value}: no simulator option")
        elif choice.dimension == "undetermined":
            changes["nondetect"] = UNDETERMINED_TO_NONDETECT[str(choice.value)]
        elif choice.dimension == "amp_call":
            late = AMP_TO_LATE_CQ.get(str(choice.value))
            if late is None:
                notes.append(f"amplification rule {choice.value}: no simulator counterpart")
            else:
                changes["late_cq"] = late
        elif choice.dimension == "efficiency":
            model = EFFICIENCY_TO_SIM.get(str(choice.value))
            if model is None:
                notes.append(f"efficiency model {choice.value}: no simulator counterpart")
            else:
                changes["efficiency"] = model
        else:
            notes.append(f"{choice.dimension}: no simulator counterpart")
    base = space.baseline
    return {k: v for k, v in changes.items() if base.get(k) != v}, notes


# ---------------------------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------------------------


@dataclass
class AuditResult:
    """What one audit found and where it is."""

    out_dir: Path
    study_id: str
    manifest: dict[str, Any]
    summary: dict[str, Any]
    verdicts: dict[str, str]
    your_choices: pd.DataFrame
    seconds: float

    @property
    def verdict_counts(self) -> dict[str, int]:
        """How many genes got each verdict."""
        return dict(self.summary.get("verdicts", {}).get("counts", {}))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_checksums(out_dir: Path) -> str:
    lines = [
        f"{sha256_file(p)}  {p.relative_to(out_dir).as_posix()}"
        for p in sorted(out_dir.rglob("*"))
        if p.is_file() and p.name != CHECKSUMS
    ]
    text = "\n".join(lines) + "\n"
    (out_dir / CHECKSUMS).write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()


def audit(
    store: StudyStore,
    study_id: str,
    out_dir: str | Path,
    *,
    permutations: int = 999,
    seed: int = 2026,
    bench_trials: int = 0,
    design_draws: int = 0,
    explorer: bool = False,
) -> AuditResult:
    """Audit one stored study with the Decision Simulator and write the bound audit folder.

    ``bench_trials`` (planted faults), ``design_draws`` (small-experiment draws) and
    ``explorer`` (cheaper-search check) are the simulator's method checks; they are off by
    default because they test the simulator on this data rather than audit the study.

    Raises:
        SimulatorUnavailable: ``qsim`` is not installed.
        NotApplicable: The design is outside what the simulator can audit.
        AuditRefused: The simulator's baseline does not reproduce the stored result.
    """
    _require_qsim()
    import qsim
    from qsim.compare import whatif
    from qsim.report import run_all

    started = time.perf_counter()
    analysis = load_analysis(store, study_id)
    prepared = prepare(analysis)
    check = reproduction(prepared, analysis.result)
    if not check["ok"]:
        raise AuditRefused(
            "the simulator's baseline does not reproduce qPilot's stored result "
            f"(mismatched: {check['mismatched'][:5]}, only in qPilot: "
            f"{check['genes_only_in_qpilot'][:5]}, only in the simulator: "
            f"{check['genes_only_in_simulator'][:5]}); the audit refuses rather than describe "
            "other numbers"
        )
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; give a new folder for the audit")
    out.mkdir(parents=True, exist_ok=True)
    summary = run_all(
        str(analysis.source),
        out,
        permutations=permutations,
        bench_trials=bench_trials,
        seed=seed,
        design_draws=design_draws,
        explorer=explorer,
        source=f"{input_label(analysis.source) or analysis.source.name} (qPilot study {study_id})",
        prepared=(prepared.study, prepared.space, prepared.space_info, prepared.engine),
    )
    changes, unmapped = chosen_changes(prepared, analysis.inputs.choices)
    table = whatif(prepared.engine, changes)
    table.to_csv(out / "your_choices.csv", index=False)
    flipped = table[table["call"] != table["base_call"]]
    genes = pd.read_csv(out / "genes.csv").set_index("gene")
    verdicts = genes["verdict"].astype(str).to_dict()
    manifest = {
        "kind": "qpilot.simulator_audit",
        "version": 1,
        "study_id": study_id,
        "input_sha256": analysis.input_sha256,
        "chain_head": analysis.inputs.chain_head,
        "design_hash": analysis.inputs.design_hash,
        "source_file": input_label(analysis.source) or analysis.source.name,  # the person's names
        "scope": prepared.scope,
        "reproduces_qpilot": check,
        "lock_sha256": summary.get("lock_sha256"),
        "grid_hash": summary.get("grid_hash"),
        "analyses": summary.get("ledger", {}).get("total_cells"),
        "verdict_counts": summary.get("verdicts", {}).get("counts", {}),
        "your_choices": {
            "changes_from_prespecified": changes,
            "no_simulator_counterpart": unmapped,
            "calls_that_differ": sorted(flipped["gene"]),
        },
        "settings": {
            "permutations": permutations,
            "seed": seed,
            "bench_trials": bench_trials,
            "design_draws": design_draws,
            "explorer": explorer,
        },
        "versions": {"qsim": qsim.__version__, "qpilot": _qpilot_version()},
    }
    (out / MANIFEST).write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    manifest["checksums_sha256"] = _write_checksums(out)
    return AuditResult(
        out_dir=out,
        study_id=study_id,
        manifest=manifest,
        summary=summary,
        verdicts=verdicts,
        your_choices=table,
        seconds=time.perf_counter() - started,
    )


def _qpilot_version() -> str:
    import qpilot

    return qpilot.__version__


# ---------------------------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------------------------


@dataclass
class AuditCheck:
    """The result of :func:`verify_audit`."""

    ok: bool
    problems: list[str]

    def summary(self) -> str:
        """One line: OK, or every problem found."""
        return "audit OK" if self.ok else "audit FAILED: " + "; ".join(self.problems)


def verify_audit(audit_dir: str | Path, record_dir: str | Path | None = None) -> AuditCheck:
    """Check the audit's checksums and manifest; with ``record_dir``, that it is this record's.

    The audit belongs to a record when the record verifies (``qpilot verify``), its study id and
    input sha256 are the audit's, and the record's decision chain contains the audited head.
    """
    root = Path(audit_dir)
    problems: list[str] = []
    sums = root / CHECKSUMS
    if not sums.exists():
        return AuditCheck(False, [f"{CHECKSUMS} missing"])
    listed: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        if not name or len(digest) != 64:
            return AuditCheck(False, [f"malformed line in {CHECKSUMS}"])
        listed[name] = digest
    present = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != CHECKSUMS
    }
    problems += [f"missing: {n}" for n in sorted(set(listed) - present)]
    problems += [f"not in checksums: {n}" for n in sorted(present - set(listed))]
    problems += [
        f"changed: {n}" for n in sorted(set(listed) & present) if sha256_file(root / n) != listed[n]
    ]
    manifest_path = root / MANIFEST
    if not manifest_path.exists():
        return AuditCheck(False, [*problems, f"{MANIFEST} missing"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("reproduces_qpilot", {}).get("ok"):
        problems.append("the audit does not record that it reproduces qPilot's result")
    lock = json.loads((root / "lock.json").read_text()) if (root / "lock.json").exists() else {}
    if lock.get("sha256") != manifest.get("lock_sha256"):
        problems.append("lock.json does not match the manifest")
    if lock.get("input_sha256") != manifest.get("input_sha256"):
        problems.append("lock.json is for another input file")
    if record_dir is not None:
        problems += _record_binding(Path(record_dir), manifest)
    return AuditCheck(not problems, problems)


def _record_binding(record_dir: Path, manifest: dict[str, Any]) -> list[str]:
    from qpilot.core.record import verify

    report = verify(record_dir)
    problems = [] if report.ok else [f"the record does not verify: {report.summary()}"]
    results = record_dir / "results.json"
    if results.exists():
        data = json.loads(results.read_text(encoding="utf-8"))
        if data.get("input_sha256") != manifest.get("input_sha256"):
            problems.append("the record's input file is not the audited one")
        if data.get("study_id") != manifest.get("study_id"):
            problems.append("the record is for another study")
    else:
        problems.append("the record has no results.json")
    log = record_dir / "decisions.jsonl"
    head = manifest.get("chain_head")
    if head and log.exists():
        hashes = {json.loads(line).get("hash") for line in log.read_text().splitlines() if line}
        if head not in hashes:
            problems.append("the audited decision chain head is not in the record's chain")
    return problems


__all__ = [
    "AuditCheck",
    "AuditRefused",
    "AuditResult",
    "NotApplicable",
    "SimulatorUnavailable",
    "audit",
    "available",
    "chosen_changes",
    "load_analysis",
    "prepare",
    "reproduction",
    "verify_audit",
]
