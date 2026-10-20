"""Prism, the Analysis Record and downloads: everything the page writes to or reads from files.

* **Prism** (a Studio session's, blind-gated like every result): where Prism stands, the preview
  of what Send would write, how the usual Excel→Prism routes would change this study's
  conclusions, the bundles sent, and three jobs: draft the project (a proposal, accepted like any
  other), send (bundle into qPilot's export folder beside the store, zipped for download, then
  Prism started when it is installed here), and the round trip (what came back from Prism becomes
  proposals with their consequences).
* **Record** (a study's): export the Analysis Record (a job; the zip is offered for download) and
  verify an uploaded record (checksums, both hash chains, and its binding to an audit).
* **Downloads**: only files this server registered, only inside the export folder, always
  as an attachment.

Every write is a person's (``actor="human"``, set here). Folder rules: :mod:`qpilot.web.folders`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, File, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from qpilot.core.record import (
    CHECKSUMS,
    RecordError,
    VerifyReport,
    unzip_record,
    verify,
    write_record,
    zip_record,
)
from qpilot.core.store import StudyNotFound
from qpilot.studio_service import StudioError
from qpilot.web import folders, views
from qpilot.web.context import KEY, AppContext, Ctx, api_error, check_key, is_session, is_study
from qpilot.web.contract import JobStarted, JobView
from qpilot.web.contract_files import (
    AuditBinding,
    DownloadLink,
    GroupPoints,
    PreviewTable,
    PrismBundles,
    PrismBundleView,
    PrismChoice,
    PrismDrafted,
    PrismFigure,
    PrismPreview,
    PrismProject,
    PrismRoundTrip,
    PrismRoute,
    PrismRoutes,
    PrismSent,
    PrismStatus,
    PrismTemplate,
    RecordCommands,
    RecordExported,
    RecordFacts,
    RecordList,
    RecordRequest,
    RecordVerified,
    RoundTripRefused,
    RoundTripRequest,
    UnitValue,
)
from qpilot.web.jobs import JobError, Progress

router = APIRouter(tags=["files"])
#: The model of each job's result, by job kind (typed in the schema: ``routers.job_results``).
JOB_RESULTS = {
    "prism.draft": PrismDrafted,
    "prism.send": PrismSent,
    "prism.roundtrip": PrismRoundTrip,
    "record.export": RecordExported,
}

MAX_RECORD_BYTES = 200 * 1024 * 1024  # the old pages' upload cap (Gradio max_file_size 200mb)
MAX_JSON_BYTES = 1024 * 1024  # record.json / audit_manifest.json read from an upload
PROJECT_KIND = "prism.project"
EXPORT_FILE = "export.json"  # beside each exported record zip: what the export job answered
# Typical times on the demo, measured on this laptop on 20 Oct while twenty build sessions shared
# it (so on the slow side); the page shows them as "usually ~N s", never as a promise.
DRAFT_TYPICAL_S = 6.5  # the rules' draft, no model
SEND_TYPICAL_S = 25.0  # the bundle (the engine rebuilds the export inputs) and its zip
ROUNDTRIP_TYPICAL_S = 8.5  # one edited table: the diff and each exclusion's consequence
RECORD_TYPICAL_S = 1.5  # copy, hash and zip (7.8 MB with the input file)
BLIND = (
    "Results stay hidden until you confirm the Design and the Curves stages: Prism shows "
    "group differences."
)
NOT_FROM_HERE = "Choose a bundle that Send to Prism wrote from this page."
TAMPER_NOTE = "Tamper-evident, not tamper-proof. Research use only."
FIGURE_NOTE = (
    "An approximation of the template's graph: every biological unit, the group mean and its "
    "95 % confidence interval. Prism draws the real one."
)
PRISM_ERRORS: tuple[type[BaseException], ...] = (ValueError, KeyError, OSError, RuntimeError)


# ---- shared checks -------------------------------------------------------------------------------


def _session(ctx: AppContext, sid: str) -> None:
    check_key(sid)
    if not is_session(ctx.store, sid):
        raise api_error(404, "not_found", "There is no Studio session with this id.")


def _visible_study(ctx: AppContext, sid: str) -> str:
    """The session's current analysis; 403 ``blind`` until the design and curves are confirmed."""
    _session(ctx, sid)
    try:
        if not ctx.studio.results_visible(sid):
            raise api_error(403, "blind", BLIND)
        return ctx.studio.study(sid)
    except StudyNotFound as err:
        raise api_error(404, "not_found", "There is no Studio session with this id.") from err
    except StudioError as err:
        raise api_error(409, "studio", _sentence(err)) from err
    except OSError as err:
        raise api_error(
            409, "file_missing", f"The session's input file cannot be read: {_sentence(err)}"
        ) from err


