"""The robustness audit: its status, the run (a job), its views, and attached audit folders.

The audit (:func:`qpilot.integration.simulator.audit`) re-runs a confirmed study under every
combination of eight analysis decisions and gives each gene a verdict; it is written once, to
``<studies>/simulator_audits/<study id>``, sealed with checksums and bound to the study's
decision chain. Its views are the Decision Simulator's results screen
(:class:`qsim.app.Screen`) built with :meth:`~qsim.app.Screen.from_prepared` on the engine the
integration prepares from the study (confirmed design, excluded wells, the two groups), so the
live views (what-if, analyses, effects, samples, lab) describe the audited numbers.

One screen is kept per study (and per attached folder), rebuilt when the audit changes, and
every call into it holds that screen's lock: the simulator's engine is not thread-safe.

A study whose Studio session is still blind answers 403 ``blind`` on every route here.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from fastapi import APIRouter, Request
from pydantic import BaseModel

from qpilot.core.store import StudyNotFound
from qpilot.web import views
from qpilot.web.context import AppContext, Ctx, api_error, check_key, is_session
from qpilot.web.contract import JobStarted, JobView
from qpilot.web.contract_audit import (
    AttachedAudit,
    AttachedAuditList,
    AuditAnalyses,
    AuditEffects,
    AuditGeneCard,
    AuditHow,
    AuditLab,
    AuditManifestView,
    AuditOverview,
    AuditRunRequest,
    AuditSamples,
    AuditStatus,
    AuditStudyView,
    AuditVerifyRequest,
    AuditVerifyView,
    AuditWhatIf,
    SamplesRequest,
    WhatIfRequest,
)
from qpilot.web.jobs import JobError, Progress

router = APIRouter(tags=["audit"])

M = TypeVar("M", bound=BaseModel)

AUDIT_TYPICAL_S = 55.0  # the demo's audit through this route: rebuild ~8 s + run ~45 s, measured
LOAD_TYPICAL_S = 15.0  # rebuilding the study (~8 s) and the reasonable-analyses sweep (~5 s)
KEEP_SCREENS = 3  # live screens kept in memory (each holds a study's engine)
POLL_S = 0.5
#: Files the simulator writes in this order, each starting a stage: (file, step, fraction).
#: The fractions are where each stage starts on the demo's measured timings.
RUN_STAGES = (
    ("lock.json", "Running every combination of the analysis choices", 0.17),
    (
        "grid.parquet",
        "Testing single samples and wells, and the fewest changes that flip a call",
        0.88,
    ),
    ("explain.json", "Giving each gene a verdict and writing the issue queue", 0.95),
    ("summary.json", "Comparing with your Decision Cards and sealing the audit", 0.98),
)
DROPPED = {"overview": ("model",), "gene": ("evidence",)}  # screen keys the page does not use
NO_SIMULATOR = (
    "The robustness audit needs the Decision Simulator, which is not installed here. From a "
    "qPilot clone, run pip install -e '.[sim]' and start qPilot again."
)


# ---- the screens -----------------------------------------------------------------------------


@dataclass
class _Entry:
    stamp: tuple[int, ...]
    lock: threading.RLock = field(default_factory=threading.RLock)
    screen: Any = None  # qsim.app.Screen once built


class Screens:
    """One live :class:`qsim.app.Screen` per audit, rebuilt when the audit's files change."""

    def __init__(self, keep: int = KEEP_SCREENS) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def ready(self, name: str, folder: Path) -> bool:
        """True when the screen for this audit (as it is on disk now) is built."""
        with self._lock:
            entry = self._entries.get(name)
        return entry is not None and entry.screen is not None and entry.stamp == _stamp(folder)

    def call(self, name: str, folder: Path, build: Callable[[], Any], fn: Callable[[Any], Any]):
        """``fn(screen)`` under the screen's lock, building the screen first when needed."""
        stamp = _stamp(folder)
        with self._lock:
            entry = self._entries.get(name)
            if entry is None or entry.stamp != stamp:
                entry = _Entry(stamp)
                self._entries[name] = entry
            self._entries.move_to_end(name)
            while len(self._entries) > self._keep:
                self._entries.popitem(last=False)
        with entry.lock:
            if entry.screen is None:
                entry.screen = build()
            return fn(entry.screen)


