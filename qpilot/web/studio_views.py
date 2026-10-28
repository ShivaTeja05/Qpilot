"""Studio's views for the page: the plate, a well's curve, quarantined text, proposal cards.

Built from :class:`~qpilot.studio_service.Studio` and the file's facts, never HTML. The blind
rule is applied here, once: nothing that pairs a group with a number leaves this module before
the design and the curves are confirmed (the plate shows curve numbers only once the design is
confirmed, and a well's group only once results are visible).

The refusal words of the earlier Studio page live here too (:data:`WORDS`), so the page and any
other client get the same sentences.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd

from qpilot.schemas_studio import Proposal, ProposalOutcome
from qpilot.studio_service import BLIND_STAGES, CURVE_JUDGE_FILE, CURVE_JUDGE_LISTED, Studio
from qpilot.web.contract import (
    CurveSeries,
    CurveView,
    EvidenceView,
    ModelSeen,
    PlateRun,
    PlateView,
    PlateWell,
    ProposalView,
    QuarantineView,
    StageView,
)

WELL = re.compile(r"^([A-Z]{1,2})(\d{1,3})\Z")
KEY = re.compile(r"^[A-Za-z0-9_\-.() ]{1,128}/[A-Z]{1,2}\d{1,3}\Z")
PROPOSAL_ID = re.compile(r"^p_[0-9a-f]{16}\Z")
MAX_REPLICATES = 12
MAX_PAYLOAD_CHARS = 200_000
AI_MAKERS = ("model", "agent")
DECIDED = ("accepted", "edited", "rejected")

#: The earlier Studio page's sentences, kept word for word where they still apply.
WORDS = {
    "reject_reason": "Give a reason to reject (it is kept in the record).",
    "exclusion_reason": (
        "Say why this value was excluded in Prism (the reason is kept in the record)."
    ),
    "reason:prism.exclusion_reason": (
        "Say why this value was excluded in Prism (the reason is kept in the record)."
    ),
    "reason:curve.exclude_well": (
        "Say why this well is left out of the analysis, or put back (the reason is kept in "
        "the record)."
    ),
    "reason:curve.import_trust": (
        "Say why the imported curves are used this way (the reason is kept in the record)."
    ),
    "edit_nothing": "Nothing was changed; use Accept to accept the proposal as it is.",
    "edit_not_object": "The edited payload must be a JSON object; nothing was changed.",
    "stale": (
        "The inbox changed since this page showed it (another tab or an agent). Here is the "
        "current inbox: please look again, then decide."
    ),
    "bulk_none": "No waiting proposal of this stage is consistent with the engine's check.",
    "bulk_show": (
        "Check the list; only these are accepted, and only when you press the button under it. "
        "Contradicted and cannot-check proposals are never on this list."
    ),
    "reject_none": "No waiting proposal of this stage (in this list) is contradicted by the "
    "engine's check.",
    "reject_show": (
        "Check the list and give one reason; only these are rejected, and only when you press "
        "the button."
    ),
    "reject_all_reason": "Give the reason for rejecting them (it is kept with each one).",
    "list_changed": (
        "The list changed since it was shown (another tab or an agent decided something). "
        "Here is the current list: please look again."
    ),
    "matters_unknown": "The engine cannot tell yet: the rest of the design does not run.",
    "seen_none": "No model call yet in this qPilot process.",
    "seen_hidden": (
        "Hidden: the design or the curves are not confirmed (again) yet, and the last model call "
        "did not come from the Design Interpreter, so what it was sent may include results."
    ),
    "seen_shown": "The last model call in this qPilot process, exactly as it was sent.",
    "curves_hidden": (
        "Cq, efficiency, R² and the amplification calls are shown once the design is confirmed."
    ),
    "curves_shown": (
        "LinRegPCR's numbers per well (with any call a person accepted); the Curve Judge's call "
        "where it ran on this file."
    ),
    "curve_note": (
        "Raw fluorescence as exported by the instrument, by cycle. LinRegPCR's baseline is in "
        "the same units as the fluorescence; the Cq is a cycle."
    ),
}


def finite(value: Any) -> float | None:
    """A finite float, or None (NaN, inf, missing)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def well_position(label: str) -> tuple[int | None, int | None]:
    """``B3`` -> (2, 3); anything else -> (None, None)."""
    match = WELL.match(label or "")
    if not match:
        return None, None
    letters, digits = match.groups()
    row = 0
    for ch in letters:
        row = row * 26 + (ord(ch) - ord("A") + 1)
    return row, int(digits)


