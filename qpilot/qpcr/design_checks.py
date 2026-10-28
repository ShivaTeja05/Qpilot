"""Refute-only checks of proposed study designs, and the two hard bans.

AI proposes. The engine checks. The scientist decides. A check can show that the data
contradict a proposal; it can never confirm one. The best status is ``consistent`` ("nothing
in the data argues against it"), never "correct". Each check returns a
:class:`~qpilot.schemas_studio.ProposalCheck` with its rule ids, its numbers in ``details`` and
plain wording without digits in ``note``. Method cards: ``methods/design_checks.md``.

==============  ==============================================================================
rule            what it can refute
==============  ==============================================================================
``D-SERIES``    a dilution series whose wells do not fall on a line of Cq against log10
                quantity (R² below 0.98); a standard none of whose wells (or dilution level)
                LinRegPCR called amplified. Efficiency outside 90-110 % is only a warning.
``D-NTC``       a no-template, no-RT or no-amplification control that amplifies within five
                cycles of the median Cq of the same plate's unknowns for that target.
``D-REP``       technical replicates whose Cq range exceeds the Poisson-aware tolerance
                ``2.1/ln(E) * sqrt(0.15**2 + 1/N)``; only a warning when N (copies) is unknown.
``D-SYMBOL``    a gene symbol that is not the approved HGNC symbol for the target's name.
``D-COVER``     a role for a sample or well that does not exist, or wells left with no role or
                more than one in the assembled design.
``D-NGUARD``    a comparison in which a group has fewer than two biological units (the
                p-value would be withheld).
``D-AXIS``      a further choice to test (``choice.axis``) whose options are not the axis's
                own, do not start with the analysis in use, or need what the file does not
                have (each well's own efficiency, a dilution series, an amplicon on several
                plates; three reference genes for a best pair, many genes for the global
                mean; a gene split over plates with a calibrator or a shared measurement).
==============  ==============================================================================

**Hard bans** (:func:`hard_ban`) are refused before a proposal is stored, whoever proposes it:
giving a declared or confirmed control (``ntc``, ``nrt``, ``nac``) a non-control role, and
merging or splitting biological units a person already confirmed.

No language model is involved anywhere in this module.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from qpilot.io.rdml_io import RdmlLoadError
from qpilot.io.sheets import SheetError
from qpilot.io.symbols import check_symbol, load_table
from qpilot.qpcr import design_rules
from qpilot.qpcr.curves import CurveAnalysisError
from qpilot.qpcr.inspect import FileFacts, cached_facts, file_facts
from qpilot.schemas_studio import CONTROL_ROLES, Proposal, ProposalCheck

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore

R2_MIN = 0.98
EFFICIENCY_RANGE = (0.90, 1.10)  # E - 1, where E = 10 ** (-1 / slope) is the amplification factor
MIN_LEVELS = 3
NTC_CYCLES = 5.0
TOL_FACTOR = 2.1
TOL_PIPETTING = 0.15
SMALL_REPLICATE_SET = 4
ACCEPTED = ("accepted", "edited")
SAMPLE_ROLES = ("unkn",)  # roles whose samples count as study samples (D-NTC, D-NGUARD)

RULE_IDS = ("D-SERIES", "D-NTC", "D-REP", "D-SYMBOL", "D-COVER", "D-NGUARD", "D-AXIS")


def _check(
    status: str, rule: str, details: dict[str, Any] | None = None, note: str = ""
) -> ProposalCheck:
    return ProposalCheck(status=status, rule_ids=[rule], details=details or {}, note=note)


def _num(value: float | None, digits: int = 6) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def combine(primary: ProposalCheck, *others: ProposalCheck) -> ProposalCheck:
    """One check from several: any contradiction wins; otherwise ``primary`` decides.

    A secondary check that is merely consistent (for example "the sample exists") never turns
    a primary ``cannot_check`` into ``consistent``. ``primary``'s details stay at the top
    level; every other check is kept whole under ``details["checks"][rule_id]``.
    """
    checks = [primary, *others]
    statuses = {c.status for c in checks}
    status = "contradicted" if "contradicted" in statuses else primary.status
    details = dict(primary.details)
    if others:
        details["checks"] = {
            "/".join(c.rule_ids): {"status": c.status, "details": c.details, "note": c.note}
            for c in others
        }
    rule_ids = list(dict.fromkeys(r for c in checks for r in c.rule_ids))
    note = "; ".join(c.note for c in checks if c.note)
    return ProposalCheck(status=status, rule_ids=rule_ids, details=details, note=note)


# ---------------------------------------------------------------------------------------------
# D-SERIES: dilution series and standards
# ---------------------------------------------------------------------------------------------


def _amplified(wells: pd.DataFrame) -> pd.Series:
    """LinRegPCR's amplification call, and a Cq to go with it."""
    return wells["amplification"].astype(bool) & wells["cq"].notna()