def _stamp(folder: Path) -> tuple[int, ...]:
    """Changes when the audit is replaced: the mtimes and sizes of its sealing files."""
    out: list[int] = []
    for name in ("explain.json", "summary.json", "audit_manifest.json", "AUDIT.sha256"):
        try:
            st = (folder / name).stat()
        except OSError:
            out += [0, 0]
            continue
        out += [st.st_mtime_ns, st.st_size]
    return tuple(out)


_SCREENS_LOCK = threading.Lock()


def screens(request_or_app: Any) -> Screens:
    """The server's :class:`Screens` (kept on ``app.state``; one per server)."""
    app = getattr(request_or_app, "app", request_or_app)
    with _SCREENS_LOCK:
        found = getattr(app.state, "audit_screens", None)
        if found is None:
            found = Screens()
            app.state.audit_screens = found
    return found


def _build_for_study(ctx: AppContext, study_id: str, folder: Path) -> Callable[[], Any]:
    def build() -> Any:
        from qsim.app import Screen

        from qpilot.integration.simulator import load_analysis, prepare

        prepared = prepare(load_analysis(ctx.store, study_id))
        return Screen.from_prepared(folder, prepared)

    return build


# ---- checks ----------------------------------------------------------------------------------


def _available() -> bool:
    from qpilot.integration.simulator import available

    return available()


def require_visible(ctx: AppContext, study_id: str) -> None:
    """404 for an unknown study; 403 ``blind`` while its Studio session is still blind."""
    check_key(study_id)
    try:
        result = ctx.store.get(study_id)
    except (StudyNotFound, OSError, ValueError) as err:
        raise api_error(404, "not_found", "There is no analysed study with this id.") from err
    sid = result.input_sha256[:12]
    if not is_session(ctx.store, sid):
        return
    if study_id not in views.session_meta(ctx.store, sid).get("studies", {}):
        return  # analysed outside the session (qpilot run, an agent): shown straight away
    folder = ctx.store.find_session(sid)
    signature = _signature(folder)
    with _VISIBLE_LOCK:
        if _VISIBLE.get(folder) == signature:
            return
    if not ctx.studio.results_visible(sid):
        raise api_error(
            403,
            "blind",
            "Results stay hidden until the design and the curves are confirmed in Studio.",
            session=sid,
        )
    with _VISIBLE_LOCK:
        _VISIBLE[folder] = signature


_VISIBLE: dict[Path, tuple[tuple[str, int, int], ...]] = {}  # session folder -> files when seen
_VISIBLE_LOCK = threading.Lock()


def _signature(folder: Path) -> tuple[tuple[str, int, int], ...]:
    """The session's files (name, mtime, size): any Studio write changes it.

    "Results visible" is cached against it, so a confirmation withdrawn (a write to the
    proposal log) is seen at once, while repeated audit requests skip re-assembling the design.
    """
    out = []
    for path in sorted(folder.iterdir()):
        try:
            st = path.stat()
        except OSError:
            continue
        out.append((path.name, st.st_mtime_ns, st.st_size))
    return tuple(out)


def _audit_folder(ctx: AppContext, study_id: str) -> Path:
    folder = views.audit_dir(ctx.store, study_id)
    if folder is None:
        raise api_error(
            404, "no_audit", "This study has no robustness audit yet: run the audit first."
        )
    return folder


def _attached(ctx: AppContext, name: str) -> Path:
    folder = ctx.audit_dirs.get(name)
    if folder is None:
        raise api_error(404, "not_found", "No results folder with this name was attached.")
    return folder