def _choices_confirmed(ctx: AppContext, sid: str) -> bool:
    return any(s.stage == "choices" and s.confirmed for s in ctx.studio.stages(sid))


def _project(ctx: AppContext, sid: str, study_id: str) -> PrismProject:
    """The accepted project of this analysis, else a draft waiting, else none (old page's rule)."""
    projects = [p for p in ctx.studio.inbox(sid, "prism") if p.kind == PROJECT_KIND]
    accepted = [
        p
        for p in projects
        if p.status in ("accepted", "edited") and p.effective_payload().get("study_id") == study_id
    ]
    waiting = [p for p in projects if p.status == "proposed"]
    chosen, status = (
        (accepted[-1], "accepted")
        if accepted
        else (waiting[-1], "waiting")
        if waiting
        else (None, "none")
    )
    if chosen is None:
        return PrismProject(status="none")
    payload = chosen.effective_payload()
    return PrismProject(
        status=status,
        proposal_id=chosen.id,
        template_id=payload.get("template_id"),
        genes=[str(g) for g in payload.get("genes") or []],
        made_by=chosen.made_by.kind,
    )


def _job(ctx: AppContext, kind: str, fn: Any, *, title: str, key: str, typical_s: float) -> JobView:
    job = ctx.jobs.submit(kind, fn, title=title, key=key, typical_s=typical_s)
    return JobView(**job.view())


def _sentence(err: BaseException) -> str:
    text = str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err)
    text = text.strip() or type(err).__name__
    return (text[:1].upper() + text[1:])[:500]


def _link(ctx: AppContext, path: Path) -> DownloadLink:
    """The download link of a file in the export folder (the same id when it is offered again)."""
    target = path.resolve()
    with ctx.lock:  # jobs register downloads from their own threads
        token = next((t for t, p in ctx.downloads.items() if p == target), None)
        if token is None:
            token = folders.register_download(ctx.downloads, _exports(ctx), target)
    return DownloadLink(
        id=token,
        url=f"/api/downloads/{token}",
        name=target.name,
        bytes=target.stat().st_size,
        path=str(target),
    )


def _exports(ctx: AppContext) -> Path:
    """The export folder beside the store (every download is inside it)."""
    return folders.exports_root(ctx.store.root)


def _ws_exports(ctx: AppContext, key: str) -> Path:
    """A workspace's own export folder."""
    return folders.workspace_exports(ctx.store.root, key)


# ---- Prism: reading ------------------------------------------------------------------------------


@router.get("/sessions/{sid}/prism", response_model=PrismStatus)
def prism_status(sid: str, ctx: Ctx) -> PrismStatus:
    """Where Prism stands: the project of the current analysis, and what can be done next."""
    study_id = _visible_study(ctx, sid)
    confirmed = _choices_confirmed(ctx, sid)
    project = _project(ctx, sid, study_id)
    if project.status == "accepted" and confirmed:
        step = "The Prism project for this analysis is accepted: press Send to Prism."
    elif project.status == "waiting":
        step = "A drafted Prism project is waiting in the Prism inbox: check it, then accept it."
    elif confirmed:
        step = "No Prism project yet: press “Draft the Prism project”."
    else:
        step = "Confirm the analysis choices first (Results): the Prism project follows them."
    exports = _ws_exports(ctx, sid).resolve()
    here = [
        e
        for e in ctx.studio.exports(sid)
        if folders.within(Path(e.get("bundle_dir", "")), exports)
        and Path(e.get("bundle_dir", "")).is_dir()
    ]
    return PrismStatus(
        session_id=sid,
        study_id=study_id,
        choices_confirmed=confirmed,
        project=project,
        can_draft=confirmed,
        can_send=confirmed and project.status == "accepted",
        next=step,
        bundles=len(here),
    )


