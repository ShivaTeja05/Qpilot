"""The Studio log around a study's decision chain: what happened to its file before and after.

A study made in a Studio session has a second hash-chained log, the session's proposal inbox
(``proposals.jsonl``: every proposal, acceptance and rejection on the design, the curves, the
choices and Prism). It holds hundreds of entries on the demo, so it is shown by stage run: one
:class:`~qpilot.web.contract_history.StudioMilestone` per run of entries on one stage, with what
was proposed, accepted and turned down, and whether the run confirmed its stage.

The analyses of the same input file (one per design a person confirmed; a Prism round trip that
excludes a value makes a new one) are listed as related studies; each is tied to the Studio step
that produced it: the curves confirmation, or an accepted change after it.
"""

from __future__ import annotations

import json
import threading
from collections import Counter, OrderedDict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qpilot.core.proposals import chain_lines, verify_proposal_chain
from qpilot.core.store import INPUT_SHA, StudyNotFound, StudyStore, read_entries
from qpilot.schemas import DecisionEntry
from qpilot.schemas_studio import Proposal, ProposalEntry
from qpilot.web.contract_history import MilestoneItem, RelatedStudy, StudioMilestone

KIND_TITLE = {
    "design.preset": "Design preset",
    "design.well_role": "Sample role",
    "design.group": "Group",
    "design.bio_unit": "Biological unit",
    "design.target_role": "Target role",
    "design.gene_symbol": "Gene symbol",
    "design.comparison": "Comparison",
    "design.dilution_series": "Dilution series",
    "curve.call_rule": "Amplification rule",
    "curve.well_call": "Well call",
    "prism.project": "Prism project",
    "prism.exclusion_reason": "Exclusion in Prism",
    "prism.value_edit": "Value changed in Prism",
    "stage.confirm": "Confirm stage",
}
STAGE_WORD = {
    "design": "Design",
    "curves": "Curves",
    "choices": "Choices",
    "prism": "Prism",
    "other": "Studio",
}
# Accepted proposals that make (or re-make) the session's analysis: the curves confirmation,
# and a change after it that a person accepted from a Prism round trip.
PRODUCES = {"prism.exclusion_reason", "prism.value_edit"}
MAX_LISTED = 3
MAX_TEXT = 160
MAX_CACHED = 8


def _stage(proposal: Proposal | None) -> str:
    if proposal is None:
        return "other"
    if proposal.kind == "stage.confirm":
        stage = str(proposal.payload.get("stage") or proposal.subject)
        return stage if stage in STAGE_WORD else "other"
    head = proposal.kind.split(".", 1)[0]
    return {"design": "design", "curve": "curves", "prism": "prism"}.get(head, "other")


def _short(text: str | None) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def _produces(entry: ProposalEntry, proposal: Proposal | None) -> bool:
    if entry.action not in ("accept", "edit") or proposal is None:
        return False
    if proposal.kind == "stage.confirm":
        return _stage(proposal) == "curves"
    return proposal.kind in PRODUCES


_cache_lock = threading.Lock()
_cache: OrderedDict[tuple[str, int], tuple[list[ProposalEntry], int | None]] = OrderedDict()


def read_log(folder: Path) -> tuple[list[ProposalEntry], int | None]:
    """A session's proposal chain and the first entry that fails to verify (None if intact).

    Unlike the inbox, a damaged chain is read rather than refused, so the timeline can show
    where it breaks; nothing read here is ever acted on.
    """
    path = folder / "proposals.jsonl"
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return [], None
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    entries: list[ProposalEntry] = []
    broken: int | None = None
    for position, line in enumerate(chain_lines(path), start=1):
        try:
            entries.append(ProposalEntry.model_validate_json(line))
        except ValueError:
            broken = position
            break
    found = verify_proposal_chain(entries, folder.name) if INPUT_SHA.match(folder.name) else 1
    if found is not None:
        broken = found if broken is None else min(broken, found)
    value = (entries, broken)
    with _cache_lock:
        _cache[key] = value
        while len(_cache) > MAX_CACHED:
            _cache.popitem(last=False)
    return value


