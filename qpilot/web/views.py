"""Structured views the routes return: built from the services, never HTML.

Small, pure helpers over :class:`~qpilot.studio_service.Studio` and the store. Anything that is
only presentation (colours, layout) belongs to the frontend; anything that is a fact or a rule
(which step comes next, what a stage waits for) is decided here, once, for every client.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qpilot.core.store import StudyNotFound, StudyStore
from qpilot.explain.sets import AUDIT_DOES
from qpilot.studio_service import Studio, StudioError
from qpilot.web.contract import (
    FileFacts,
    NextStep,
    StageView,
    WorkspaceSummary,
    WorkspaceView,
)

STUDY_KEY = re.compile(r"^[0-9a-f]{12}\Z")
INPUT_SUFFIXES = {
    "rdml": (".rdml", ".xml"),
    "sheet": (".xlsx", ".csv"),
    # instrument exports (and RDML, and a sample sheet) dropped together; the content decides
    "export": (".rdml", ".rdm", ".xml", ".lc96p", ".csv", ".tsv", ".txt", ".xlsx", ".xlsm"),
}
MAX_SENTENCE = 500


def demo_sha() -> str:
    """The demo study's input sha256."""
    from qpilot.io.datasets import VERMEULEN_SHA256

    return VERMEULEN_SHA256


def inputs_dir(store: StudyStore) -> Path:
    """Where opened files are kept so a session finds them again after a restart.

    Next to the study store (``~/.cache/qpilot/studio-inputs`` for the default store), named by
    content, so the same file opened twice is kept once.
    """
    path = store.root.parent / "studio-inputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


MAX_NAME = 200


def _name_file(kept: Path) -> Path | None:
    """Where a kept upload's original name is written (beside the kept-inputs folder).

    An RDML file built from an instrument export (``<studies>/imports/capture/<key>.rdml``)
    keeps its name next to it (``<key>.rdml.name``): the export's file, or its plate and how
    many files.
    """
    if kept.parent.name == "studio-inputs":
        return kept.parent.parent / "studio-input-names" / kept.name
    if kept.parent.name == "capture" and kept.parent.parent.name == "imports":
        return kept.parent / f"{kept.name}.name"
    return None


def remember_name(kept: Path, name: str) -> None:
    """Remember the name a kept upload had on the person's computer (shown, never opened)."""
    name = "".join(ch for ch in Path(name or "").name if ch.isprintable())[:MAX_NAME].strip()
    target = _name_file(kept)
    if not name or name == kept.name or target is None:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(name, encoding="utf-8", newline="\n")
    except OSError:  # the content-named copy is enough to work with
        pass


def display_name(path: str | Path | None) -> str | None:
    """A file's name as the person knows it (an upload's original name when it was kept)."""
    if not path:
        return None
    path = Path(path)
    target = _name_file(path)
    if target is None:
        return path.name
    try:
        name = target.read_text(encoding="utf-8").strip()
    except OSError:
        return path.name
    return name[:MAX_NAME] or path.name


def study_autonomy(store: StudyStore, study_id: str | None) -> Any:
    """A study's autonomy (``suggest`` / ``decide_and_tell``), None without a study."""
    if not study_id:
        return None
    try:
        level = store.autonomy(study_id)
    except (StudyNotFound, OSError, ValueError):
        return None
    return level if level in ("suggest", "decide_and_tell") else "suggest"


def session_meta(store: StudyStore, sid: str) -> dict[str, Any]:
    """A session's ``studio.json`` (empty when there is none)."""
    path = store.find_session(sid) / "studio.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def session_source_record(store: StudyStore, sid: str) -> dict[str, Any]:
    """A session's ``source.json``: the bound file (and sheet) paths with their sha256."""
    path = store.find_session(sid) / "source.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def last_write(folder: Path) -> float:
    """The newest mtime among a workspace's own files (not recursive)."""
    newest = 0.0
    try:
        for p in folder.iterdir():
            if p.is_file():
                newest = max(newest, p.stat().st_mtime)
    except OSError:
        pass
    return newest