def series_check(
    wells: pd.DataFrame,
    quantities: Mapping[str, float],
    *,
    pool: pd.DataFrame | None = None,
    pool_quantities: Mapping[str, float] | None = None,
) -> ProposalCheck:
    """D-SERIES: do the wells of a dilution series fall on a line of Cq against log10 quantity?

    Each plate and target is fitted on its own. A dilution level is used only if at least one
    well at that level, among the series and its ``pool`` (series named by the same scheme on
    the same plate, such as ``comp_00`` ... ``comp_50``), was called amplified by LinRegPCR;
    levels without any are listed in ``levels_without_amplification`` and their late Cqs do
    not count. Within the levels used, every well with a Cq counts, so a stray late Cq argues
    against the line. Contradicted when any plate's R² is below 0.98 or Cq does not fall as
    quantity rises; an efficiency outside 90-110 % (E - 1, with E = 10 ** (-1 / slope)) is a
    warning. Fewer than three levels with a Cq: cannot check.

    Args:
        wells: Curve rows (``run_id``, ``target``, ``sample``, ``cq``, ``amplification``).
        quantities: Sample -> quantity for the proposed series.
        pool: Curve rows of the series' family (defaults to ``wells``).
        pool_quantities: Sample -> quantity for the family (defaults to ``quantities``).
    """
    bad = sorted(s for s, q in quantities.items() if not (isinstance(q, int | float) and q > 0))
    usable = {s: float(q) for s, q in quantities.items() if s not in bad}
    pool = wells if pool is None else pool
    pool_quantities = {**(pool_quantities or {}), **usable}
    rows = wells[wells["sample"].isin(usable)].copy()
    rows["quantity"] = rows["sample"].map(usable)
    family = pool[pool["sample"].isin(pool_quantities)].copy()
    family["quantity"] = family["sample"].map(pool_quantities)
    fits: list[dict[str, Any]] = []
    for (run_id, target), group in rows.groupby(["run_id", "target"], sort=True):
        on_plate = family[(family["run_id"] == run_id) & (family["target"] == target)]
        amplified_levels = set(on_plate.loc[_amplified(on_plate), "quantity"])
        levels = sorted(set(group["quantity"]))
        without = [q for q in levels if q not in amplified_levels]
        used = group[group["quantity"].isin(amplified_levels) & group["cq"].notna()]
        late = group[~group["quantity"].isin(amplified_levels) & group["cq"].notna()]
        fit: dict[str, Any] = {
            "run_id": run_id,
            "target": target,
            "levels": levels,
            "levels_used": sorted(set(used["quantity"])),
            "levels_without_amplification": without,
            "n_wells": int(len(group)),
            "n_wells_used": int(len(used)),
            "n_late_cq_not_counted": int(len(late)),
        }
        if used["quantity"].nunique() < MIN_LEVELS:
            fit["status"] = "cannot_check"
        else:
            x = np.log10(used["quantity"].to_numpy(float))
            y = used["cq"].to_numpy(float)
            slope, intercept = np.polyfit(x, y, 1)
            r2 = float(np.corrcoef(x, y)[0, 1] ** 2) if np.std(y) > 0 else 0.0
            factor = 10 ** (-1.0 / slope) if slope < 0 else None
            efficiency = factor - 1.0 if factor is not None else None
            warning = efficiency is None or not (
                EFFICIENCY_RANGE[0] <= efficiency <= EFFICIENCY_RANGE[1]
            )
            fit.update(
                slope=_num(slope),
                intercept=_num(intercept),
                r2=_num(r2),
                amplification_factor=_num(factor),
                efficiency=_num(efficiency),
                efficiency_fraction_of_doubling=_num(factor / 2 if factor else None),
                efficiency_warning=bool(warning),
                status="contradicted" if (r2 < R2_MIN or slope >= 0) else "consistent",
            )
        fits.append(fit)
    fitted = [f for f in fits if "r2" in f]
    details: dict[str, Any] = {
        "r2_min_required": R2_MIN,
        "efficiency_range": list(EFFICIENCY_RANGE),
        "n_fits": len(fitted),
        "n_fits_contradicted": sum(f["status"] == "contradicted" for f in fits),
        "levels_without_amplification": sorted(
            {q for f in fits for q in f["levels_without_amplification"]}
        ),
        "invalid_quantities": bad,
        "missing_samples": sorted(set(usable) - set(rows["sample"])),
        "fits": fits,
    }
    if fitted:
        r2s = [f["r2"] for f in fitted]
        details.update(
            r2=min(r2s),
            r2_max=max(r2s),
            slope=_num(float(np.median([f["slope"] for f in fitted]))),
            amplification_factor=_num(
                float(np.median([f["amplification_factor"] or np.nan for f in fitted]))
            ),
            efficiency=_num(float(np.median([f["efficiency"] or np.nan for f in fitted]))),
            efficiency_warning=any(f["efficiency_warning"] for f in fitted),
            levels_used=sorted({q for f in fitted for q in f["levels_used"]}),
        )
    if details["missing_samples"] or bad:
        return _check(
            "contradicted",
            "D-SERIES",
            details,
            "the series names samples the file does not have on any plate, or quantities "
            "that are not positive numbers",
        )
    if not fitted:
        return _check(
            "cannot_check",
            "D-SERIES",
            details,
            "fewer than three dilution levels with amplified wells, so no line can be tested",
        )
    if details["n_fits_contradicted"]:
        where = "on some plates " if details["n_fits_contradicted"] < len(fitted) else ""
        return _check(
            "contradicted",
            "D-SERIES",
            details,
            f"{where}the wells do not fall on a line of Cq against the logarithm of quantity",
        )
    note = "the wells fall on a line of Cq against the logarithm of quantity"
    if details["efficiency_warning"]:
        note += "; the efficiency from the slope is outside the usual range (a warning only)"
    if details["levels_without_amplification"]:
        note += "; some dilution levels have no amplified well and were left out of the fit"
    return _check("consistent", "D-SERIES", details, note)


def standard_role_check(
    sample_wells: pd.DataFrame,
    *,
    level_wells: pd.DataFrame | None = None,
) -> ProposalCheck:
    """D-SERIES for a ``std`` role: a standard must have amplified.

    Contradicted when LinRegPCR called none of the sample's wells amplified and, if the sample
    is a level of a named dilution series, no well at that level of the series' family either
    (``level_wells``). A late Cq without an amplification call does not count.
    """
    n_amplified = int(_amplified(sample_wells).sum())
    details: dict[str, Any] = {
        "n_wells": int(len(sample_wells)),
        "n_amplified": n_amplified,
        "n_with_cq": int(sample_wells["cq"].notna().sum()),
    }
    level_amplified = 0
    if level_wells is not None:
        level_amplified = int(_amplified(level_wells).sum())
        details.update(n_level_wells=int(len(level_wells)), n_level_amplified=level_amplified)
    if len(sample_wells) == 0:
        return _check("cannot_check", "D-SERIES", details, "the sample has no wells")
    if n_amplified == 0 and level_amplified == 0:
        return _check(
            "contradicted",
            "D-SERIES",
            details,
            "no well of this sample (nor of its dilution level) was called amplified, so it "
            "cannot serve as a standard",
        )
    if n_amplified == 0:
        return _check(
            "consistent",
            "D-SERIES",
            details,
            "LinRegPCR called none of this sample's wells amplified, but other wells at its "
            "dilution level in the series did",
        )
    return _check("consistent", "D-SERIES", details, "the sample's wells amplify")


# ---------------------------------------------------------------------------------------------
# D-NTC: negative controls
# ---------------------------------------------------------------------------------------------