@router.get("/sessions/{sid}/prism/preview", response_model=PrismPreview)
def prism_preview(
    sid: str,
    ctx: Ctx,
    rows: Annotated[int, Query(ge=1, le=50)] = 5,
) -> PrismPreview:
    """What Send to Prism would write (nothing is written), with each gene's graph as data."""
    from qpilot.prism import PrismExportError
    from qpilot.qpcr.export import ExportError

    study_id = _visible_study(ctx, sid)
    try:
        full = ctx.studio.preview_prism(sid, rows=folders.MAX_POINTS)
    except StudioError as err:
        raise api_error(409, "studio", _sentence(err)) from err
    except (PrismExportError, ExportError, *PRISM_ERRORS) as err:
        raise api_error(409, "no_preview", f"No Prism preview: {_sentence(err)}") from err
    parsed = folders.preview_tables(full)
    template = full.get("template") or {}
    bundle = full.get("bundle") or {}
    info = bundle.get("info") or {}
    figures: dict[str, PrismFigure] = {}
    if template.get("layout") == "column":
        scale = str(info.get("scale") or "log2 relative quantity")
        for gene, table in parsed.items():
            groups = [
                _group(name, points)
                for name, points in folders.group_points(table["columns"], table["rows"]).items()
            ]
            if any(g.n for g in groups):
                figures[gene] = PrismFigure(gene=gene, scale=scale, groups=groups, note=FIGURE_NOTE)
    cards = {c.id: c for c in ctx.store.cards(study_id)}
    return PrismPreview(
        session_id=sid,
        study_id=study_id,
        writes_nothing=bool(full.get("writes_nothing", True)),
        bundle=bundle,
        would_write=[str(f) for f in full.get("would_write", [])],
        template=PrismTemplate(**template),
        genes=list(parsed),
        tables=[
            PreviewTable(
                gene=g,
                columns=[str(c) for c in t["columns"]],
                n_rows=int(t.get("n_rows") or 0),
                rows=[[str(c) for c in r] for r in t["rows"][:rows]],
            )
            for g, t in parsed.items()
        ],
        choices=[_choice(c, cards.get(str(c.get("card_id")))) for c in full.get("choices", [])],
        caption=info.get("caption"),
        figures=figures,
        project=_project(ctx, sid, study_id),
        choices_confirmed=_choices_confirmed(ctx, sid),
        not_affiliated=str(full.get("not_affiliated", "")),
    )


def _group(name: str, points: list[tuple[str, float]]) -> GroupPoints:
    ci = folders.mean_ci([v for _, v in points])
    return GroupPoints(
        name=name,
        n=len(points),
        mean=ci[0] if ci else None,
        ci_lo=ci[1] if ci else None,
        ci_hi=ci[2] if ci else None,
        points=[UnitValue(unit=u, value=v) for u, v in points],
    )


def _choice(choice: dict[str, Any], card: Any) -> PrismChoice:
    """A choice the bundle is exported at, with the card's question and the option's words."""
    from qpilot.ai.explain import KIND_TITLE

    option = str(choice.get("option", ""))
    labels = {o.id: o.label for o in card.options} if card is not None else {}
    kind = card.kind if card is not None else str(choice.get("dimension", ""))
    return PrismChoice(
        **choice,
        title=KIND_TITLE.get(kind, kind.replace("_", " ").capitalize()),
        option_label=labels.get(option, option.replace("_", " ")),
        decided_by=folders.who_decided(choice.get("actor")),
    )