def stage_views(studio: Studio, sid: str) -> list[StageView]:
    """Every stage's status (empty when the session's file is missing).

    ``pending`` counts the proposals waiting for a decision; a waiting confirm step is told
    apart (``confirm_waiting``), and ``consistent`` counts what "Accept all consistent" would
    cover.
    """
    from qpilot.studio_service import _in_stage

    try:
        inbox = studio.store.proposals(sid).view()
        assembly = studio.assemble(sid, inbox.accepted)
        stages = studio._stages(sid, inbox, assembly)
    except (StudioError, StudyNotFound, OSError):
        return []
    waiting = [p for p in inbox.proposals if p.status == "proposed"]
    out = []
    for s in stages:
        mine = [p for p in waiting if _in_stage(p, s.stage)]
        confirms = [p for p in mine if p.kind == "stage.confirm"]
        others = [p for p in mine if p.kind != "stage.confirm"]
        out.append(
            StageView(
                **{
                    **s.as_dict(),
                    "pending": len(others),
                    "consistent": sum(1 for p in others if p.check.status == "consistent"),
                    "confirm_waiting": bool(confirms),
                }
            )
        )
    return out


def next_step(
    stages: list[StageView],
    proposals: dict[str, int],
    *,
    file_present: bool,
    results_visible: bool,
    undecided_cards: int = 0,
    has_audit: bool = False,
    analysed: bool = True,
    quantify: bool = False,
) -> NextStep:
    """The one thing to do next. ``proposals`` counts the inbox per stage (``design`` …).

    A study that quantifies samples (``quantify``) has no audit (it compares no groups): its
    last step is the report.
    """
    if not file_present:
        return NextStep(
            title="Open the file again",
            detail="The input file is missing or has changed since this study was opened.",
            section="home",
            action="Open",
        )
    by = {s.stage: s for s in stages}
    for stage, propose_label in (("design", "Propose the design"), ("curves", "Check the curves")):
        status = by.get(stage)
        if status is None or status.confirmed:
            continue
        if not proposals.get(stage):
            word = "design" if stage == "design" else "amplification curves"
            return NextStep(
                title=f"Ask for proposals on the {word}",
                detail="The AI proposes; the engine checks each proposal; you decide. "
                "Results stay hidden until you confirm the design and the curves.",
                section=stage,
                action=propose_label,
            )
        if status.pending:
            return NextStep(
                title=f"Review {status.pending} {stage} proposal{'s' * (status.pending != 1)}",
                detail="Accept, edit or reject each one; contradicted proposals come first.",
                section=stage,
                action="Accept all consistent…" if status.consistent else None,
            )
        if status.blockers:
            return NextStep(title=status.blockers[0], section=stage)
        if status.confirm_waiting:
            return NextStep(
                title=f"Confirm the {stage}",
                detail="The confirm step shows what it covers; “Yes, confirm” confirms it.",
                section=stage,
                action="Confirm this stage…",
            )
        return NextStep(
            title=f"Confirm the {stage}",
            detail="Confirming shows exactly what it covers before anything is written.",
            section=stage,
            action="Confirm this stage…",
        )
    if not results_visible:
        return NextStep(title="Confirm the design and the curves", section="design")
    if not analysed:
        return NextStep(
            title="Analysing the confirmed design",
            detail="Every curve, then every analysis in qPilot's choice grid; the results show "
            "when it is done.",
            section="results",
        )
    choices = by.get("choices")
    if choices is not None and choices.pending:
        return NextStep(
            title="Decide which further choices to test",
            detail="qPilot proposes testing the efficiency models (or stopping); accept, edit "
            "or reject it. Nothing changes until you accept.",
            section="results",
        )
    if undecided_cards:
        return NextStep(
            title=f"Decide {undecided_cards} analysis choice{'s' * (undecided_cards != 1)}",
            detail="Each card shows what every option would change; you give the reason.",
            section="results",
            action="Decide",
        )
    if quantify:
        return NextStep(
            title="Read the quantities and export the report",
            detail="Every sample's quantity with its 95 % prediction interval, the LOD and the "
            "LOQ; the report and the Analysis Record keep them with every decision.",
            section="report",
            action="Export",
        )
    if not has_audit:
        return NextStep(
            title="Run the robustness audit",
            detail=AUDIT_DOES,
            section="audit",
            action="Run the audit",
        )
    return NextStep(
        title="Export the Analysis Record",
        detail="Input, results, every decision with its reason, and the audit, hash-chained.",
        section="record",
        action="Export",
    )