def ntc_check(
    control_wells: pd.DataFrame,
    plate_wells: pd.DataFrame,
    roles: Mapping[str, str] | None = None,
    *,
    k_cycles: float = NTC_CYCLES,
) -> ProposalCheck:
    """D-NTC: does a proposed negative control behave like a negative control?

    For each control well, the reference is the median Cq of the amplified unknown wells on
    the same plate and target (``roles`` maps sample -> role; default the declared
    ``sample_type``). An amplified control well within ``k_cycles`` of that median (or earlier)
    behaves like a sample: contradicted. Later amplification is consistent, with a note (late
    signal, typical of primer-dimer). A Cq without LinRegPCR's amplification call, or no Cq,
    is consistent. An amplified control on a plate without amplified unknowns cannot be
    judged.

    Args:
        control_wells: Curve rows of the proposed control.
        plate_wells: Curve rows of every well on the plates involved.
        roles: Sample -> role in the design being assembled.
        k_cycles: The MIQE 2.0 margin (five cycles).
    """
    plate_roles = plate_wells["sample"].map(dict(roles or {})).fillna(plate_wells["sample_type"])
    unknown = plate_wells[plate_roles.isin(SAMPLE_ROLES) & _amplified(plate_wells)]
    medians = unknown.groupby(["run_id", "target"])["cq"].median().to_dict()
    classes: dict[str, int] = defaultdict(int)
    signal: list[dict[str, Any]] = []
    for _, well in control_wells.iterrows():
        amplified = bool(well["amplification"]) and pd.notna(well["cq"])
        reference = medians.get((well["run_id"], well["target"]))
        entry = {
            "run_id": well["run_id"],
            "well": well["well"],
            "target": well["target"],
            "cq": _num(well["cq"], 4) if pd.notna(well["cq"]) else None,
            "unknown_median_cq": _num(reference, 4) if reference is not None else None,
        }
        if amplified and reference is None:
            kind = "amplified_no_reference"
        elif amplified:
            gap = float(well["cq"]) - float(reference)
            entry["gap_cycles"] = _num(gap, 4)
            kind = "like_sample" if gap < k_cycles else "late"
        elif pd.notna(well["cq"]):
            kind = "cq_without_amplification_call"
        else:
            kind = "clean"
        classes[kind] += 1
        if kind != "clean":
            signal.append({**entry, "class": kind})
    gaps = [s["gap_cycles"] for s in signal if "gap_cycles" in s]
    details: dict[str, Any] = {
        "k_cycles": k_cycles,
        "n_wells": int(len(control_wells)),
        "n_clean": classes["clean"],
        "n_like_sample": classes["like_sample"],
        "n_late": classes["late"],
        "n_cq_without_amplification_call": classes["cq_without_amplification_call"],
        "n_amplified_no_reference": classes["amplified_no_reference"],
        "min_gap_cycles": min(gaps) if gaps else None,
        "wells_with_signal": signal,
    }
    if len(control_wells) == 0:
        return _check("cannot_check", "D-NTC", details, "the control has no wells")
    if classes["like_sample"]:
        return _check(
            "contradicted",
            "D-NTC",
            details,
            "the control amplifies within the cycle margin of the study samples on its plate; "
            "it behaves like a sample (or is contaminated)",
        )
    judged = len(control_wells) - classes["amplified_no_reference"]
    if judged == 0:
        return _check(
            "cannot_check",
            "D-NTC",
            details,
            "the control amplifies on a plate with no amplified study samples to compare with",
        )
    notes = []
    if classes["amplified_no_reference"]:
        notes.append(
            "some control wells amplify on plates without study samples and were not judged"
        )
    if classes["late"]:
        notes.append("late signal well after the study samples, typical of primer-dimer")
    if classes["cq_without_amplification_call"]:
        notes.append("LinRegPCR found a late Cq but did not call the curve amplified")
    if classes["clean"] == len(control_wells):
        notes.append("the control does not amplify")
    return _check("consistent", "D-NTC", details, "; ".join(notes))


# ---------------------------------------------------------------------------------------------
# D-REP: technical replicates
# ---------------------------------------------------------------------------------------------


def replicate_tolerance(efficiency: float, copies: float | None = None) -> float:
    """Expected Cq range of technical replicates: ``2.1/ln(E) * sqrt(0.15**2 + 1/N)``.

    ``E`` is the amplification factor (about 1.9); ``N`` the copies per reaction. Without
    ``copies`` this is the high-copy limit (pipetting only, about 0.5 cycles at E = 1.9).
    Source: Ruiz-Villalba et al. 2021 (see ``methods/design_checks.md``).
    """
    if efficiency <= 1.0:
        raise ValueError("efficiency must be the amplification factor E > 1")
    poisson = 1.0 / copies if copies else 0.0
    return TOL_FACTOR / math.log(efficiency) * math.sqrt(TOL_PIPETTING**2 + poisson)


def replicate_check(
    wells: pd.DataFrame, copies: Mapping[str, float] | None = None
) -> ProposalCheck:
    """D-REP: do technical replicates (same sample, plate and target) agree within tolerance?

    Only amplified wells count. ``E`` is LinRegPCR's per-target efficiency on the plate. A set
    whose Cq range exceeds the tolerance is reported. It counts against the proposal only when
    the copies per reaction are known (a file quantity in copies) and the set has at most four
    wells; the check is contradicted when such sets are more than half of the sets that could
    be judged that way (the tolerance is a typical range, not a hard limit, so a few
    excursions among many plates are expected). Otherwise (copies unknown, so the high-copy
    limit is used, or a larger set, whose range grows with its size) it is a warning.
    """
    copies = copies or {}
    sets: list[dict[str, Any]] = []
    n_sets = 0
    n_judged = 0
    amplified = wells[_amplified(wells)]
    for (sample, run_id, target), group in amplified.groupby(
        ["sample", "run_id", "target"], sort=True
    ):
        if len(group) < 2:
            continue
        eff = group["eff_target"].dropna()
        eff = eff if len(eff) else group["eff_indiv"].dropna()
        if not len(eff) or float(eff.median()) <= 1.0:
            continue
        efficiency = float(eff.median())
        n_copies = copies.get(sample)
        tol = replicate_tolerance(efficiency, n_copies)
        spread = float(group["cq"].max() - group["cq"].min())
        n_sets += 1
        hard = n_copies is not None and len(group) <= SMALL_REPLICATE_SET
        n_judged += hard
        if spread > tol:
            sets.append(
                {
                    "sample": sample,
                    "run_id": run_id,
                    "target": target,
                    "n": int(len(group)),
                    "range": _num(spread, 4),
                    "tolerance": _num(tol, 4),
                    "efficiency": _num(efficiency, 4),
                    "copies": n_copies,
                    "judged_at_known_copies": bool(hard),
                }
            )
    n_hard = sum(s["judged_at_known_copies"] for s in sets)
    details: dict[str, Any] = {
        "n_sets": n_sets,
        "n_sets_at_known_copies": n_judged,
        "n_over_tolerance": len(sets),
        "n_over_tolerance_at_known_copies": n_hard,
        "copies_known": bool(n_judged),
        "warning": bool(sets),
        "over_tolerance": sets,
        "tolerance_formula": "2.1/ln(E) * sqrt(0.15**2 + 1/N)",
    }
    if n_sets == 0:
        return _check(
            "cannot_check", "D-REP", details, "no set of two or more amplified replicates"
        )
    if n_judged and n_hard * 2 > n_judged:
        return _check(
            "contradicted",
            "D-REP",
            details,
            "most replicate sets differ by more than pipetting and Poisson sampling allow at "
            "the stated copy number",
        )
    if sets:
        return _check(
            "consistent",
            "D-REP",
            details,
            "some replicate sets differ by more than the expected spread (a warning only)",
        )
    return _check("consistent", "D-REP", details, "technical replicates agree within tolerance")


# ---------------------------------------------------------------------------------------------
# D-SYMBOL, D-COVER, D-NGUARD
# ---------------------------------------------------------------------------------------------