def _milestone(
    run: list[tuple[ProposalEntry, Proposal | None]], stage: str, broken: int | None
) -> StudioMilestone:
    actions = Counter(e.action for e, _ in run)
    items: dict[tuple[str, str], dict[str, Any]] = {}
    confirmed = False
    for entry, proposal in run:
        kind = proposal.kind if proposal else "unknown"
        item = items.setdefault(
            (kind, entry.action),
            {"n": 0, "actors": Counter(), "reasons": [], "subjects": []},
        )
        item["n"] += 1
        item["actors"][entry.actor] += 1
        reason = _short(entry.reason)
        if reason and reason not in item["reasons"] and len(item["reasons"]) < MAX_LISTED:
            item["reasons"].append(reason)
        subject = _short(proposal.subject) if proposal else ""
        if subject and subject not in item["subjects"] and len(item["subjects"]) < MAX_LISTED:
            item["subjects"].append(subject)
        if kind == "stage.confirm" and entry.action == "accept":
            confirmed = True
    parts = []
    if actions["propose"]:
        parts.append(f"{actions['propose']} proposed")
    if actions["accept"] + actions["edit"]:
        parts.append(f"{actions['accept'] + actions['edit']} accepted")
    if actions["reject"]:
        parts.append(f"{actions['reject']} turned down")
    title = f"{STAGE_WORD[stage]}: {', '.join(parts) or 'no change'}"
    if confirmed:
        title += " · confirmed"
    first, last = run[0][0], run[-1][0]
    return StudioMilestone(
        stage=stage,  # type: ignore[arg-type]
        title=title,
        first_seq=first.seq,
        last_seq=last.seq,
        at_first=first.at,
        at_last=last.at,
        n_proposed=actions["propose"],
        n_accepted=actions["accept"] + actions["edit"],
        n_rejected=actions["reject"],
        n_edited=actions["edit"],
        n_superseded=actions["supersede"],
        confirmed=confirmed,
        head=last.hash,
        chain_intact=broken is None or last.seq < broken,
        before=True,
        items=[
            MilestoneItem(
                kind=kind,
                title=KIND_TITLE.get(kind, kind),
                action=action,  # type: ignore[arg-type]
                n=v["n"],
                actors=dict(v["actors"]),
                reasons=v["reasons"],
                subjects=v["subjects"],
            )
            for (kind, action), v in items.items()
        ],
    )


def milestones(
    folder: Path,
) -> tuple[list[StudioMilestone], list[tuple[str, int]], bool]:
    """The session's log by stage run, the producing acceptances (at, run index), and intact."""
    entries, broken = read_log(folder)
    proposals: dict[str, Proposal] = {}
    runs: list[tuple[str, list[tuple[ProposalEntry, Proposal | None]]]] = []
    producing: list[tuple[str, int]] = []
    for entry in entries:
        if entry.proposal is not None:
            proposals[entry.proposal_id] = entry.proposal
        proposal = proposals.get(entry.proposal_id)
        stage = _stage(proposal)
        if not runs or runs[-1][0] != stage:
            runs.append((stage, []))
        runs[-1][1].append((entry, proposal))
        if _produces(entry, proposal):
            producing.append((entry.at, len(runs) - 1))
    return [_milestone(run, stage, broken) for stage, run in runs], producing, broken is None