def file_facts(studio: Studio, sid: str) -> FileFacts | None:
    """Counts from the file's inspection (None when the file cannot be read now)."""
    try:
        summary = studio.summary(sid)
    except (StudioError, StudyNotFound, OSError, ValueError):
        return None
    record = session_source_record(studio.store, sid)
    sheet = record.get("sheet") or {}
    return FileFacts(
        file_name=display_name(record.get("path")),
        input_sha256=summary.input_sha256,
        sheet_name=display_name(sheet["path"]) if sheet.get("path") else None,
        n_plates=len(summary.runs),
        n_wells=sum(r.n_wells for r in summary.runs),
        n_samples=summary.n_samples,
        n_targets=len(summary.targets),
        declared_types=dict(summary.declared_types),
    )


def inbox_counts(studio: Studio, sid: str) -> dict[str, int]:
    """How many proposals each stage has ever had (any status)."""
    counts: dict[str, int] = {}
    try:
        proposals = studio.inbox(sid)
    except (StudioError, StudyNotFound, OSError):
        return counts
    for p in proposals:
        stage = {"design": "design", "curve": "curves", "prism": "prism"}.get(p.stage)
        if stage:
            counts[stage] = counts.get(stage, 0) + 1
    return counts


def audit_dir(store: StudyStore, study_id: str | None) -> Path | None:
    """The robustness audit of a study, if one was run (``<studies>/simulator_audits/<id>``)."""
    if not study_id:
        return None
    path = store.root / "simulator_audits" / study_id
    return path if (path / "audit_manifest.json").exists() else None


def undecided(store: StudyStore, study_id: str | None) -> int:
    """Decision Cards still open or waiting for a person."""
    if not study_id:
        return 0
    try:
        return sum(1 for c in store.cards(study_id) if c.status in ("open", "pending_human"))
    except (StudyNotFound, OSError, ValueError):
        return 0


def analysed_study(studio: Studio, sid: str, meta: dict[str, Any] | None = None) -> str | None:
    """The session's analysed study of the design confirmed now (None while it is analysed).

    Studio analyses on first use; when a person's decision changed the confirmed design (an
    accepted exclusion, say), the earlier analysis is not shown as if it were this one.
    """
    meta = session_meta(studio.store, sid) if meta is None else meta
    current = meta.get("current_study")
    try:
        expected = studio.expected_study(sid)
    except (StudioError, StudyNotFound, OSError, ValueError):
        return None
    if not current or current != expected:
        return None
    try:
        studio.store.workspace(current)
    except StudyNotFound:
        return None
    return current


def session_summary(studio: Studio, sid: str, ready: bool | None = None) -> WorkspaceSummary:
    """One line of the workspace list for a Studio session.

    Stages, counts and results need the file's facts; while they are not in memory yet (``ready``
    False, or not known and cold) only what is cheap is returned, with ``warming`` set.
    """
    from qpilot.web.warm import facts_warm, session_file_present

    store = studio.store
    folder = store.find_session(sid)
    record = session_source_record(store, sid)
    meta = session_meta(store, sid)
    present = session_file_present(store, sid)
    warm = (present and facts_warm(store, sid)) if ready is None else ready
    stages: list[StageView] = []
    facts: dict[str, Any] = {}
    if present and warm:
        stages = stage_views(studio, sid)
        try:
            summary = studio.summary(sid)
            facts = {
                "n_plates": len(summary.runs),
                "n_samples": summary.n_samples,
                "n_genes": len(summary.targets),
            }
        except (StudioError, StudyNotFound, OSError, ValueError):
            pass
    visible = bool(stages) and all(s.confirmed for s in stages if s.stage in ("design", "curves"))
    study_id = analysed_study(studio, sid, meta) if visible else None
    decisions = pending = 0
    counts_of = "file"
    if study_id:
        try:
            decisions = len(store.entries(study_id))
            pending = len(store.pending(study_id))
            result = store.get(study_id)
            facts = {
                "n_plates": result.n_plates,
                "n_samples": result.n_samples,
                "n_genes": len(result.contrasts),
            }
            counts_of = "analysis"
        except (StudyNotFound, OSError, ValueError):
            pass
    name = display_name(record.get("path"))
    return WorkspaceSummary(
        key=sid,
        id=f"session:{sid}",
        counts_of=counts_of,  # type: ignore[arg-type]
        kind="session",
        title=_title(name, folder.name),
        input_sha256=folder.name,
        file_name=name,
        file_present=present,
        study_id=study_id,
        results_visible=visible,
        stages=stages,
        decisions=decisions,
        pending_requests=pending,
        # while the file is read, the audit badge comes from disk (it names no number)
        has_audit=audit_dir(store, study_id or (None if warm else meta.get("current_study")))
        is not None,
        is_demo=folder.name == demo_sha(),
        updated_at=last_write(folder),
        warming=present and not warm,
        **facts,
    )