def plate_shape(positions: Iterable[tuple[int | None, int | None]]) -> tuple[int, int]:
    """Rows and columns of the smallest usual plate that holds every position."""
    rows = [r for r, _ in positions if r]
    cols = [c for _, c in positions if c]
    max_r, max_c = max(rows, default=0), max(cols, default=0)
    for n_rows, n_cols in ((8, 12), (16, 24), (32, 48)):
        if max_r <= n_rows and max_c <= n_cols:
            return n_rows, n_cols
    return max_r, max_c


def stage_views(studio: Studio, sid: str) -> list[StageView]:
    """Every stage's status as the contract's model (the frame's own counting)."""
    from qpilot.web.views import stage_views as frame_stages

    return frame_stages(studio, sid)


def describe(proposal: Proposal, payload: dict[str, Any] | None = None) -> str:
    """The proposal in plain words (Studio's own describer; plain text)."""
    from qpilot.studio_state import describe as _describe

    return _describe(proposal, payload)


def descriptions(proposals: Sequence[Proposal]) -> dict[str, str]:
    """Proposal id -> plain words (the edited reading when a person edited it)."""
    out: dict[str, str] = {}
    for p in proposals:
        try:
            out[p.id] = describe(p, p.effective_payload() if p.edits else None)
        except Exception:  # a malformed agent payload is shown by its kind and subject
            out[p.id] = f"{p.kind} for {p.subject}"
    return out


def blind_kind(proposal: Proposal) -> bool:
    """A design or curves proposal (its consequence is only ever 'matters')."""
    if proposal.kind == "stage.confirm":
        return proposal.subject in BLIND_STAGES
    return proposal.kind.startswith(("design.", "curve."))


def visible_proposals(proposals: Sequence[Proposal], results_visible: bool) -> list[Proposal]:
    """What may be listed: while blind, only the design and curves stages' proposals."""
    if results_visible:
        return list(proposals)
    return [p for p in proposals if blind_kind(p)]


# ---- the plate -------------------------------------------------------------------------------


def _judge_cache(studio: Studio, sid: str, experiment: str | None) -> dict[str, bool] | None:
    """The Curve Judge's calls when it already ran on this session (never runs it here)."""
    from qpilot.qpcr import curve_judge

    path = studio.store.find_session(sid) / CURVE_JUDGE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    key = f"{curve_judge.MODEL_SHA256}:{experiment}:scored-only"
    if data.get("key") != key or not isinstance(data.get("calls"), dict):
        return None
    return {str(k): v for k, v in data["calls"].items() if isinstance(v, bool)}


_designed_lock = threading.Lock()
_designed: OrderedDict[tuple[str, int, str], pd.DataFrame | None] = OrderedDict()
MAX_DESIGNED = 4


def _designed_table(studio: Studio, sid: str, design: Any) -> pd.DataFrame | None:
    """The design's per-well table (curves as analysed, the design's roles and exclusions).

    Kept in memory per input file and design, so the plate map and the curve viewer do not
    re-read the analysis for every plate.
    """
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.designs import design_curves
    from qpilot.qpcr.study import StudySettings

    source = studio.source(sid)
    key = (str(source), source.stat().st_mtime_ns, design.design_hash())
    with _designed_lock:
        if key in _designed:
            _designed.move_to_end(key)
            return _designed[key]
    settings = StudySettings.from_design(design)
    try:
        curves = analyse_study(source, settings.experiment_id, settings.candidates, settings.curves)
        table: pd.DataFrame | None = design_curves(curves, design)
    except Exception:  # an unanalysable design: the plate falls back to the file's own facts
        table = None
    with _designed_lock:
        _designed[key] = table
        while len(_designed) > MAX_DESIGNED:
            _designed.popitem(last=False)
    return table