def symbol_check(target_name: str, symbol: str) -> ProposalCheck:
    """D-SYMBOL: is ``symbol`` the approved HGNC symbol the target's name points to?

    Contradicted when the proposed symbol is a previous or alias symbol, looks like a date
    Excel made, or when the target's own name resolves to other genes (or is a repeat or
    spike-in assay that has no gene symbol). Cannot check a symbol HGNC does not know (it may
    be non-human). Consistent otherwise.
    """
    table = load_table()
    proposed = check_symbol(symbol, table=table)
    named = check_symbol(target_name, table=table)
    details: dict[str, Any] = {
        "symbol_status": proposed.status,
        "symbol_candidates": list(proposed.candidates),
        "name_status": named.status,
        "name_candidates": list(named.candidates),
    }
    exact_approved = symbol in table.approved
    if proposed.status in ("date_mangled", "number_mangled"):
        return _check(
            "contradicted",
            "D-SYMBOL",
            details,
            "the proposed symbol looks like a value Excel made from a gene name",
        )
    if not exact_approved and proposed.status in ("previous", "alias", "approved"):
        if proposed.status == "approved" and proposed.case_changed:
            return _check(
                "cannot_check",
                "D-SYMBOL",
                details,
                "the symbol matches a human symbol only when letter case is ignored (a "
                "non-human gene?)",
            )
        return _check(
            "contradicted",
            "D-SYMBOL",
            details,
            "the proposed symbol is not the approved HGNC symbol; the approved one is listed",
        )
    if not exact_approved:
        return _check(
            "cannot_check",
            "D-SYMBOL",
            details,
            "HGNC does not know this symbol (it may be non-human or a custom assay)",
        )
    if named.status == "non_gene":
        return _check(
            "contradicted",
            "D-SYMBOL",
            details,
            getattr(named, "note", "")
            or "the target is a repeat or spike-in assay, which has no gene symbol",
        )
    # Not circular: a name that is an alias, matches only ignoring case, or fits several genes
    # does not name the proposed gene by itself, so the lookup that made the proposal cannot
    # also confirm it (``SymbolFinding.identifies``, io/symbols.py; absent in older builds).
    if symbol != target_name and getattr(named, "identifies", None) is False:
        listed = ", ".join(named.candidates[:5]) or "no gene"
        return _check(
            "cannot_check",
            "D-SYMBOL",
            details,
            "the target's name is an alias, or matches only when letter case is ignored; HGNC "
            f"lists it for {listed}; confirm the gene",
        )
    if named.candidates and symbol not in named.candidates:
        return _check(
            "contradicted",
            "D-SYMBOL",
            details,
            "the target's name points to a different gene than the proposed symbol",
        )
    note = "the symbol is approved"
    if named.candidates:
        note += " and matches the target's name"
    else:
        note += "; the target's name itself is not a gene symbol, so only the symbol is checked"
    return _check("consistent", "D-SYMBOL", details, note)


def assemble_roles(
    facts_types: Mapping[str, tuple[tuple[str, str], ...]],
    wells: pd.DataFrame,
    accepted: Iterable[Proposal] = (),
) -> dict[tuple[str, str, str], set[str]]:
    """Every well's role(s) in the assembled design: ``(run_id, well, target)`` -> roles.

    Declared types come first (a per-target type applies to that target's wells), then
    accepted sample-level ``design.well_role`` proposals, then accepted well-level ones
    (subject ``run_id/well``). Each well and target should end with exactly one role
    (D-COVER); a multiplex well may hold a different role per target.
    """
    by_sample: dict[str, set[str]] = defaultdict(set)
    by_well: dict[str, set[str]] = defaultdict(set)
    for proposal in accepted:
        if proposal.kind != "design.well_role" or proposal.status not in ACCEPTED:
            continue
        role = proposal.effective_payload().get("role")
        target = by_well if "/" in proposal.subject else by_sample
        target[proposal.subject].add(str(role))
    out: dict[tuple[str, str, str], set[str]] = {}
    for row in wells[["run_id", "well", "sample", "target"]].itertuples(index=False):
        well = f"{row.run_id}/{row.well}"
        key = (row.run_id, row.well, row.target)
        if well in by_well:
            roles = set(by_well[well])
        elif row.sample in by_sample:
            roles = set(by_sample[row.sample])
        else:
            declared = facts_types.get(row.sample, (("unkn", ""),))
            specific = {t for t, target in declared if target == row.target}
            roles = specific or {t for t, target in declared if not target} or {"unkn"}
        out.setdefault(key, set()).update(roles)
    return out


def coverage_check(
    roles: Mapping[Any, set[str]], subject_wells: Iterable[Any] | None = None
) -> ProposalCheck:
    """D-COVER: every well (and target) has exactly one role.

    ``roles`` comes from :func:`assemble_roles`. With ``subject_wells`` (the keys a proposal is
    about) only those decide the status; the design-wide counts are reported either way.
    """
    without = sorted(k for k, r in roles.items() if not r)
    multiple = sorted(k for k, r in roles.items() if len(r) > 1)
    details: dict[str, Any] = {
        "n_wells": len(roles),
        "n_without_role": len(without),
        "n_with_several_roles": len(multiple),
        "wells_with_several_roles": [_key_text(k) for k in multiple[:50]],
    }
    scope = set(subject_wells) if subject_wells is not None else set(roles)
    if subject_wells is not None:
        details["n_subject_wells"] = len(scope)
        if not scope:
            return _check(
                "contradicted",
                "D-COVER",
                details,
                "no well in the file carries this sample or well",
            )
    if scope & (set(without) | set(multiple)):
        return _check(
            "contradicted",
            "D-COVER",
            details,
            "some wells would have no role or more than one role",
        )
    return _check("consistent", "D-COVER", details, "every well concerned has exactly one role")


def _key_text(key: Any) -> str:
    """``("P1", "A1", "MYCN")`` -> ``"P1/A1 (MYCN)"``; other keys as text."""
    if isinstance(key, tuple) and len(key) == 3:
        return f"{key[0]}/{key[1]} ({key[2]})"
    return str(key)


def nguard_check(
    group_a: str,
    group_b: str,
    groups: Mapping[str, str],
    units: Mapping[str, str],
    roles: Mapping[str, str] | None = None,
) -> ProposalCheck:
    """D-NGUARD: does each group of a comparison have at least two biological units?

    Only study samples (role ``unkn``) count; technical replicates and several samples of one
    unit count once. A group with exactly one unit contradicts (the engine would withhold the
    p-value); a group with no confirmed samples yet cannot be checked.
    """
    roles = roles or {}

    def units_of(group: str) -> set[str]:
        return {
            units.get(sample, sample)
            for sample, g in groups.items()
            if g == group and roles.get(sample, "unkn") in SAMPLE_ROLES
        }

    a, b = units_of(group_a), units_of(group_b)
    details = {"n_units_a": len(a), "n_units_b": len(b), "min_units": 2}
    if group_a == group_b:
        return _check("contradicted", "D-NGUARD", details, "the comparison names one group twice")
    if 0 < len(a) < 2 or 0 < len(b) < 2:
        return _check(
            "contradicted",
            "D-NGUARD",
            details,
            "a group has fewer than two biological units, so the p-value would be withheld",
        )
    if not a or not b:
        return _check(
            "cannot_check",
            "D-NGUARD",
            details,
            "a group has no confirmed study samples yet",
        )
    return _check("consistent", "D-NGUARD", details, "each group has at least two biological units")