def study_summary(store: StudyStore, study_id: str) -> WorkspaceSummary:
    """One line of the workspace list for a study analysed outside a Studio session."""
    result = store.get(study_id)
    workspace = store.workspace(study_id)
    source = store.source(study_id)
    return WorkspaceSummary(
        key=study_id,
        id=f"study:{study_id}",
        counts_of="analysis",
        kind="study",
        title=_title(display_name(source), result.input_sha256),
        input_sha256=result.input_sha256,
        file_name=display_name(source),
        file_present=source is not None,
        study_id=study_id,
        results_visible=True,
        n_plates=result.n_plates,
        n_samples=result.n_samples,
        n_genes=len(result.contrasts),
        decisions=len(store.entries(study_id)),
        pending_requests=len(store.pending(study_id)),
        has_audit=audit_dir(store, study_id) is not None,
        is_demo=result.input_sha256 == demo_sha(),
        updated_at=last_write(workspace),
    )


def _title(file_name: str | None, sha: str) -> str:
    if sha == demo_sha():
        # Vermeulen et al. 2009 (Lancet Oncol) is the study; Ruijter et al. 2013 (Methods)
        # published its raw curves as this RDML file. The year names the study, as cited.
        return "Vermeulen 2009 neuroblastoma study (demo)"
    return file_name or f"Study {sha[:12]}"


def study_ids(store: StudyStore) -> list[str]:
    """Study ids of the store's complete workspaces; a damaged one is skipped, never fatal."""
    from qpilot.web.events import _study_id
    from qpilot.web.warm import regular_file

    out = []
    try:
        folders = sorted(store.root.iterdir())
    except OSError:
        return out
    for folder in folders:
        try:
            if not folder.is_dir() or not regular_file(folder / "results.json"):
                continue
        except OSError:
            continue
        study_id = _study_id(folder)
        if study_id and STUDY_KEY.match(study_id) and folder.name.startswith(study_id):
            out.append(study_id)
    return out


def workspaces(studio: Studio, warm: Callable[[str], Any] | None = None) -> list[WorkspaceSummary]:
    """Every Studio session and every study not reached through one, newest first.

    ``warm(sid)`` is called for each session whose file is still cold (it starts the read).
    """
    store = studio.store
    out: list[WorkspaceSummary] = []
    session_studies: set[str] = set()
    sessions = store.root / "sessions"
    if sessions.is_dir():
        for folder in sessions.iterdir():
            if folder.is_dir() and len(folder.name) == 64:
                try:
                    item = session_summary(studio, folder.name[:12])
                except (StudyNotFound, OSError, ValueError):
                    continue
                out.append(item)
                if item.warming and warm is not None:
                    warm(item.key)
                studies = session_meta(store, folder.name[:12]).get("studies") or {}
                session_studies.update(studies)
    for study_id in study_ids(store):
        if study_id in session_studies:
            continue
        try:
            out.append(study_summary(store, study_id))
        except (StudyNotFound, OSError, ValueError):
            continue
    out.sort(key=lambda w: w.updated_at, reverse=True)
    return out