def read_session(studio: Studio, sid: str) -> tuple[Any, Any, dict[str, Any]]:
    """One read of the inbox: the inbox view, the design assembled from it, every stage."""
    inbox = studio.store.proposals(sid).view()
    assembly = studio.assemble(sid, inbox.accepted)
    stages = {s.stage: s for s in studio._stages(sid, inbox, assembly)}
    return inbox, assembly, stages


def plate_view(studio: Studio, sid: str, run_id: str | None = None) -> PlateView:
    """One plate's wells. ``run_id`` defaults to the first plate the design analyses.

    Raises:
        KeyError: No plate ``run_id`` in the file.
    """
    from qpilot.qpcr.amp_call import amplified

    facts = studio.facts(sid)
    summary = facts.summary
    inbox, assembly, stages = read_session(studio, sid)
    design = assembly.design
    experiment = design.experiment_id if design is not None else None
    curves_shown = bool(stages.get("curves") and stages["curves"].open)
    visible = all(stages[b].confirmed for b in BLIND_STAGES if b in stages)
    runs = [
        PlateRun(
            experiment_id=r.experiment_id,
            run_id=r.run_id,
            n_wells=r.n_wells,
            targets=list(r.targets),
            in_design=experiment is not None and r.experiment_id == experiment,
        )
        for r in summary.runs
    ]
    if not runs:
        raise KeyError("this file has no plates")
    if run_id is None:
        run = next((r for r in runs if r.in_design), runs[0])
    else:
        run = next((r for r in runs if r.run_id == run_id), None)
        if run is None:
            raise KeyError(f"no plate {run_id!r} in this file")
    table = facts.wells
    rows = table[(table["run_id"] == run.run_id) & (table["experiment_id"] == run.experiment_id)]
    designed = None
    if design is not None and run.in_design:
        full = _designed_table(studio, sid, design)
        if full is not None:
            designed = full[full["run_id"] == run.run_id]
    left_out: Any = None  # wells of targets a person left out (the analysis drops them)
    if designed is not None and not designed.empty:
        ignored = {t for t, d in design.targets.items() if d.role == "ignore"} if design else set()
        if ignored:
            left_out = rows[rows["target"].isin(ignored)]
        rows = designed
    person_calls = dict(design.well_calls) if design is not None else {}
    excluded = set(design.excluded_wells) if design is not None else set()
    judge = _judge_cache(studio, sid, experiment) if curves_shown and run.in_design else None
    pending: dict[str, str] = {}
    for p in inbox.proposals:
        if p.kind == "curve.well_call" and p.status == "proposed":
            pending[p.subject] = p.id
    calls = None
    if curves_shown and not rows.empty:
        try:
            calls = amplified(rows, "linregpcr", person_calls)
        except Exception:  # a table without quantities: no call is shown
            calls = None
    groups: dict[str, str] = {}
    if visible and design is not None:
        groups = {s: d.group for s, d in design.samples.items() if d.group}
    wells: list[PlateWell] = []
    for idx, row in rows.iterrows():
        well = str(row["well"])
        key = f"{run.run_id}/{well}"
        r, c = well_position(well)
        sample = str(row["sample"])
        target = str(row["target"])
        item = PlateWell(
            key=key,
            well=well,
            row=r,
            col=c,
            sample=sample,
            sample_text_id=facts.sample_text_ids.get(sample),
            target=target,
            target_text_id=facts.target_text_ids.get(target),
            declared_type=_declared(facts, row),
            role=str(row["sample_type"]) if designed is not None else None,
            excluded_by_person=key in excluded or bool(row.get("design_excluded", False)),
            excluded_note=str(row.get("excluded") or ""),
            proposal_id=pending.get(key),
            group=groups.get(sample),
        )
        if curves_shown:
            ours = bool(calls.loc[idx]) if calls is not None else None
            theirs = judge.get(key) if judge is not None else None
            item = item.model_copy(
                update={
                    "amplified": ours,
                    "cq": finite(row.get("cq")),
                    "efficiency": finite(row.get("eff_indiv")),
                    "efficiency_target": finite(row.get("eff_target")),
                    "baseline": finite(row.get("baseline")),
                    "linregpcr_note": str(row.get("note") or ""),
                    "r2": finite(row.get("r2")),
                    "judge": theirs,
                    "disagrees": bool(
                        theirs is not None
                        and ours is not None
                        and theirs != ours
                        and key not in person_calls
                        and str(row["sample_type"]) == "unkn"
                    ),
                    "person_call": person_calls.get(key),
                }
            )
        wells.append(item)
    if left_out is not None:
        for _, row in left_out.iterrows():
            well, sample, target = str(row["well"]), str(row["sample"]), str(row["target"])
            r, c = well_position(well)
            wells.append(
                PlateWell(
                    key=f"{run.run_id}/{well}",
                    well=well,
                    row=r,
                    col=c,
                    sample=sample,
                    sample_text_id=facts.sample_text_ids.get(sample),
                    target=target,
                    target_text_id=facts.target_text_ids.get(target),
                    declared_type=_declared(facts, row),
                    role=None,
                    excluded_by_person=False,
                    excluded_note="its target is left out of the study by a person's decision",
                    group=groups.get(sample),
                )
            )
    n_rows, n_cols = plate_shape((w.row, w.col) for w in wells)
    if judge is not None:
        judge_words = "ran on this file (its calls are shown)"
    elif curves_shown and run.in_design:
        judge_words = "not run yet: Check the curves runs it where it is validated"
    else:
        judge_words = "not shown on this plate"
    return PlateView(
        key=sid,
        run=run,
        runs=runs,
        n_rows=n_rows,
        n_cols=n_cols,
        targets=sorted({w.target for w in wells}),
        curves_shown=curves_shown,
        curves_note=WORDS["curves_shown"] if curves_shown else WORDS["curves_hidden"],
        curve_judge=judge_words,
        results_visible=visible,
        wells=wells,
    )