# ---------------------------------------------------------------------------------------------
# Hard bans
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DeclaredDesign:
    """What the file and the sample sheet already fix, for the hard bans.

    Attributes:
        controls: Samples every declared type of which is a control (``ntc``/``nrt``/``nac``).
        control_wells: ``run_id/well`` keys whose declared role is a control.
        well_samples: ``run_id/well`` -> sample.
        sheet_units: Sample -> biological unit from the sheet's explicit unit column.
    """

    controls: frozenset[str] = frozenset()
    control_wells: frozenset[str] = frozenset()
    well_samples: Mapping[str, str] = field(default_factory=dict)
    sheet_units: Mapping[str, str] = field(default_factory=dict)


Resolved = Path | tuple[Path, Path | None] | None  # the input, or (input, sample sheet)
_DECLARED: dict[str, DeclaredDesign] = {}
_RESOLVER: list[Callable[[str], Resolved]] = []


_DECLARED_BY_INPUT: dict[tuple[str, str | None], DeclaredDesign] = {}


def declared_design(facts: FileFacts) -> DeclaredDesign:
    """The controls and sheet units an input fixes (see :class:`DeclaredDesign`); memoised."""
    key = (facts.sha256, facts.sheet.sha256 if facts.sheet else None)
    if key not in _DECLARED_BY_INPUT:
        _DECLARED_BY_INPUT[key] = _declared_design(facts)
    return _DECLARED_BY_INPUT[key]


def _declared_design(facts: FileFacts) -> DeclaredDesign:
    controls = frozenset(
        sample
        for sample, types in facts.sample_types.items()
        if types and all(t in CONTROL_ROLES for t, _ in types)
    )
    roles = assemble_roles(facts.sample_types, facts.wells)
    control_wells = frozenset(
        f"{run}/{well}" for (run, well, _), r in roles.items() if r & CONTROL_ROLES
    )
    well_samples = {
        f"{r.run_id}/{r.well}": r.sample
        for r in facts.wells[["run_id", "well", "sample"]].itertuples(index=False)
    }
    units = design_rules.sheet_units(facts.summary, facts.quarantine) if facts.sheet else {}
    return DeclaredDesign(
        controls=controls,
        control_wells=control_wells,
        well_samples=well_samples,
        sheet_units=units,
    )


def register_declared(study_id: str, source: FileFacts | DeclaredDesign | str | Path) -> None:
    """Tell the hard bans what a study's input fixes.

    ``source`` is the input's :class:`~qpilot.qpcr.inspect.FileFacts`, an RDML path, or a
    ready :class:`DeclaredDesign`. :func:`check_proposal` registers automatically; call this
    when a session or study is created if proposals may arrive before any check.
    """
    if isinstance(source, DeclaredDesign):
        _DECLARED[study_id] = source
    elif isinstance(source, FileFacts):
        _DECLARED[study_id] = declared_design(source)
    else:
        _DECLARED[study_id] = declared_design(file_facts(source))


def set_input_resolver(resolver: Callable[[str], Resolved] | None) -> None:
    """Install how :func:`hard_ban` finds a study's input when nothing is registered.

    The resolver returns the input file, or ``(input file, sample sheet or None)`` so the
    sheet's unit column counts; ``None`` when the input (or its bound sheet) is not available,
    and then the bans fail closed.
    """
    _RESOLVER.clear()
    if resolver is not None:
        _RESOLVER.append(resolver)


def _declared_for(study_id: str) -> DeclaredDesign | None:
    if study_id in _DECLARED:
        return _DECLARED[study_id]
    if _RESOLVER:
        # The resolver knows the session's own sheet; facts cached for another sheet (or for
        # none) would hide the units a person wrote in it.
        try:
            found = _RESOLVER[0](study_id)
            path, sheet = found if isinstance(found, tuple) else (found, None)
            facts = file_facts(path, sheet) if path is not None else None
        except (RdmlLoadError, SheetError, CurveAnalysisError, OSError, KeyError):
            facts = None
    else:
        hexadecimal = all(c in "0123456789abcdef" for c in study_id)
        facts = cached_facts(study_id) if hexadecimal else None
    if facts is None:
        return None
    _DECLARED[study_id] = declared_design(facts)
    return _DECLARED[study_id]


def hard_ban(proposal: Proposal, current: list[Proposal]) -> str | None:
    """The reason a proposal must be refused outright, or ``None``. Independent of who proposes.

    (a) A sample or well the file declares as ``ntc``/``nrt``/``nac``, or a person accepted as
    one, may not get a non-control role: not by ``design.well_role``, not as a member of a
    ``design.dilution_series``, and not by joining a ``design.group`` or ``design.bio_unit``
    (that would make it a study sample). When the input's declared types are not known in this
    process, role and series proposals are refused (fail closed) until they are.

    (b) A ``design.bio_unit`` proposal may not move a sample out of a biological unit a person
    confirmed (an accepted proposal, or the sheet's explicit unit column): that merges or
    splits confirmed units. When the input and its sheet are not known in this process, unit
    proposals are refused (fail closed) until they are. The one exception is a person's own
    change on the Design page (``made_by.kind == "person"``, which only ``actor="human"`` can
    propose): a person may correct a unit they or their sheet set, with a reason; no rule,
    model or agent ever can.

    A ``design.dilution_series`` must list its samples as an object of sample to quantity; any
    other shape is refused, so no member can slip past (a).

    Args:
        proposal: The proposal about to be stored.
        current: The study's proposals so far (any status; only accepted ones count).
    """
    declared = _declared_for(proposal.study_id)
    accepted = [
        p
        for p in current
        if p.status in ACCEPTED and p is not proposal and not (proposal.id and p.id == proposal.id)
    ]
    payload = proposal.effective_payload()
    controls = set(declared.controls) if declared else set()
    control_wells = set(declared.control_wells) if declared else set()
    well_samples = dict(declared.well_samples) if declared else {}
    for p in accepted:
        if p.kind == "design.well_role" and p.effective_payload().get("role") in CONTROL_ROLES:
            (control_wells if "/" in p.subject else controls).add(p.subject)

    def is_control(subject: str) -> bool:
        if subject in controls or subject in control_wells:
            return True
        if "/" in subject:
            return well_samples.get(subject) in controls
        return any(well_samples.get(w) == subject for w in control_wells)

    kind = proposal.kind
    demotes = kind == "design.dilution_series" or (
        kind == "design.well_role" and payload.get("role") not in CONTROL_ROLES
    )
    if demotes and declared is None:
        return (
            "refused: the engine has not read this study's input file yet, so it cannot make "
            "sure the proposal does not demote a control"
        )
    if kind == "design.bio_unit" and declared is None:
        return (
            "refused: the engine has not read this study's input file and sample sheet yet, so "
            "it cannot make sure the proposal does not merge or split a confirmed unit"
        )
    if kind == "design.well_role" and payload.get("role") not in CONTROL_ROLES:
        if is_control(proposal.subject):
            return (
                "refused: this sample or well is a control (no template, no RT or no "
                "amplification) in the file or by a person's decision; a control is never "
                "given another role"
            )
    if kind == "design.dilution_series":
        members = payload.get("samples")
        if not isinstance(members, Mapping) or not members:
            return "refused: a dilution series lists its samples as an object of sample to quantity"
        if any(is_control(str(s)) for s in members):
            return "refused: a dilution series may not include a declared or confirmed control"
    if kind in ("design.group", "design.bio_unit") and is_control(proposal.subject):
        return "refused: a control cannot join a biological group or unit"
    if kind == "design.bio_unit" and proposal.made_by.kind != "person":
        unit = payload.get("biological_unit")
        confirmed = dict(declared.sheet_units) if declared else {}
        for p in accepted:
            if p.kind == "design.bio_unit":
                confirmed[p.subject] = str(p.effective_payload().get("biological_unit"))
        current_unit = confirmed.get(proposal.subject)
        if current_unit is not None and unit != current_unit:
            joins = any(u == unit for s, u in confirmed.items() if s != proposal.subject)
            what = "merges two confirmed units" if joins else "splits a confirmed unit"
            return (
                f"refused: this {what}; a person already confirmed this sample's biological "
                "unit, and units are never merged or split by a proposal"
            )
    return None