@router.get("/sessions/{sid}/prism/routes", response_model=PrismRoutes)
def prism_routes(sid: str, ctx: Ctx) -> PrismRoutes:
    """How often the usual Excel→Prism routes would change a conclusion on this study."""
    from qpilot.qpcr.routes import ROUTE_LABELS

    study_id = _visible_study(ctx, sid)
    result = ctx.store.get(study_id)
    facts = result.facts
    n_genes = facts["f_n_genes"].value if "f_n_genes" in facts else None
    routes = []
    for route, label in folders.ROUTES:
        fid = f"f_n_differ_route_{route}"
        if fid not in facts or n_genes is None:
            continue
        n_differ = int(facts[fid].value)
        gid = f"f_genes_differ_route_{route}"
        routes.append(
            PrismRoute(
                route=route,
                label=label,
                method=ROUTE_LABELS.get(route, route),
                n_differ=n_differ,
                n_genes=int(n_genes),
                genes=_gene_list(facts[gid].value, n_differ, list(result.contrasts))
                if gid in facts
                else [],
                fact=fid,
                genes_fact=gid if gid in facts else None,
            )
        )
    changed = {g for r in routes for g in r.genes}
    return PrismRoutes(
        session_id=sid,
        study_id=study_id,
        n_genes=int(n_genes) if n_genes is not None else None,
        rule=_rule_words(result.conclusion_rule),
        engine={g: c.conclusion for g, c in result.contrasts.items() if g in changed},
        routes=routes,
        note=folders.ROUTES_NOTE,
    )


def _rule_words(rule: dict[str, Any] | None) -> str:
    """The study's conclusion rule in the engine's own words."""
    from qpilot.qpcr.contrast import ConclusionRule

    given = rule or {}
    known = {k: float(given[k]) for k in ("alpha", "min_log2fc") if k in given}
    return ConclusionRule(**known).describe()


def _gene_list(value: Any, n: int, known: list[str]) -> list[str]:
    """The genes of a ``f_genes_differ_route_*`` fact (a ", "-joined text, "none" when empty)."""
    if n == 0:
        return []
    parts = [p.strip() for p in str(value).split(", ")]
    if len(parts) == n:
        return parts
    text = f", {value}, "
    return [g for g in known if f", {g}, " in text]  # a gene name with ", " in it


def _bundle_views(ctx: AppContext, sid: str, current: str | None) -> list[PrismBundleView]:
    exports = _ws_exports(ctx, sid).resolve()
    out = []
    for entry in reversed(ctx.studio.exports(sid)):
        folder = Path(str(entry.get("bundle_dir", "")))
        token = folders.bundle_id(folder) if folders.within(folder, exports) else None
        if token is not None and folders.bundle_folder(exports, token) != folder:
            token = None
        archive = exports / _bundle_zip_name(str(entry.get("study_id", "")), token or "")
        sent_back = entry.get("sent_back_dir") or (
            str(folder / folders.SENT_BACK_DIR) if token else None
        )
        out.append(
            PrismBundleView(
                id=token,
                study_id=str(entry.get("study_id", "")),
                bundle_sha256=str(entry.get("bundle_sha256", "")),
                at=str(entry.get("at", "")),
                folder=str(folder),
                exists=folder.is_dir(),
                current=entry.get("study_id") == current,
                sent_back_folder=sent_back,
                round_trip=token is not None,
                download=_link(ctx, archive) if token and archive.is_file() else None,
            )
        )
    return out


def _bundle_zip_name(study_id: str, token: str) -> str:
    """The zip of a bundle, beside its folder (named for the person who saves it)."""
    return f"qpilot-prism-{study_id}-{token}.zip"


@router.get("/sessions/{sid}/prism/bundles", response_model=PrismBundles)
def prism_bundles(sid: str, ctx: Ctx) -> PrismBundles:
    """Every bundle sent to Prism from this session (``Studio.exports``), newest first."""
    study_id = _visible_study(ctx, sid)
    return PrismBundles(session_id=sid, bundles=_bundle_views(ctx, sid, study_id))


# ---- Prism: a person's actions (jobs) ------------------------------------------------------------