def _workspace_info(folder: Path) -> tuple[str, str] | None:
    """(study id, input sha256) of a workspace folder, from its results file."""
    try:
        data = json.loads((folder / "results.json").read_text(encoding="utf-8"))
        return str(data["study_id"]), str(data["input_sha256"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


_ws_lock = threading.Lock()
_ws: dict[tuple[str, int], tuple[str, str] | None] = {}


def same_input(store: StudyStore, input_sha256: str) -> list[str]:
    """Every analysed study of one input file (any design), by study id."""
    out = []
    for folder in sorted(store.root.iterdir()):
        path = folder / "results.json"
        if not folder.is_dir() or not path.is_file():
            continue
        try:
            key = (str(path), path.stat().st_mtime_ns)
        except OSError:
            continue
        with _ws_lock:
            info = _ws.get(key, ...)
        if info is ...:
            info = _workspace_info(folder)
            with _ws_lock:
                _ws[key] = info
        if info is not None and info[1] == input_sha256:
            out.append(info[0])
    return out


def created_at(store: StudyStore, study_id: str) -> str | None:
    """When a study was made: its first chain entry, else its results file's time."""
    try:
        folder = store.workspace(study_id)
    except StudyNotFound:
        return None
    entries = read_entries(folder / "decisions.jsonl")
    if entries:
        return entries[0].at
    try:
        mtime = (folder / "results.json").stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _session_meta(folder: Path) -> dict[str, Any]:
    try:
        return json.loads((folder / "studio.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _after_words(run: StudioMilestone) -> str:
    """What a study was made after, in words (the run's last acceptance)."""
    accepted = [i for i in run.items if i.action in ("accept", "edit")]
    if not accepted:
        return run.title
    last = accepted[-1]
    if last.kind == "stage.confirm":
        return f"{STAGE_WORD[run.stage]} confirmed"
    what = f"{last.title} accepted"
    if last.subjects:
        what += f" ({', '.join(last.subjects)})"
    if last.reasons:
        what += f": {last.reasons[-1]}"
    return what


def studio_context(
    store: StudyStore,
    study_id: str,
    input_sha256: str,
    created: str | None,
    entries: Sequence[DecisionEntry],
    session: str | None = None,
) -> tuple[str | None, list[StudioMilestone], bool, list[RelatedStudy]]:
    """A study's Studio session, its log by stage run, and the file's other analyses.

    Returns ``(session id, milestones, the log verifies, related studies)``.
    """
    from qpilot.web.results_views import session_of_study

    sid = session or session_of_study(store, study_id)
    folder = None
    if sid is not None:
        try:
            folder = store.find_session(sid)
        except StudyNotFound:
            folder = None
    runs: list[StudioMilestone] = []
    producing: list[tuple[str, int]] = []
    intact = True
    meta: dict[str, Any] = {}
    if folder is not None:
        runs, producing, intact = milestones(folder)
        meta = _session_meta(folder)

    others = same_input(store, input_sha256)
    studies = {s: created_at(store, s) for s in others}
    designs = meta.get("studies") or {}
    # each study is tied to the latest producing acceptance at or before it was made
    led: dict[str, int] = {}
    for sid_study, made in studies.items():
        if made is None or (designs and sid_study not in designs):
            continue
        hits = [run for at, run in producing if at <= made]
        if hits:
            led[sid_study] = hits[-1]
    for study, run in led.items():
        runs[run] = runs[run].model_copy(update={"led_to": study})

    mine = led.get(study_id)
    times = [e.at for e in entries]
    placed = []
    for index, run in enumerate(runs):
        if mine is not None:
            before = index <= mine
        else:
            before = created is not None and run.at_last < created
        after_seq = None
        if not before:
            after_seq = sum(1 for at in times if at <= run.at_first)
        placed.append(run.model_copy(update={"before": before, "after_seq": after_seq}))

    related = []
    for other in others:
        if other == study_id:
            continue
        run_index = led.get(other)
        try:
            n_entries = len(read_entries(store.workspace(other) / "decisions.jsonl"))
        except StudyNotFound:
            continue
        related.append(
            RelatedStudy(
                study_id=other,
                created_at=studies.get(other),
                design_hash=designs.get(other),
                current=meta.get("current_study") == other,
                after=_after_words(runs[run_index]) if run_index is not None else None,
                n_entries=n_entries,
            )
        )
    related.sort(key=lambda r: (r.created_at or "", r.study_id))
    return sid, placed, intact, related