# ---------------------------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------------------------


def _source(store: StudyStore, study_id: str) -> Path | None:
    try:
        return store.source(study_id)
    except (KeyError, OSError, ValueError):
        return None


def check_proposal(
    proposal: Proposal,
    store: StudyStore,
    study_id: str,
    *,
    rdml_path: Path | None = None,
    accepted: list[Proposal] | None = None,
    sheet_path: Path | None = None,
) -> ProposalCheck:
    """The engine's refute-only check of one proposal (never stores anything).

    Args:
        proposal: The proposal to check.
        store: The study store; ``store.source(study_id)`` gives the input file when
            ``rdml_path`` is not given.
        study_id: The study (or Studio session) the proposal belongs to.
        rdml_path: The input file, when the proposal belongs to a session without a study.
        accepted: The proposals a person accepted so far (the assembled design), for D-COVER,
            D-NGUARD and the roles D-NTC compares against.
        sheet_path: The sample sheet, if the study has one.

    Returns:
        A :class:`~qpilot.schemas_studio.ProposalCheck`; ``cannot_check`` with a note when the
        input is not available or the kind has no engine check.
    """
    path = Path(rdml_path) if rdml_path is not None else _source(store, study_id)
    if path is None:
        return ProposalCheck(
            status="cannot_check", note="the input file is not available to the engine"
        )
    if proposal.kind == "curve.import_trust":
        return trust_check(proposal, store, study_id, path)
    try:
        facts = file_facts(path, sheet_path)
    except (RdmlLoadError, SheetError, CurveAnalysisError) as err:
        return ProposalCheck(
            status="cannot_check",
            details={"error": type(err).__name__},
            note="the engine could not read the input file",
        )
    _DECLARED[study_id] = declared_design(facts)
    return check_with_facts(proposal, facts, accepted=accepted)


def trust_check(
    proposal: Proposal, store: StudyStore, session_id: str, path: Path
) -> ProposalCheck:
    """``D-TRUST`` for an option of the Import Trust card (:func:`qpilot.io.trust.check`).

    The verdict is the one the session's import was read with; the instrument's Cq values are
    counted in the file the session opened (the RDML file the export was written to).
    """
    from qpilot.core.store import StudyNotFound
    from qpilot.io import trust
    from qpilot.io.rdml_io import load
    from qpilot.qpcr.curves import instrument_cq

    if proposal.subject != trust.SUBJECT:
        return _check("contradicted", trust.RULE_ID, {}, "the card is about the import as a whole")
    try:
        verdict = trust.session_verdict(store.find_session(session_id))
    except StudyNotFound:
        verdict = None
    try:
        n_cq = len(instrument_cq(load(path), None))
    except (RdmlLoadError, CurveAnalysisError, KeyError, ValueError):
        n_cq = 0
    return trust.check(proposal.effective_payload().get("option"), verdict, n_cq)


def check_with_facts(
    proposal: Proposal, facts: FileFacts, *, accepted: list[Proposal] | None = None
) -> ProposalCheck:
    """:func:`check_proposal` once the input's facts are loaded (tests call this directly)."""
    accepted = [p for p in (accepted or []) if p.status in ACCEPTED]
    payload = proposal.effective_payload()
    kind = proposal.kind
    wells = facts.wells
    if kind == "design.well_role":
        return _check_role(proposal, payload, facts, accepted)
    if kind == "design.dilution_series":
        return _check_series(payload, facts)
    if kind == "design.gene_symbol":
        known = {t.target for t in facts.summary.targets}
        if proposal.subject not in known:
            return _check("contradicted", "D-COVER", {}, "no target in the file has this name")
        original = facts.quarantined(facts.target_text_ids[proposal.subject]) or proposal.subject
        if design_rules.is_placeholder_name(original) or design_rules.is_placeholder_name(
            proposal.subject
        ):
            return _check(
                "cannot_check",
                "D-SYMBOL",
                {"placeholder": True},
                "the target's name is a placeholder (a role, a control or a dye), not a gene "
                "name, so no gene symbol can be checked against it",
            )
        return symbol_check(original, str(payload.get("symbol", "")))
    if kind == "design.comparison":
        groups, units = _groups_and_units(accepted)
        roles = _sample_roles(facts, accepted)
        return nguard_check(
            str(payload.get("group_a", "")), str(payload.get("group_b", "")), groups, units, roles
        )
    if kind in ("design.group", "design.bio_unit"):
        if proposal.subject not in set(wells["sample"]):
            return _check("contradicted", "D-COVER", {}, "no well in the file carries this sample")
        return ProposalCheck(
            status="cannot_check",
            rule_ids=["D-COVER"],
            details={"sample_found": True},
            note="the sample exists; no engine check can test its group or unit",
        )
    if kind == "design.target_role":
        if proposal.subject not in {t.target for t in facts.summary.targets}:
            return _check("contradicted", "D-COVER", {}, "no target in the file has this name")
        return ProposalCheck(
            status="cannot_check", note="no engine check can test a target's role on its own"
        )
    if kind == "curve.well_call":
        return curve_check(proposal.subject, payload, wells)
    if kind == "curve.exclude_well":
        return exclusion_check(proposal.subject, payload, wells)
    if kind == "choice.axis":
        return axis_check(proposal.subject, payload, wells, accepted)
    return ProposalCheck(status="cannot_check", note="no engine check exists for this kind")