@router.post("/sessions/{sid}/prism/draft", response_model=JobStarted, status_code=202)
def prism_draft(sid: str, ctx: Ctx) -> JobStarted:
    """Draft the Prism project (a proposal in the Prism inbox; a person accepts it)."""
    _visible_study(ctx, sid)
    if not _choices_confirmed(ctx, sid):
        raise api_error(
            409, "studio", "Confirm the analysis choices first: the Prism draft follows them."
        )

    def work(progress: Progress) -> dict[str, Any]:
        progress("Drafting the Prism project: tables, test, graph and caption")
        try:
            outcome = ctx.studio.propose_prism(sid)
        except (StudioError, *PRISM_ERRORS) as err:
            raise JobError("studio", f"No Prism project drafted: {_sentence(err)}") from err
        ctx.bus.publish({"type": "proposals.changed", "key": sid, "source": "page"})
        drafted = outcome.status == "proposed"
        return PrismDrafted(
            status=outcome.status,
            proposal_id=outcome.proposal.id if outcome.proposal else None,
            reason=outcome.reason,
            message="The Prism project is drafted: check it in the Prism inbox, then accept it."
            if drafted
            else f"No Prism project drafted: {outcome.reason or outcome.status}",
        ).model_dump(mode="json")

    view = _job(
        ctx,
        "prism.draft",
        work,
        title="Drafting the Prism project",
        key=sid,
        typical_s=DRAFT_TYPICAL_S,
    )
    return JobStarted(job=view)


@router.post("/sessions/{sid}/prism/send", response_model=JobStarted, status_code=202)
def prism_send(sid: str, ctx: Ctx) -> JobStarted:
    """Write the accepted project's bundle, offer it as a zip, start Prism if it is here."""
    study_id = _visible_study(ctx, sid)
    if not _choices_confirmed(ctx, sid):
        raise api_error(409, "studio", "Confirm the analysis choices first.")
    if _project(ctx, sid, study_id).status != "accepted":
        raise api_error(409, "studio", "Accept the Prism project for this analysis first.")

    def work(progress: Progress) -> dict[str, Any]:
        progress("Writing the bundle: tables, scripts and provenance", 0.1)
        exports = _ws_exports(ctx, sid)
        folder = folders.private_dir(exports, folders.BUNDLE_PREFIX)
        try:
            result = ctx.studio.send_to_prism(sid, folder, actor="human")
        except (StudioError, *PRISM_ERRORS) as err:
            shutil.rmtree(folder, ignore_errors=True)
            raise JobError("studio", f"Not sent: {_sentence(err)}") from err
        progress("Zipping the bundle for download", 0.6)
        name = _bundle_zip_name(result.bundle.study_id, folders.bundle_id(folder) or "bundle")
        base = exports / name.removesuffix(".zip")
        archive = Path(shutil.make_archive(str(base), "zip", root_dir=folder))
        progress("Starting Prism (when it is installed on this computer)", 0.7)
        try:
            launched = ctx.studio.launch_prism(result, actor="human")
        except PRISM_ERRORS as err:
            launched = {"launched": False, "note": f"Prism could not be started: {_sentence(err)}"}
        view = next(
            (b for b in _bundle_views(ctx, sid, study_id) if b.folder == str(folder.resolve())),
            None,
        )
        if view is None:  # the export is always remembered; this is only belt and braces
            raise JobError("studio", "The bundle was written but this session does not list it.")
        return PrismSent(
            bundle=view,
            n_files=len(result.files),
            files=sorted(
                p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()
            ),
            notes=[str(n) for n in result.notes],
            launched=bool(launched.get("launched")),
            done=launched.get("done") if launched.get("launched") else None,
            launch_note=None if launched.get("launched") else str(launched.get("note") or ""),
            command_line=result.launch.command_line,
            send_back_command=result.send_back.command_line,
            download=_link(ctx, archive),
        ).model_dump(mode="json")

    view = _job(
        ctx, "prism.send", work, title="Sending to Prism", key=sid, typical_s=SEND_TYPICAL_S
    )
    return JobStarted(job=view)