def session_view(
    studio: Studio,
    sid: str,
    active_jobs: list[Any] | None = None,
    ready: bool | None = None,
) -> WorkspaceView:
    """Everything the page needs to show a session's frame: file, stages, next step."""
    from qpilot.web import intake

    store = studio.store
    line = session_summary(studio, sid, ready)
    capture = intake.summary(store, sid)  # what an instrument export was read as (or None)
    if line.warming:
        from qpilot.web.warm import COLD_MESSAGE

        return WorkspaceView(
            key=sid,
            kind="session",
            title=line.title,
            results_visible=False,
            next_step=NextStep(title="Reading the file", detail=COLD_MESSAGE, section="design"),
            active_jobs=active_jobs or [],
            is_demo=line.is_demo,
            has_audit=line.has_audit,
            warming=True,
            capture=capture,
        )
    try:
        summary = studio.summary(sid)
    except (StudioError, StudyNotFound, OSError, ValueError):
        summary = None
    try:
        proposals_head = studio.head(sid)
    except (StudioError, StudyNotFound, OSError):
        proposals_head = None
    decisions_head = None
    if line.study_id:
        try:
            decisions_head = store.chain_head(line.study_id)
        except (StudyNotFound, OSError):
            pass
    purpose = session_purpose(studio, sid)
    step = next_step(
        line.stages,
        inbox_counts(studio, sid),
        file_present=line.file_present,
        results_visible=line.results_visible,
        undecided_cards=undecided(store, line.study_id),
        has_audit=line.has_audit,
        analysed=line.study_id is not None,
        quantify=purpose == "quantify",
    )
    return WorkspaceView(
        purpose=purpose,
        autonomy=study_autonomy(store, line.study_id),
        key=sid,
        kind="session",
        title=line.title,
        facts=file_facts(studio, sid),
        summary=summary,
        stages=line.stages,
        results_visible=line.results_visible,
        study_id=line.study_id,
        proposals_head=proposals_head,
        decisions_head=decisions_head,
        next_step=step,
        active_jobs=active_jobs or [],
        has_audit=line.has_audit,
        is_demo=line.is_demo,
        capture=capture,
    )


def study_view(store: StudyStore, study_id: str, active_jobs: list[Any] | None = None):
    """The frame of a study analysed outside a Studio session (results straight away)."""
    line = study_summary(store, study_id)
    purpose = study_purpose(store, study_id)
    step = next_step(
        [],
        {},
        file_present=True,
        results_visible=True,
        undecided_cards=undecided(store, study_id),
        has_audit=line.has_audit,
        quantify=purpose == "quantify",
    )
    return WorkspaceView(
        purpose=purpose,
        autonomy=study_autonomy(store, study_id),
        key=study_id,
        kind="study",
        title=line.title,
        results_visible=True,
        study_id=study_id,
        decisions_head=store.chain_head(study_id),
        next_step=step,
        active_jobs=active_jobs or [],
        has_audit=line.has_audit,
        is_demo=line.is_demo,
    )


def session_purpose(studio: Studio, sid: str) -> str:
    """What a session's study is for, as a person decided it (``compare`` until then).

    Read from the accepted design decisions (a design choice, never a result: blind-safe).
    """
    from qpilot.qpcr.designs import purpose_of

    try:
        return purpose_of(studio.store.proposals(sid).accepted("design."))
    except (StudioError, StudyNotFound, OSError, ValueError):
        return "compare"


def study_purpose(store: StudyStore, study_id: str) -> str:
    """What a stored study is for: ``quantify`` for a quantification design, else ``compare``."""
    from qpilot.qpcr.quantify_study import is_quantify

    try:
        return "quantify" if is_quantify(store.design(study_id)) else "compare"
    except (StudyNotFound, OSError, ValueError):
        return "compare"


def archive_demo(store: StudyStore) -> list[Path]:
    """Move the demo's session, studies and audits aside (never deleted); return where to."""
    import shutil
    import time

    sha = demo_sha()
    targets: list[Path] = []
    candidates: list[Path] = [store.root / "sessions" / sha]
    for study_id in store.list_studies():
        try:
            if store.get(study_id).input_sha256 == sha:
                candidates.append(store.workspace(study_id))
                candidates.append(store.root / "simulator_audits" / study_id)
        except (StudyNotFound, OSError, ValueError):
            continue
    archive = store.root.parent / "studies-archive" / time.strftime("demo-%Y%m%d-%H%M%S")
    for path in candidates:
        if path.exists():
            archive.mkdir(parents=True, exist_ok=True)
            target = archive / path.relative_to(store.root).as_posix().replace("/", "__")
            shutil.move(str(path), str(target))
            targets.append(target)
    return targets