def _declared(facts: Any, row: Any) -> str:
    """The type the file declares for this well's sample (and target)."""
    pairs = facts.sample_types.get(str(row["sample"])) or ()
    target = str(row["target"])
    for kind, for_target in pairs:
        if for_target in ("", target):
            return str(kind)
    if "sample_type" in getattr(row, "index", ()):
        return str(row["sample_type"])
    return "unkn"


# ---- one well's curve ------------------------------------------------------------------------


def parse_well_key(key: str) -> tuple[str, str]:
    """``run_id/well`` -> (run_id, well); ValueError for anything else."""
    if not isinstance(key, str) or not KEY.match(key):
        raise ValueError("a well is named `plate/well`, e.g. `AHCY_20080229/A1`")
    run_id, _, well = key.rpartition("/")
    return run_id, well


def curve_view(studio: Studio, sid: str, key: str, target: str | None = None) -> CurveView:
    """A well's raw curve, the replicates beside it, and LinRegPCR's numbers once shown.

    Raises:
        ValueError: A malformed well key.
        KeyError: No such plate, well or target in the file.
    """
    from qpilot.web.curves import raw_run

    run_id, well = parse_well_key(key)
    facts = studio.facts(sid)
    known = {r.run_id for r in facts.summary.runs}
    if run_id not in known:
        raise KeyError(f"no plate {run_id!r} in this file")
    curves = raw_run(studio.source(sid), run_id)
    here = [w for (wl, _), w in curves.items() if wl == well]
    if target is not None:
        here = [w for w in here if w.target == target]
    if not here:
        raise KeyError(f"no curve for well {well} on plate {run_id}")
    raw = here[0]
    stages = {s.stage: s for s in studio.stages(sid)}
    shown = bool(stages.get("curves") and stages["curves"].open)
    numbers: dict[str, Any] = {}
    if shown:
        plate = plate_view(studio, sid, run_id)
        match = next((w for w in plate.wells if w.well == well and w.target == raw.target), None)
        if match is not None:
            numbers = {
                "cq": match.cq,
                "efficiency": match.efficiency,
                "efficiency_target": match.efficiency_target,
                "r2": match.r2,
                "amplified": match.amplified,
                "judge": match.judge,
                "baseline": match.baseline,
                "linregpcr_note": match.linregpcr_note,
            }
    replicates = [
        CurveSeries(
            key=f"{run_id}/{w.well}",
            well=w.well,
            sample=w.sample,
            target=w.target,
            cycle=list(w.cycles),
            fluorescence=list(w.values),
        )
        for (wl, _), w in curves.items()
        if w.sample == raw.sample and w.target == raw.target and wl != well
    ][:MAX_REPLICATES]
    declared = _declared(facts, {"sample": raw.sample, "target": raw.target})
    return CurveView(
        key=f"{run_id}/{well}",
        run_id=run_id,
        well=well,
        sample=raw.sample,
        target=raw.target,
        declared_type=declared,
        cycle=list(raw.cycles),
        fluorescence=list(raw.values),
        numbers_shown=shown,
        replicates=replicates,
        note=WORDS["curve_note"],
        **numbers,
    )