@router.post("/sessions/{sid}/prism/roundtrip", response_model=JobStarted, status_code=202)
def prism_roundtrip(sid: str, body: RoundTripRequest, ctx: Ctx) -> JobStarted:
    """Compare what Prism sent back with the bundle; each change becomes a proposal."""
    _visible_study(ctx, sid)
    bundle = folders.bundle_folder(_ws_exports(ctx, sid), body.bundle)
    if bundle is None:
        raise api_error(404, "not_found", NOT_FROM_HERE)
    if not any(Path(str(e.get("bundle_dir", ""))) == bundle for e in ctx.studio.exports(sid)):
        raise api_error(409, "studio", "This bundle was not sent to Prism from this session.")
    try:
        folder = folders.allowed_folder(
            body.folder, roots=(_exports(ctx), Path.home()), store_root=ctx.store.root
        )
    except folders.FolderRefused as err:
        raise api_error(400, "bad_folder", str(err)) from err

    def work(progress: Progress) -> dict[str, Any]:
        from qpilot.prism import PrismExportError

        progress("Reading what Prism sent back and comparing it with the bundle")
        try:
            report = ctx.studio.round_trip(sid, bundle, folder)
        except (StudioError, PrismExportError, *PRISM_ERRORS) as err:
            raise JobError(
                "cannot_read", f"Could not read what came back from Prism: {_sentence(err)}"
            ) from err
        ctx.bus.publish({"type": "proposals.changed", "key": sid, "source": "page"})
        inbox = report.get("inbox") or {}
        items = report.get("items", [])
        added = list(inbox.get("proposed", []))
        notes = [str(n) for n in report.get("notes", [])]
        combined = report.get("combined_consequence") or None
        words = [
            f"{len(items)} difference{'s' * (len(items) != 1)} since the export; "
            f"{len(added)} question{'s' * (len(added) != 1)} added to the Round trip inbox."
        ]
        if combined and len(combined.get("exclusions") or []) > 1:
            changed = combined.get("changed_genes") or []
            words.append(
                f"All {len(combined['exclusions'])} exclusions together change {len(changed)} of "
                f"{combined.get('n_genes', '?')} conclusions"
                + (f" ({', '.join(map(str, changed))})." if changed else ".")
            )
        return PrismRoundTrip(
            bundle_id=body.bundle,
            study_id=str(report.get("study_id", "")),
            items=items,
            proposed=added,
            refused=[RoundTripRefused(**r) for r in inbox.get("refused", [])],
            notes=notes,
            combined=combined,
            message=" ".join(words),
        ).model_dump(mode="json")

    view = _job(
        ctx,
        "prism.roundtrip",
        work,
        title="Reading what came back from Prism",
        key=sid,
        typical_s=ROUNDTRIP_TYPICAL_S,
    )
    return JobStarted(job=view)


def _study_gate(ctx: AppContext, study_id: str) -> None:
    """The results routes' rule for a study: 404 unknown, 403 ``blind`` while its session is."""
    from qpilot.web.routers.results import study

    study(ctx, study_id)


def _download_gate(ctx: AppContext, path: Path) -> None:
    """A record or bundle of a workspace that is blind (again) is not served (403 ``blind``)."""
    parts = path.relative_to(_exports(ctx).resolve()).parts
    key = parts[0] if len(parts) > 1 else ""
    if not KEY.match(key):
        raise api_error(404, "not_found", "This download is not available.")
    if parts[1].startswith(folders.RECORD_PREFIX):  # exports/<study>/record-*/…
        _study_gate(ctx, key)
        return
    if not is_session(ctx.store, key):  # exports/<session>/prism-* and their zips
        raise api_error(404, "not_found", "This download is not available.")
    try:
        visible = ctx.studio.results_visible(key)
    except (StudyNotFound, StudioError, OSError):
        visible = False
    if not visible:
        raise api_error(403, "blind", BLIND)


# ---- the Analysis Record -------------------------------------------------------------------------


def _commands(name: str) -> RecordCommands:
    return RecordCommands(verify=f"qpilot verify {name}", rerun=f"qpilot rerun {name}")