def axis_check(
    subject: str, payload: Mapping[str, Any], wells: pd.DataFrame, accepted: list[Proposal]
) -> ProposalCheck:
    """``D-AXIS``: a further choice to test, refuted when its options cannot be what they say.

    The options must be the axis's own, primary first, each once
    (:func:`qpilot.qpcr.designs.axis_options`). For the efficiency models the file must also
    have what each option needs: study wells with their own efficiency inside LinRegPCR's
    valid range (``per_well``), a dilution series of at least three levels (``standard_curve``;
    standards typed in the file, named ``STD_<copies>``, or in an accepted dilution series) and
    an amplicon measured on more than one plate (``amplicon_mean``). This reads the whole file;
    which options apply to the analysed experiment is said again when the study is analysed.
    """
    from qpilot.qpcr.axes import efficiency as eff_axis
    from qpilot.qpcr.designs import DesignError, axis_options

    try:
        options = axis_options(subject, payload.get("options"))
    except DesignError as err:
        return _check(
            "contradicted",
            "D-AXIS",
            {"problem": str(err)},
            "the options are not this choice's own: they start with the analysis in use and "
            "name each of the choice's options at most once",
        )
    if subject == "normaliser":
        return _normaliser_axis_check(options, wells, accepted)
    if subject == "interrun":
        return _interrun_axis_check(options, wells)
    table, quantities = wells, {}
    for p in accepted:
        if p.kind == "design.dilution_series":
            for sample, quantity in dict(p.effective_payload().get("samples") or {}).items():
                quantities[str(sample)] = float(quantity)
    if quantities:
        series = table["sample"].astype(str).isin(set(quantities))
        table = table.assign(sample_type=table["sample_type"].where(~series, "std"))
    curves = eff_axis.standard_curves(table, quantities)
    missing = set(eff_axis.unavailable(table, curves))
    study = table[(table["sample_type"] == "unkn") & table["n0"].notna()]
    own = pd.to_numeric(study["eff_indiv"], errors="coerce")
    low, high = eff_axis.E_VALID
    valid = own[np.isfinite(own) & (own > low) & (own < high)]
    if valid.empty:
        missing.add("per_well")
    details: dict[str, Any] = {
        "options": list(options),
        "study_wells_with_a_quantity": len(study),
        "own_efficiency_in_valid_range": len(valid),
        "own_efficiency_outside_valid_range": len(study) - len(valid),
        "own_efficiency_median": _num(float(valid.median())) if len(valid) else None,
        "dilution_series_with_three_levels": len(curves),
    }
    refuted = [o for o in options if o in missing]
    if refuted:
        details["not_in_the_file"] = refuted
        return _check(
            "contradicted", "D-AXIS", details, "; ".join(_AXIS_MISSING[o] for o in refuted)
        )
    return _check(
        "consistent",
        "D-AXIS",
        details,
        "each option is the choice's own and the file has what it needs; which options apply "
        "to the analysed experiment is said again when the study is analysed",
    )


def _refuted(options: Sequence[str], missing: Mapping[str, str], details: dict) -> ProposalCheck:
    """``D-AXIS`` from the options the file cannot give (option -> why, in plain words)."""
    refuted = [o for o in options if o in missing]
    if refuted:
        details["not_in_the_file"] = refuted
        return _check("contradicted", "D-AXIS", details, "; ".join(missing[o] for o in refuted))
    return _check(
        "consistent",
        "D-AXIS",
        details,
        "each option is the choice's own and the file has what it needs; which options apply "
        "to the analysed experiment is said again when the study is analysed",
    )


def _reference_targets(accepted: list[Proposal]) -> set[str] | None:
    """The targets the accepted proposals make reference genes (``None``: a preset decides)."""
    refs: dict[str, bool] = {}
    for p in accepted:
        if p.kind == "design.preset":
            return None
        if p.kind == "design.target_role":
            refs[p.subject] = p.effective_payload().get("role") == "ref"
    return {t for t, is_ref in refs.items() if is_ref}


def _normaliser_axis_check(
    options: Sequence[str], wells: pd.DataFrame, accepted: list[Proposal]
) -> ProposalCheck:
    """``D-AXIS`` for the normaliser: what a best pair and the global mean need.

    A best pair needs three reference genes; the global mean needs many genes with study wells
    (:data:`qpilot.qpcr.axes.normaliser.GLOBAL_MEAN_MIN_GENES`).
    """
    from qpilot.qpcr.axes.normaliser import GLOBAL_MEAN_MIN_GENES

    study = wells[(wells["sample_type"] == "unkn") & wells["n0"].notna()]
    n_genes = int(study["target"].nunique())
    refs = _reference_targets(accepted)
    missing: dict[str, str] = {}
    if refs is not None and len(refs) < 3:
        why = "a best pair needs at least three reference genes, and fewer are accepted"
        missing.update({"normfinder_pair": why, "genorm_pair": why})
    if n_genes < GLOBAL_MEAN_MIN_GENES:
        missing["global_mean"] = (
            "the file measures too few genes for a global mean (qPilot asks for fifty)"
        )
    details: dict[str, Any] = {
        "options": list(options),
        "genes_with_study_wells": n_genes,
        "global_mean_min_genes": GLOBAL_MEAN_MIN_GENES,
        "reference_genes_accepted": None if refs is None else sorted(refs),
    }
    return _refuted(options, missing, details)


def _interrun_axis_check(options: Sequence[str], wells: pd.DataFrame) -> ProposalCheck:
    """``D-AXIS`` for the correction between plates: what each correction needs.

    A gene's study wells must be split over plates, and the option needs a calibrator on each
    of its plates (``calibrator``) or a measurement two plates share (``factor``).
    """
    from qpilot.qpcr import interrun as irc

    table = wells[["run_id", "sample", "sample_type", "target", "n0"]].copy()
    table["n0"] = pd.to_numeric(table["n0"], errors="coerce")
    missing = irc.unavailable(table)
    summary = irc.summary(table)
    details: dict[str, Any] = {
        "options": list(options),
        "plates": summary["n_runs"],
        "genes_split_over_plates": summary["n_split_targets"],
        "genes_with_a_calibrator_on_each_plate": len(summary["calibrators"]),
        "plate_pairs_sharing_a_measurement": summary["n_plate_pairs_sharing"],
    }
    return _refuted(options, missing, details)


#: Why the file cannot give an efficiency model, in words without digits.
_AXIS_MISSING = {
    "per_well": "no study well has its own efficiency inside LinRegPCR's valid range",
    "amplicon_mean": "every amplicon is on one plate, so one efficiency per amplicon is "
    "LinRegPCR's own",
    "standard_curve": "no amplicon has a dilution series with at least three levels",
}


def curve_check(subject: str, payload: Mapping[str, Any], wells: pd.DataFrame) -> ProposalCheck:
    """``D-CURVE``: LinRegPCR's own fit refutes a well call only when it is unambiguous.

    A call "not amplified" is contradicted by a well LinRegPCR fitted completely (an
    exponential phase, a plateau and a quantity); a call "amplified" is contradicted by a well
    where LinRegPCR found no exponential phase and no quantity. Anything in between (a late
    curve without a plateau, a quantity without LinRegPCR's own amplification call) is
    ``consistent``: the curve itself has to be looked at.
    """
    if "/" not in subject:
        return _check("contradicted", "D-CURVE", {}, "a well call names a well as run/well")
    rows = _subject_wells(subject, wells)
    if rows.empty:
        return _check("contradicted", "D-COVER", {}, "no well in the file has this position")
    claim = payload.get("amplified")
    if not isinstance(claim, bool):
        return _check("contradicted", "D-CURVE", {}, "a well call is amplified true or false")
    row = rows.iloc[0]
    has_quantity = bool(pd.notna(row["n0"]))
    fitted = bool(row["amplification"]) and bool(row["plateau"]) and has_quantity
    absent = not bool(row["amplification"]) and not has_quantity
    details = {
        "linregpcr_amplification": bool(row["amplification"]),
        "linregpcr_plateau": bool(row["plateau"]),
        "linregpcr_quantity": has_quantity,
        "cq": None if pd.isna(row["cq"]) else round(float(row["cq"]), 4),
        "eff_indiv": None if pd.isna(row["eff_indiv"]) else round(float(row["eff_indiv"]), 4),
    }
    if (claim is False and fitted) or (claim is True and absent):
        note = (
            "LinRegPCR fitted a complete amplification curve in this well"
            if claim is False
            else "LinRegPCR found no exponential phase in this well"
        )
        return _check("contradicted", "D-CURVE", details, note)
    return _check("consistent", "D-CURVE", details, "the curve itself has to be looked at")