# ---- quarantined text, evidence and the model's payload -------------------------------------


def quarantine_view(studio: Studio, sid: str, ids: Sequence[str] | None = None) -> QuarantineView:
    """Every quarantined text of the session (or those named), with the sheet's cells."""
    entries = studio.quarantined(sid)
    if ids:
        wanted = set(ids)
        entries = [e for e in entries if e.text_id in wanted]
    try:
        cells = {c.cell: c.text_id for c in studio.summary(sid).sheet}
    except Exception:  # a changed sheet: the texts are still the session's
        cells = {}
    return QuarantineView(
        entries=entries,
        sheet_cells=cells,
        n_flagged=sum(1 for e in entries if e.flags),
    )


def evidence_views(studio: Studio, sid: str, proposal: Proposal) -> list[EvidenceView]:
    """A proposal's evidence with the quoted text each item points at."""
    texts = {e.text_id: e for e in studio.quarantined(sid)}
    try:
        cells = {c.cell: c.text_id for c in studio.summary(sid).sheet}
    except Exception:
        cells = {}
    out: list[EvidenceView] = []
    for item in proposal.evidence:
        entry = None
        if item.kind == "text":
            entry = texts.get(item.ref)
        elif item.kind == "cell" and item.ref in cells:
            entry = texts.get(cells[item.ref])
        well = item.ref if item.kind in ("well", "curve") and KEY.match(item.ref) else None
        out.append(
            EvidenceView(
                kind=item.kind,
                ref=item.ref,
                note=item.note,
                text=entry.value if entry else None,
                origin=entry.origin if entry else None,
                flags=list(entry.flags) if entry else [],
                well=well,
            )
        )
    return out


def proposal_view(studio: Studio, sid: str, proposal: Proposal) -> ProposalView:
    """Everything one proposal card shows."""
    stale = None
    if proposal.kind == "prism.exclusion_reason" and proposal.status == "proposed":
        try:
            stale = studio.stale_consequence(sid, proposal)
        except Exception:  # cannot tell: the accept itself refuses when it does not hold
            stale = None
    alternatives = []
    for alt in proposal.alternatives:
        try:
            alternatives.append(describe(proposal, alt))
        except Exception:
            alternatives.append(json.dumps(alt, ensure_ascii=False, default=str)[:500])
    return ProposalView(
        proposal=proposal,
        description=descriptions([proposal])[proposal.id],
        alternatives=alternatives,
        evidence=evidence_views(studio, sid, proposal),
        blind=blind_kind(proposal),
        stale_consequence=stale,
        model_made=proposal.made_by.kind == "model"
        and proposal.made_by.provider != "qpilot-curve-judge",
        head=studio.head(sid),
    )