@router.post("/studies/{study_id}/record", response_model=JobStarted, status_code=202)
def export_record(
    study_id: str, ctx: Ctx, body: Annotated[RecordRequest | None, Body()] = None
) -> JobStarted:
    """Export the Analysis Record (input, results, every decision, checksums) as a zip."""
    _study_gate(ctx, study_id)
    options = body or RecordRequest()

    def work(progress: Progress) -> dict[str, Any]:
        progress("Copying the study and hashing every file", 0.1)
        folder = folders.private_dir(_ws_exports(ctx, study_id), folders.RECORD_PREFIX)
        try:
            info = write_record(
                ctx.store, study_id, folder / "record", include_input=options.include_input
            )
            meta = json.loads((Path(info.record_dir) / "record.json").read_text(encoding="utf-8"))
            progress("Zipping the record", 0.7)
            archive = zip_record(info.record_dir, folder / f"qpilot-record-{study_id}.zip")
        except (RecordError, StudyNotFound, OSError, ValueError) as err:
            shutil.rmtree(folder, ignore_errors=True)
            raise JobError("cannot_export", f"Export failed: {_sentence(err)}") from err
        shutil.rmtree(info.record_dir, ignore_errors=True)  # keep only the zip
        warnings = []
        open_flips = [
            c.id
            for c in ctx.store.cards(study_id)
            if c.impact.get("flips") and c.status in ("open", "pending_human")
        ]
        if open_flips:
            n = len(open_flips)
            warnings.append(
                f"{n} choice{'s' * (n != 1)} that can change a conclusion "
                f"{'are' if n != 1 else 'is'} still open; the record says so."
            )
        moved = bool(options.expected_head) and info.chain_head != options.expected_head
        if moved:
            warnings.append("Something was decided after this page last refreshed.")
        if options.include_input and not info.input_included:
            warnings.append(
                "The input file was not found, so it is not in the record: the record can be "
                "verified but not re-run."
            )
        exported = RecordExported(
            study_id=study_id,
            record_id=info.record_id,
            chain_head=info.chain_head,
            n_files=info.n_files,
            input_included=info.input_included,
            written_at=meta.get("written_at"),
            download=_link(ctx, archive),
            open_flips=open_flips,
            head_moved=moved,
            warnings=warnings,
            commands=_commands(archive.name),
        )
        (folder / EXPORT_FILE).write_text(exported.model_dump_json(), encoding="utf-8")
        return exported.model_dump(mode="json")

    view = _job(
        ctx,
        "record.export",
        work,
        title="Exporting the Analysis Record",
        key=study_id,
        typical_s=RECORD_TYPICAL_S,
    )
    return JobStarted(job=view)


@router.get("/studies/{study_id}/records", response_model=RecordList)
def list_records(study_id: str, ctx: Ctx) -> RecordList:
    """The records of this study in qPilot's export folder, newest first."""
    _study_gate(ctx, study_id)
    found = []
    for path in _ws_exports(ctx, study_id).glob(f"{folders.RECORD_PREFIX}*/{EXPORT_FILE}"):
        try:
            exported = RecordExported.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        archive = path.parent / exported.download.name
        if exported.study_id != study_id or not archive.is_file():
            continue
        found.append(
            (path.stat().st_mtime, exported.model_copy(update={"download": _link(ctx, archive)}))
        )
    found.sort(key=lambda pair: pair[0], reverse=True)
    return RecordList(study_id=study_id, records=[e for _, e in found])


@router.get(
    "/downloads/{download_id}",
    response_class=FileResponse,
    responses={200: {"content": {"application/zip": {}}, "description": "The file."}},
)
def download(download_id: str, ctx: Ctx) -> FileResponse:
    """A file this server wrote into its export folder (a record or a Prism bundle zip)."""
    path = folders.download_path(ctx.downloads, _exports(ctx), download_id)
    if path is None:
        raise api_error(
            404, "not_found", "This download is not available (qPilot may have restarted)."
        )
    _download_gate(ctx, path)
    media = "application/zip" if path.suffix == ".zip" else "application/octet-stream"
    return FileResponse(path, media_type=media, filename=path.name)