def _manifest(folder: Path) -> dict[str, Any] | None:
    try:
        return json.loads((folder / "audit_manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---- shaping the screen's dicts ------------------------------------------------------------


def _finite(value: Any) -> Any:
    """The same data with NaN / infinity as None (JSON has no NaN) and numpy scalars as Python."""
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, str | bytes):
        value = value.item()  # numpy scalar
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _shape(model: type[M], data: dict[str, Any], view: str = "") -> M:
    data = {k: v for k, v in data.items() if k not in DROPPED.get(view, ())}
    return model.model_validate(_finite(data))


def _gene_of(screen: Any, gene: str) -> str:
    if gene in screen.explain and gene in screen.engine.items:
        return gene
    if gene in screen.engine.study.candidates:
        raise api_error(
            404,
            "not_found",
            f"{gene} is a control gene: the audit gives a verdict to each compared gene only.",
        )
    raise api_error(404, "not_found", f"There is no gene {gene!r} in this audit.")


def _changes_of(screen: Any, changes: dict[str, str]) -> dict[str, str]:
    """The changes, or a 422 that names the valid choices / options in words."""
    names = list(screen.space.names)
    for decision, option in changes.items():
        if decision not in names:
            raise api_error(
                422,
                "bad_request",
                f"There is no analysis choice {decision!r}. The choices are: {', '.join(names)}.",
            )
        options = [o.id for o in screen.space.decision(decision).options]
        if option not in options:
            raise api_error(
                422,
                "bad_request",
                f"{option!r} is not an option of {decision!r}. Its options are: "
                f"{', '.join(options)}.",
            )
    return dict(changes)


# ---- the views, for a study and for an attached folder ----------------------------------


class _Views:
    """The view functions over one screen (shared by study audits and attached folders)."""

    @staticmethod
    def overview(screen: Any) -> AuditOverview:
        return _shape(AuditOverview, screen.overview(), "overview")

    @staticmethod
    def study(screen: Any) -> AuditStudyView:
        return _shape(AuditStudyView, screen.study_view())

    @staticmethod
    def how(screen: Any) -> AuditHow:
        return _shape(AuditHow, screen.how_view())

    @staticmethod
    def gene(screen: Any, gene: str) -> AuditGeneCard:
        return _shape(AuditGeneCard, screen.gene_card(_gene_of(screen, gene)), "gene")

    @staticmethod
    def analyses(screen: Any, gene: str) -> AuditAnalyses:
        return _shape(AuditAnalyses, screen.gene_analyses(_gene_of(screen, gene)))

    @staticmethod
    def effects(screen: Any, gene: str) -> AuditEffects:
        return _shape(AuditEffects, screen.gene_effects(_gene_of(screen, gene)))

    @staticmethod
    def lab(screen: Any, gene: str) -> AuditLab:
        return _shape(AuditLab, screen.lab_parameters(_gene_of(screen, gene)))

    @staticmethod
    def whatif(screen: Any, body: WhatIfRequest) -> AuditWhatIf:
        changes = _changes_of(screen, body.changes)
        return _shape(AuditWhatIf, screen.run_whatif(changes, list(body.genes)))

    @staticmethod
    def samples(screen: Any, body: SamplesRequest) -> AuditSamples:
        gene = _gene_of(screen, body.gene)
        return _shape(AuditSamples, screen.gene_samples(gene, _changes_of(screen, body.changes)))


def _study_view(request: Request, ctx: AppContext, study_id: str, fn: Callable[[Any], M]) -> M:
    require_visible(ctx, study_id)
    if not _available():
        raise api_error(409, "unavailable", NO_SIMULATOR)
    folder = _audit_folder(ctx, study_id)
    return _run_view(
        lambda: screens(request).call(study_id, folder, _build_for_study(ctx, study_id, folder), fn)
    )


def _attached_view(request: Request, ctx: AppContext, name: str, fn: Callable[[Any], M]) -> M:
    folder = _attached(ctx, name)
    info = _attached_info(ctx, name, folder)
    if not info.available:
        raise api_error(409, "unavailable", info.reason or "This folder's views cannot be shown.")
    if info.study_id is not None:
        require_visible(ctx, info.study_id)
    return _run_view(
        lambda: screens(request).call(
            f"attached:{name}", folder, _build_for_attached(ctx, folder, info), fn
        )
    )


def _run_view(call: Callable[[], M]) -> M:
    from qpilot.integration.simulator import AuditRefused, NotApplicable

    try:
        return call()
    except (NotApplicable, AuditRefused) as err:
        raise api_error(409, "not_applicable", _sentence(err)) from err
    except FileNotFoundError as err:
        raise api_error(409, "incomplete", f"The audit's files are incomplete: {err}") from err


def _sentence(err: BaseException, capital: bool = True) -> str:
    """An exception's message as a sentence (the simulator's messages start in lower case)."""
    text = str(err).strip() or type(err).__name__
    if capital:
        text = text[0].upper() + text[1:]
    return text if text.endswith(".") else text + "."


# ---- status and the run ----------------------------------------------------------------------


def _manifest_view(folder: Path, manifest: dict[str, Any]) -> AuditManifestView:
    sums = folder / "AUDIT.sha256"
    from qpilot.integration.simulator import sha256_file

    try:
        timings = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["timings_s"]
        seconds: float | None = round(sum(float(v) for v in timings.values()), 1)
    except (OSError, ValueError, KeyError, TypeError):
        seconds = None
    return AuditManifestView.model_validate(
        _finite(
            {
                **manifest,
                "checksums_sha256": sha256_file(sums) if sums.exists() else "",
                "seconds": seconds,
            }
        )
    )


def _decisions_since(ctx: AppContext, study_id: str, head: str | None) -> int:
    entries = ctx.store.entries(study_id)
    hashes = [e.hash for e in entries]
    if head in hashes:
        return len(hashes) - hashes.index(head) - 1
    return len(hashes) if head else 0


def _load_job(request: Request, ctx: AppContext, study_id: str, folder: Path) -> JobView | None:
    """Start (or find) the job that loads the audit's live views, unless they are loaded."""
    cache = screens(request)
    if cache.ready(study_id, folder):
        return None

    def work(progress: Progress) -> dict[str, Any]:
        progress("Rebuilding the study the audit describes")

        def warm(screen: Any) -> None:
            progress("Running every reasonable analysis once", 0.6)
            screen.reasonable()

        cache.call(study_id, folder, _build_for_study(ctx, study_id, folder), warm)
        return {"study_id": study_id}

    job = ctx.jobs.submit(
        "audit.load",
        work,
        title="Loading the audit",
        key=study_id,
        typical_s=LOAD_TYPICAL_S,
    )
    return JobView(**job.view())


@router.get("/studies/{study_id}/audit", response_model=AuditStatus)
def audit_status(study_id: str, ctx: Ctx, request: Request) -> AuditStatus:
    """Whether the study has an audit (and its manifest), one is running, or why not."""
    require_visible(ctx, study_id)
    base: dict[str, Any] = {"study_id": study_id, "typical_s": AUDIT_TYPICAL_S}
    job = ctx.jobs.latest("audit", study_id)
    if job is not None and job.status in ("queued", "running"):
        return AuditStatus(**base, status="running", job=JobView(**job.view()))
    folder = views.audit_dir(ctx.store, study_id)
    if not _available():
        return AuditStatus(**base, status="unavailable", reason=NO_SIMULATOR)
    if folder is not None:
        manifest = _manifest(folder)
        if manifest is None:
            return AuditStatus(
                **base, status="failed", reason="The audit's manifest cannot be read."
            )
        view = _manifest_view(folder, manifest)
        since = _decisions_since(ctx, study_id, view.chain_head)
        loading = _load_job(request, ctx, study_id, folder)
        return AuditStatus(
            **base,
            status="ready",
            manifest=view,
            current=since == 0,
            decisions_since=since,
            views_ready=screens(request).ready(study_id, folder),
            loading=loading,
        )
    if job is not None and job.status == "failed" and job.error:
        code = job.error.get("code", "failed")
        status = code if code in ("refused", "not_applicable", "unavailable") else "failed"
        return AuditStatus(
            **base, status=status, reason=job.error.get("message"), job=JobView(**job.view())
        )
    return AuditStatus(**base, status="none")


@router.post("/studies/{study_id}/audit", response_model=JobStarted, status_code=202)
def run_audit(
    study_id: str, ctx: Ctx, request: Request, body: AuditRunRequest | None = None
) -> JobStarted:
    """Run the robustness audit (a job, about a minute on the demo)."""
    require_visible(ctx, study_id)
    if not _available():
        raise api_error(409, "unavailable", NO_SIMULATOR)
    again = bool(body and body.again)
    running = ctx.jobs.latest("audit", study_id)
    if running is not None and running.status in ("queued", "running"):
        return JobStarted(job=JobView(**running.view()))
    if views.audit_dir(ctx.store, study_id) is not None and not again:
        raise api_error(
            409,
            "audit_exists",
            "This study already has an audit. Run it again to replace it; the earlier one is "
            "kept beside it.",
        )
    sid = ctx.store.get(study_id).input_sha256[:12]

    def work(progress: Progress) -> dict[str, Any]:
        result = _audit(ctx, study_id, progress, replace=again)
        for key in {study_id, sid}:
            ctx.bus.publish({"type": "study.changed", "key": key, "source": "audit"})
        return result

    job = ctx.jobs.submit(
        "audit",
        work,
        title="Auditing the study's robustness",
        key=study_id,
        typical_s=AUDIT_TYPICAL_S,
    )
    return JobStarted(job=JobView(**job.view()))


def _audit(ctx: AppContext, study_id: str, progress: Progress, replace: bool) -> dict[str, Any]:
    """Run the audit into a private folder, then move it into place (never half-written)."""
    from qpilot.integration import simulator

    root = ctx.store.root / "simulator_audits"
    root.mkdir(parents=True, exist_ok=True)
    partial = root / f".{study_id}.partial-{uuid.uuid4().hex[:8]}"
    progress("Rebuilding the study you confirmed and checking the audit reproduces it", 0.0)
    stop = threading.Event()
    watcher = threading.Thread(
        target=_watch_stages, args=(partial, progress, stop), daemon=True, name="audit-stages"
    )
    watcher.start()
    try:
        try:
            result = simulator.audit(ctx.store, study_id, partial)
        except simulator.NotApplicable as err:
            raise JobError(
                "not_applicable", "The audit does not apply here: " + _sentence(err, capital=False)
            ) from err
        except simulator.AuditRefused as err:
            raise JobError(
                "refused", "The audit stopped before writing anything. " + _sentence(err)
            ) from err
        except simulator.SimulatorUnavailable as err:
            raise JobError("unavailable", NO_SIMULATOR) from err
    except BaseException:
        stop.set()
        shutil.rmtree(partial, ignore_errors=True)
        raise
    finally:
        stop.set()
        watcher.join(timeout=2)
    final = root / study_id
    with ctx.lock:
        if final.exists():
            if not replace:
                shutil.rmtree(partial, ignore_errors=True)
                raise JobError("audit_exists", "Another audit of this study finished first.")
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            earlier = root / f"{study_id}.earlier-{stamp}"
            while earlier.exists():
                earlier = earlier.with_name(earlier.name + "x")
            final.rename(earlier)
        partial.rename(final)
    progress("Done", 1.0)
    return {
        "study_id": study_id,
        "analyses": result.manifest.get("analyses"),
        "verdict_counts": result.verdict_counts,
        "reproduces_qpilot": bool(result.manifest.get("reproduces_qpilot", {}).get("ok")),
        "seconds": round(result.seconds, 1),
    }


def _watch_stages(folder: Path, progress: Progress, stop: threading.Event) -> None:
    """Report the simulator's stages as its files appear (it has no progress hook)."""
    done = 0
    while not stop.wait(POLL_S) and done < len(RUN_STAGES):
        while done < len(RUN_STAGES) and (folder / RUN_STAGES[done][0]).exists():
            _, step, fraction = RUN_STAGES[done]
            progress(step, fraction)
            done += 1


# ---- verify ----------------------------------------------------------------------------------


def _verify(ctx: AppContext, folder: Path, study_id: str | None, bind: bool) -> AuditVerifyView:
    from qpilot.core.record import RecordError, write_record
    from qpilot.integration.simulator import sha256_file, verify_audit

    manifest = _manifest(folder) or {}
    sums = folder / "AUDIT.sha256"
    files = len(sums.read_text(encoding="utf-8").splitlines()) if sums.exists() else 0
    out: dict[str, Any] = {
        "files_checked": files,
        "checksums_sha256": sha256_file(sums) if sums.exists() else None,
        "lock_sha256": manifest.get("lock_sha256"),
        "audit_chain_head": manifest.get("chain_head"),
        "bound_to_record": False,
    }
    if not bind or study_id is None:
        check = verify_audit(folder)
    else:
        with tempfile.TemporaryDirectory(dir=ctx.private) as tmp:
            record = Path(tmp) / "record"
            try:
                write_record(ctx.store, study_id, record, include_input=False)
            except (RecordError, StudyNotFound, OSError) as err:
                raise api_error(
                    409, "no_record", f"The study's record cannot be written: {err}"
                ) from err
            check = verify_audit(folder, record)
        out["bound_to_record"] = True
        out["record_chain_head"] = ctx.store.chain_head(study_id)
        out["decisions_since"] = _decisions_since(ctx, study_id, manifest.get("chain_head"))
    return AuditVerifyView(ok=check.ok, summary=check.summary(), problems=check.problems, **out)


@router.post("/studies/{study_id}/audit/verify", response_model=AuditVerifyView)
def verify_study_audit(
    study_id: str, ctx: Ctx, body: AuditVerifyRequest | None = None
) -> AuditVerifyView:
    """Check the audit's checksums and manifest, and that it belongs to the study's record."""
    require_visible(ctx, study_id)
    folder = _audit_folder(ctx, study_id)
    bind = True if body is None else body.bind_to_record
    return _verify(ctx, folder, study_id, bind)


# ---- the study's views ---------------------------------------------------------------------


@router.get("/studies/{study_id}/audit/overview", response_model=AuditOverview)
def audit_overview(study_id: str, ctx: Ctx, request: Request) -> AuditOverview:
    """The audit's first screen: verdict counts, genes, choices, the top issues."""
    return _study_view(request, ctx, study_id, _Views.overview)


@router.get("/studies/{study_id}/audit/study", response_model=AuditStudyView)
def audit_study(study_id: str, ctx: Ctx, request: Request) -> AuditStudyView:
    """The Study tab: the map, which choices matter, reference stability, influence."""
    return _study_view(request, ctx, study_id, _Views.study)


@router.get("/studies/{study_id}/audit/how", response_model=AuditHow)
def audit_how(study_id: str, ctx: Ctx, request: Request) -> AuditHow:
    """How it works: stages, the call rule, the verdict rules, checks made and not made."""
    return _study_view(request, ctx, study_id, _Views.how)


@router.get("/studies/{study_id}/audit/gene/{gene:path}", response_model=AuditGeneCard)
def audit_gene(study_id: str, gene: str, ctx: Ctx, request: Request) -> AuditGeneCard:
    """One gene's card: result, verdict, what changes it, what it leans on, what to do."""
    return _study_view(request, ctx, study_id, lambda s: _Views.gene(s, gene))


@router.get("/studies/{study_id}/audit/analyses/{gene:path}", response_model=AuditAnalyses)
def audit_analyses(study_id: str, gene: str, ctx: Ctx, request: Request) -> AuditAnalyses:
    """Every reasonable analysis of one gene."""
    return _study_view(request, ctx, study_id, lambda s: _Views.analyses(s, gene))


@router.get("/studies/{study_id}/audit/effects/{gene:path}", response_model=AuditEffects)
def audit_effects(study_id: str, gene: str, ctx: Ctx, request: Request) -> AuditEffects:
    """One choice at a time for one gene."""
    return _study_view(request, ctx, study_id, lambda s: _Views.effects(s, gene))


@router.get("/studies/{study_id}/audit/lab/{gene:path}", response_model=AuditLab)
def audit_lab(study_id: str, gene: str, ctx: Ctx, request: Request) -> AuditLab:
    """The assay's lab parameters and the planned control genes' stability."""
    return _study_view(request, ctx, study_id, lambda s: _Views.lab(s, gene))


@router.post("/studies/{study_id}/audit/whatif", response_model=AuditWhatIf)
def audit_whatif(study_id: str, body: WhatIfRequest, ctx: Ctx, request: Request) -> AuditWhatIf:
    """Every gene under other choices (a live engine run; nothing is written)."""
    return _study_view(request, ctx, study_id, lambda s: _Views.whatif(s, body))


@router.post("/studies/{study_id}/audit/samples", response_model=AuditSamples)
def audit_samples(study_id: str, body: SamplesRequest, ctx: Ctx, request: Request) -> AuditSamples:
    """One gene's samples under a set of choices (a live engine run; nothing is written)."""
    return _study_view(request, ctx, study_id, lambda s: _Views.samples(s, body))


# ---- attached folders (qpilot app --audit DIR) -------------------------------------------


def _attached_info(ctx: AppContext, name: str, folder: Path) -> AttachedAudit:
    try:
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AttachedAudit(
            name=name,
            source="",
            qpilot_audit=False,
            available=False,
            reason="This folder has no complete results (summary.json is missing).",
        )
    manifest = _manifest(folder)
    source = str((summary.get("source") or {}).get("name") or "the benchmark study")
    counts = {str(k): int(v) for k, v in (summary.get("verdicts") or {}).get("counts", {}).items()}
    info: dict[str, Any] = {
        "name": name,
        "source": source,
        "qpilot_audit": manifest is not None,
        "analyses": (summary.get("ledger") or {}).get("total_cells"),
        "verdict_counts": counts,
        "available": True,
    }
    if not _available():
        info.update(available=False, reason=NO_SIMULATOR)
    elif manifest is not None:
        study_id = str(manifest.get("study_id", ""))
        info["study_id"] = study_id or None
        try:
            ctx.store.get(study_id)
        except (StudyNotFound, OSError, ValueError):
            info.update(
                available=False,
                reason=(
                    f"This audit describes qPilot study {study_id}, which is not in this "
                    "store; its views need that study."
                ),
            )
    return AttachedAudit(**info)


def _build_for_attached(ctx: AppContext, folder: Path, info: AttachedAudit) -> Callable[[], Any]:
    def build() -> Any:
        from qsim.app import Screen

        if info.study_id is None:
            return Screen(folder)  # a plain simulator run: it reads its own input file
        from qpilot.integration.simulator import load_analysis, prepare

        return Screen.from_prepared(folder, prepare(load_analysis(ctx.store, info.study_id)))

    return build


@router.get("/audits", response_model=AttachedAuditList)
def list_attached_audits(ctx: Ctx) -> AttachedAuditList:
    """Results folders attached read-only with ``qpilot app --audit DIR``."""
    return AttachedAuditList(
        audits=[
            _attached_info(ctx, name, folder) for name, folder in sorted(ctx.audit_dirs.items())
        ]
    )


@router.get("/audits/{name}", response_model=AttachedAudit)
def attached_audit(name: str, ctx: Ctx) -> AttachedAudit:
    """One attached folder: what it describes and whether its views can be shown."""
    return _attached_info(ctx, name, _attached(ctx, name))


@router.get("/audits/{name}/overview", response_model=AuditOverview)
def attached_overview(name: str, ctx: Ctx, request: Request) -> AuditOverview:
    """An attached folder's first screen."""
    return _attached_view(request, ctx, name, _Views.overview)


@router.get("/audits/{name}/study", response_model=AuditStudyView)
def attached_study(name: str, ctx: Ctx, request: Request) -> AuditStudyView:
    """An attached folder's Study tab."""
    return _attached_view(request, ctx, name, _Views.study)


@router.get("/audits/{name}/how", response_model=AuditHow)
def attached_how(name: str, ctx: Ctx, request: Request) -> AuditHow:
    """An attached folder's How it works."""
    return _attached_view(request, ctx, name, _Views.how)


@router.get("/audits/{name}/gene/{gene:path}", response_model=AuditGeneCard)
def attached_gene(name: str, gene: str, ctx: Ctx, request: Request) -> AuditGeneCard:
    """One gene's card in an attached folder."""
    return _attached_view(request, ctx, name, lambda s: _Views.gene(s, gene))


@router.get("/audits/{name}/analyses/{gene:path}", response_model=AuditAnalyses)
def attached_analyses(name: str, gene: str, ctx: Ctx, request: Request) -> AuditAnalyses:
    """Every reasonable analysis of one gene in an attached folder."""
    return _attached_view(request, ctx, name, lambda s: _Views.analyses(s, gene))


@router.get("/audits/{name}/effects/{gene:path}", response_model=AuditEffects)
def attached_effects(name: str, gene: str, ctx: Ctx, request: Request) -> AuditEffects:
    """One choice at a time for one gene in an attached folder."""
    return _attached_view(request, ctx, name, lambda s: _Views.effects(s, gene))


@router.get("/audits/{name}/lab/{gene:path}", response_model=AuditLab)
def attached_lab(name: str, gene: str, ctx: Ctx, request: Request) -> AuditLab:
    """Lab parameters for one gene in an attached folder."""
    return _attached_view(request, ctx, name, lambda s: _Views.lab(s, gene))


@router.post("/audits/{name}/whatif", response_model=AuditWhatIf)
def attached_whatif(name: str, body: WhatIfRequest, ctx: Ctx, request: Request) -> AuditWhatIf:
    """Every gene under other choices, in an attached folder."""
    return _attached_view(request, ctx, name, lambda s: _Views.whatif(s, body))


@router.post("/audits/{name}/samples", response_model=AuditSamples)
def attached_samples(name: str, body: SamplesRequest, ctx: Ctx, request: Request) -> AuditSamples:
    """One gene's samples under a set of choices, in an attached folder."""
    return _attached_view(request, ctx, name, lambda s: _Views.samples(s, body))


@router.post("/audits/{name}/verify", response_model=AuditVerifyView)
def attached_verify(name: str, ctx: Ctx, body: AuditVerifyRequest | None = None) -> AuditVerifyView:
    """Check an attached audit's checksums (and its binding, when its study is here)."""
    folder = _attached(ctx, name)
    info = _attached_info(ctx, name, folder)
    if info.study_id is not None and info.available:
        require_visible(ctx, info.study_id)
    bind = (True if body is None else body.bind_to_record) and info.available
    return _verify(ctx, folder, info.study_id, bind)