def model_seen(studio: Studio, sid: str, proposal: Proposal | None = None) -> ModelSeen:
    """The last model call's payload, withheld while blind unless the Design Interpreter sent it."""
    from qpilot.ai import payload_log
    from qpilot.ai.prompts import SYSTEM_INTERPRET

    last = payload_log.last_payload()
    if last is None:
        return ModelSeen(state="none", message=WORDS["seen_none"], interpreter=False)
    interpreter = last.get("system") == SYSTEM_INTERPRET
    if not interpreter and not studio.results_visible(sid):
        return ModelSeen(state="hidden", message=WORDS["seen_hidden"], interpreter=False)
    sha = hashlib.sha256(payload_log.canonical(dict(last)).encode("utf-8")).hexdigest()
    text = json.dumps(last, indent=2, ensure_ascii=False, default=str)[:MAX_PAYLOAD_CHARS]
    same = None
    if proposal is not None:
        same = bool(proposal.made_by.prompt_sha256 and proposal.made_by.prompt_sha256 == sha)
    return ModelSeen(
        state="shown",
        message=WORDS["seen_shown"],
        payload_text=text,
        sha256=sha,
        interpreter=interpreter,
        same_as_proposal=same,
    )


# ---- words for outcomes ----------------------------------------------------------------------


def report_message(report: dict[str, Any], what: str) -> str:
    """What a propose round did, in sentences (the earlier page's wording)."""
    proposed = len(report.get("proposed", []))
    parts = [f"{proposed} {what} proposal{'s' * (proposed != 1)} added to the inbox."]
    refused = report.get("refused") or []
    if refused:
        parts.append(
            f"{len(refused)} refused: " + "; ".join(str(r.get("reason")) for r in refused[:3])
        )
    if report.get("fallback") is True:
        parts.append("The model was not used; the rules proposed alone.")
    judged = "disagreements" in report
    for note in map(str, report.get("notes", [])):
        if judged and note == CURVE_JUDGE_LISTED:
            continue  # said once below, with the counts
        note = note[:1].upper() + note[1:]
        parts.append(note if note.endswith((".", "!", "?")) else note + ".")
    if judged:
        parts.append(curve_judge_sentence(report))
    return " ".join(parts)


def curve_judge_sentence(report: dict[str, Any]) -> str:
    """What the Curve Judge found, once: where it disagrees and what the inbox lists."""
    n = int(report.get("disagreements") or 0)
    k = int(report.get("targets_that_matter") or 0)
    wells = f"{n} study well{'s' * (n != 1)}"
    if not n:
        return "The Curve Judge agrees with LinRegPCR on every study well it scored."
    if not k:
        none = (
            "it cannot change a conclusion, so it is not listed"
            if n == 1
            else "none of them can change a conclusion, so none is listed"
        )
        return f"The Curve Judge disagrees with LinRegPCR on {wells}; {none}."
    targets = f"{k} target{'s' * (k != 1)}"
    whose = "that target's" if k == 1 else "those targets'"
    return (
        f"The Curve Judge disagrees with LinRegPCR on {wells}; on {targets}, resolving them "
        f"could change a conclusion, so {whose} wells are listed one by one for you to decide. "
        "The others change no conclusion and are not listed."
    )


def outcome_message(outcome: ProposalOutcome, done: str) -> str:
    """The sentence for a decision's outcome."""
    if outcome.status == "stale":
        return WORDS["stale"]
    if outcome.status in DECIDED:
        return done
    reason = outcome.reason or outcome.status
    return f"Not done: {reason[:1].upper() + reason[1:]}"


def sentence(text: str) -> str:
    """A refusal as a sentence: capital first letter, full stop."""
    text = str(text).strip() or "That was refused."
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."