@router.post("/records/verify", response_model=RecordVerified)
async def verify_record(
    ctx: Ctx,
    record: Annotated[UploadFile, File(description="An Analysis Record as a .zip.")],
) -> RecordVerified:
    """Check an uploaded record: every checksum, both hash chains, and its audit binding."""
    name = (Path(record.filename or "record.zip").name or "record.zip")[:200]
    work = folders.private_dir(ctx.private / "verify", folders.VERIFY_PREFIX)
    try:
        upload = work / "upload.zip"
        try:
            size = await folders.save_upload(record, upload, MAX_RECORD_BYTES)
        except folders.FolderRefused as err:
            raise api_error(413, "too_large", f"{name} is {err}.") from err
        if size == 0:
            raise api_error(400, "empty_file", f"{name} is empty.")
        return await run_in_threadpool(_verify_upload, ctx, upload, work / "unpacked", name)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _verify_upload(ctx: AppContext, upload: Path, target: Path, name: str) -> RecordVerified:
    from qpilot.integration.simulator import MANIFEST, verify_audit

    if not zipfile.is_zipfile(upload):
        raise api_error(
            400,
            "not_zip",
            f"{name} is not a zip file: verify the record's .zip (or zip its folder).",
        )
    try:
        unpacked = unzip_record(upload, target)
    except RecordError as err:
        raise api_error(400, "bad_record", f"{name}: {_sentence(err)}.") from err
    records = folders.find_marked(target, CHECKSUMS, depth=1)
    if unpacked in records:
        records = [unpacked]
    if not records:
        raise api_error(
            400, "not_record", f"{name} holds no Analysis Record (there is no {CHECKSUMS} in it)."
        )
    if len(records) > 1:
        raise api_error(
            400, "not_record", f"{name} holds more than one record: verify them one at a time."
        )
    record_dir = records[0]
    try:
        report = verify(record_dir)
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as err:
        report = VerifyReport(
            ok=False, inconsistent=[f"the record cannot be read: {_sentence(err)}"]
        )
    facts = _record_facts(record_dir)
    known = bool(facts.study_id) and _known_study(ctx, facts.study_id or "")

    carried = [d for d in folders.find_marked(target, MANIFEST, depth=2) if d != record_dir]
    audit: AuditBinding | None = None
    if carried:
        chosen = next(
            (d for d in carried if _json(d / MANIFEST).get("study_id") == facts.study_id),
            carried[0],
        )
        audit = _bind(verify_audit, chosen, record_dir, "zip")
        audit_note = "The audit in the zip was checked against this record."
    elif known and (stored := views.audit_dir(ctx.store, facts.study_id)) is not None:
        audit = _bind(verify_audit, stored, record_dir, "store")
        audit_note = "This qPilot's audit of the record's study was checked against this record."
    elif known:
        audit_note = "The record's study has no robustness audit in this qPilot."
    else:
        audit_note = (
            "No audit was checked: the zip carries none and the record's study is not in this "
            "qPilot."
        )
    return RecordVerified(
        ok=report.ok,
        file_name=name,
        summary=report.summary().splitlines(),
        report=report,
        record=facts,
        audit=audit,
        audit_note=audit_note,
        known_study=known,
        note=TAMPER_NOTE,
    )


def _known_study(ctx: AppContext, study_id: str) -> bool:
    """True when ``study_id`` (read from an uploaded record) names a study in this store."""
    if not KEY.match(study_id):
        return False
    try:
        return is_study(ctx.store, study_id)
    except (OSError, ValueError):
        return False


def _json(path: Path) -> dict[str, Any]:
    """A small JSON object from an uploaded record ({} when missing, too big or not an object)."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _record_facts(record_dir: Path) -> RecordFacts:
    meta = _json(record_dir / "record.json")
    sums = record_dir / CHECKSUMS
    record_id = None
    if sums.is_file() and not sums.is_symlink():
        digest = hashlib.sha256()
        with sums.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
        record_id = digest.hexdigest()

    def text(key: str) -> str | None:
        value = meta.get(key)
        return str(value)[:200] if isinstance(value, str) else None

    included = meta.get("input_included")
    return RecordFacts(
        study_id=text("study_id"),
        input_sha256=text("input_sha256"),
        chain_head=text("chain_head"),
        written_at=text("written_at"),
        input_included=included if isinstance(included, bool) else None,
        shared=meta.get("shared") is True,
        record_id=record_id,
    )


def _bind(check: Any, audit_dir: Path, record_dir: Path, source: str) -> AuditBinding:
    study = _json(audit_dir / "audit_manifest.json").get("study_id")
    try:
        result = check(audit_dir, record_dir)
    except (OSError, ValueError, KeyError, RecursionError) as err:
        return AuditBinding(
            source=source,
            ok=False,
            problems=[f"the audit cannot be read: {_sentence(err)}"],
            study_id=study if isinstance(study, str) else None,
        )
    return AuditBinding(
        source=source,
        ok=bool(result.ok),
        problems=[str(p) for p in result.problems],
        study_id=study if isinstance(study, str) else None,
    )