def exclusion_check(subject: str, payload: Mapping[str, Any], wells: pd.DataFrame) -> ProposalCheck:
    """``D-COVER`` for a well left out of (or put back into) the analysis.

    The engine can refute only the form: no such well in the file, or an answer that is not
    true or false. Whether a well should be left out is a person's decision on the evidence the
    proposal cites (a Run Gate rule, a curve); the best this check says is ``consistent``.
    """
    if "/" not in subject:
        return _check("contradicted", "D-COVER", {}, "a well is named as run/well")
    rows = _subject_wells(subject, wells)
    if rows.empty:
        return _check("contradicted", "D-COVER", {}, "no well in the file has this position")
    excluded = payload.get("excluded")
    if not isinstance(excluded, bool):
        return _check("contradicted", "D-COVER", {}, "a well is left out: true or false")
    details = {
        "well_found": True,
        "targets": sorted({str(t) for t in rows["target"]}),
        "declared_type": str(rows.iloc[0]["sample_type"]),
    }
    return _check(
        "consistent", "D-COVER", details, "the well is in the file; leaving it out is a decision"
    )


def _sample_roles(facts: FileFacts, accepted: list[Proposal]) -> dict[str, str]:
    """Sample -> role: the declared type (for every target), overridden by accepted roles."""
    roles = {
        sample: next((t for t, target in types if not target), "unkn")
        for sample, types in facts.sample_types.items()
    }
    for p in accepted:
        if p.kind == "design.well_role" and "/" not in p.subject:
            roles[p.subject] = str(p.effective_payload().get("role"))
    return roles


def _groups_and_units(accepted: list[Proposal]) -> tuple[dict[str, str], dict[str, str]]:
    groups: dict[str, str] = {}
    units: dict[str, str] = {}
    for p in accepted:  # a later decision on the same sample wins; None takes the value away
        if p.kind not in ("design.group", "design.bio_unit"):
            continue
        into, key = (groups, "group") if p.kind == "design.group" else (units, "biological_unit")
        value = p.effective_payload().get(key)
        if value is None:
            into.pop(p.subject, None)
        else:
            into[p.subject] = str(value)
    return groups, units


def _copies(facts: FileFacts) -> dict[str, float]:
    """Sample -> copies per reaction, where the file declares one quantity in copies."""
    out = {}
    for sample, quantities in facts.sample_quantities.items():
        values = {v for v, unit, _ in quantities if unit == "cop" and v > 0}
        if len(values) == 1:
            out[sample] = values.pop()
    return out


def _subject_wells(subject: str, wells: pd.DataFrame) -> pd.DataFrame:
    if "/" in subject:
        run_id, _, well = subject.rpartition("/")
        return wells[(wells["run_id"] == run_id) & (wells["well"] == well)]
    return wells[wells["sample"] == subject]


def _check_role(
    proposal: Proposal, payload: Mapping[str, Any], facts: FileFacts, accepted: list[Proposal]
) -> ProposalCheck:
    role = str(payload.get("role", ""))
    wells = facts.wells
    own = _subject_wells(proposal.subject, wells)
    others = [
        p for p in accepted if not (p.kind == proposal.kind and p.subject == proposal.subject)
    ]
    roles = assemble_roles(
        facts.sample_types, wells, [*others, proposal.model_copy(update={"status": "accepted"})]
    )
    keys = list(own[["run_id", "well", "target"]].itertuples(index=False, name=None))
    cover = coverage_check(roles, keys)
    if cover.status == "contradicted" or own.empty:
        return cover
    if role in CONTROL_ROLES:
        plates = wells[wells["run_id"].isin(own["run_id"].unique())]
        sample_roles = _sample_roles(facts, others)
        primary = ntc_check(own, plates, sample_roles)
        return combine(primary, cover)
    rep = replicate_check(own, _copies(facts))
    if role == "std":
        level = _level_wells(proposal.subject, facts)
        primary = standard_role_check(own, level_wells=level)
        return combine(primary, rep, cover)
    return combine(rep, cover)


def _family_of(samples: Iterable[str], facts: FileFacts) -> list[design_rules.Series]:
    """The detected dilution series sharing a naming family with any of ``samples``."""
    detected = design_rules.find_dilution_series(facts.summary, facts.quarantine, facts=facts)
    wanted = set(samples)
    families = {s.family for s in detected if wanted & set(s.samples)}
    return [s for s in detected if s.family in families]


def _level_wells(sample: str, facts: FileFacts) -> pd.DataFrame | None:
    """Wells at the same dilution level as ``sample`` across its series family, or ``None``."""
    family = _family_of([sample], facts)
    quantity = next((s.samples[sample] for s in family if sample in s.samples), None)
    if quantity is None:
        return None
    peers = {name for s in family for name, q in s.samples.items() if q == quantity}
    own = facts.wells[facts.wells["sample"] == sample]
    return facts.wells[
        facts.wells["sample"].isin(peers)
        & facts.wells["run_id"].isin(own["run_id"].unique())
        & facts.wells["target"].isin(own["target"].unique())
    ]


def _check_series(payload: Mapping[str, Any], facts: FileFacts) -> ProposalCheck:
    samples = payload.get("samples") or {}
    if not isinstance(samples, Mapping) or not samples:
        return _check("contradicted", "D-SERIES", {}, "the series lists no samples")
    experiment = payload.get("experiment_id")
    wells = facts.wells
    if experiment:
        wells = wells[wells["experiment_id"] == experiment]
    quantities: dict[str, Any] = dict(samples)
    family = _family_of(quantities, facts)
    pool_quantities = {name: q for s in family for name, q in s.samples.items()}
    primary = series_check(wells, quantities, pool=wells, pool_quantities=pool_quantities)
    primary.details["family_series"] = sorted(s.subject for s in family)
    in_series = wells[wells["sample"].isin(quantities)]
    rep = replicate_check(in_series, _copies(facts))
    return combine(primary, rep)


__all__ = [
    "R2_MIN",
    "RULE_IDS",
    "DeclaredDesign",
    "assemble_roles",
    "axis_check",
    "check_proposal",
    "check_with_facts",
    "combine",
    "coverage_check",
    "declared_design",
    "hard_ban",
    "nguard_check",
    "ntc_check",
    "register_declared",
    "replicate_check",
    "replicate_tolerance",
    "series_check",
    "set_input_resolver",
    "standard_role_check",
    "symbol_check",
]
