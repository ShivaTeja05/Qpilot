"""The robustness audit: its status, the run (a job), its views, and attached audit folders.

The audit (:func:`qpilot.integration.simulator.audit`) re-runs a confirmed study under every
combination of its analysis decisions (eight; nine with technical replicates) and gives each
gene a verdict; it is written once, to
``<studies>/simulator_audits/<study id>``, sealed with checksums and bound to the study's
decision chain. Its views are the Decision Simulator's results screen
(:class:`qsim.app.Screen`) built with :meth:`~qsim.app.Screen.from_prepared` on the engine the
integration prepares from the study (confirmed design, excluded wells, the two groups), so the
live views (what-if, analyses, effects, samples, lab) describe the audited numbers.

One screen is kept per study (and per attached folder), rebuilt when the audit changes, and
every call into it holds that screen's lock: the simulator's engine is not thread-safe. Other
routes reach the same screen through :func:`audit_screen` (Ask uses its Asker).

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
import weakref
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from qpilot.core.store import StudyNotFound
from qpilot.web import views
from qpilot.web.context import AppContext, Ctx, api_error, check_key, is_session
from qpilot.web.contract import JobStarted, JobView
from qpilot.web.contract_audit import (
    AttachedAudit,
    AttachedAuditList,
    AuditAnalyses,
    AuditCheck,
    AuditEffects,
    AuditFile,
    AuditFiles,
    AuditGeneCard,
    AuditHow,
    AuditIssues,
    AuditLab,
    AuditLoadResult,
    AuditManifestView,
    AuditOverview,
    AuditRunRequest,
    AuditRunResult,
    AuditSamples,
    AuditSamplesRequest,
    AuditStatus,
    AuditStudyView,
    AuditVerifyRequest,
    AuditVerifyView,
    AuditWhatIf,
    AuditWhatIfRequest,
)
from qpilot.web.jobs import JobError, Progress

router = APIRouter(tags=["audit"])

#: The result model of each job this module starts (typed in the page's generated schema).
JOB_RESULTS = {"audit": AuditRunResult, "audit.load": AuditLoadResult, "audit.check": AuditCheck}

M = TypeVar("M", bound=BaseModel)

AUDIT_TYPICAL_S = 55.0  # the demo's audit through this route: rebuild ~8 s + run ~45 s, measured
LOAD_TYPICAL_S = 15.0  # rebuilding the study (~8 s) and the reasonable-analyses sweep (~5 s)
LOAD_RETRY_S = 60.0  # a failed load is reported for this long before a view tries again
CHECK_TYPICAL_S = 9.0  # rebuilding the study and the reproduction check, measured on the demo
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
#: Files of a plain simulator run that may be downloaded (a qPilot audit lists its own files).
RUN_FILES = (
    "REPORT.md",
    "summary.json",
    "explain.json",
    "genes.csv",
    "decisions.csv",
    "issues.json",
    "issues.csv",
    "lock.json",
    "one_sample_flips.csv",
    "reference_wells_top50.csv",
    "validation_untergasser.json",
)
MEDIA = {
    ".json": "application/json",
    ".csv": "text/csv; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".sha256": "text/plain; charset=utf-8",
}
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

    def call(
        self,
        name: str,
        folder: Path,
        build: Callable[[], Any] | None,
        fn: Callable[[Any], Any],
    ):
        """``fn(screen)`` under the screen's lock, building the screen first when needed.

        With ``build=None`` a screen not built yet raises :class:`NotLoaded` at once: request
        threads never wait for a build (a load job makes it), so a slow build cannot take every
        thread the server has.
        """
        stamp = _stamp(folder)
        with self._lock:
            entry = self._entries.get(name)
            if entry is None or entry.stamp != stamp:
                entry = _Entry(stamp)
                self._entries[name] = entry
            self._entries.move_to_end(name)
            while len(self._entries) > self._keep:
                self._entries.popitem(last=False)
        if build is None and entry.screen is None:
            raise NotLoaded(name)
        with entry.lock:
            if entry.screen is None:
                if build is None:
                    raise NotLoaded(name)
                entry.screen = build()
            return fn(entry.screen)


class NotLoaded(Exception):
    """The audit's screen is not built yet."""


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


_SCREENS: dict[int, Screens] = {}  # id(AppContext) -> its screens, dropped with the context
_SCREENS_LOCK = threading.Lock()


def screens(ctx: AppContext) -> Screens:
    """The server's :class:`Screens` (one per :class:`AppContext`)."""
    with _SCREENS_LOCK:
        found = _SCREENS.get(id(ctx))
        if found is None:
            found = _SCREENS[id(ctx)] = Screens()
            weakref.finalize(ctx, _SCREENS.pop, id(ctx), None)
    return found


def _ask_client(ctx: AppContext) -> Any:
    """A model client on the page's model (the one its model chip shows)."""
    from qpilot.ai.client import ModelClient

    return ModelClient(backend=ctx.studio.client.backend)


def _build_for_study(ctx: AppContext, study_id: str, folder: Path) -> Callable[[], Any]:
    def build() -> Any:
        from qsim.app import Screen

        from qpilot.integration.simulator import load_analysis, prepare

        screen = Screen.from_prepared(folder, prepare(load_analysis(ctx.store, study_id)))
        screen.use_ask_client(_ask_client(ctx))
        return screen

    return build


def audit_screen(ctx: AppContext, study_id: str) -> Any:
    """The study's audit screen (:class:`qsim.app.Screen`) for other routes, or None.

    None when the simulator is missing or the study has no audit. Raises the same refusals as
    the audit routes (404 for an unknown study, 403 ``blind``). The screen's
    :meth:`~qsim.app.Screen.ask` may be called from any thread: it serialises questions, and its
    Ask engine takes the screen's engine lock for each engine call. The first call builds the
    screen (about 8 s on the demo).
    """
    require_visible(ctx, study_id)
    if not _available():
        return None
    folder = views.audit_dir(ctx.store, study_id)
    if folder is None:
        return None

    def current(screen: Any) -> Any:
        screen.use_ask_client(_ask_client(ctx))  # the page's model may have changed
        return screen

    return screens(ctx).call(study_id, folder, _build_for_study(ctx, study_id, folder), current)


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
        if path.name.startswith("."):
            continue  # the store's lock file is touched by every read
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
    def issues(screen: Any) -> AuditIssues:
        return _shape(AuditIssues, screen.issue_list())

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
    def whatif(screen: Any, body: AuditWhatIfRequest) -> AuditWhatIf:
        changes = _changes_of(screen, body.changes)
        return _shape(AuditWhatIf, screen.run_whatif(changes, list(body.genes)))

    @staticmethod
    def samples(screen: Any, body: AuditSamplesRequest) -> AuditSamples:
        gene = _gene_of(screen, body.gene)
        return _shape(AuditSamples, screen.gene_samples(gene, _changes_of(screen, body.changes)))


def _study_view(ctx: AppContext, study_id: str, fn: Callable[[Any], M]) -> M:
    require_visible(ctx, study_id)
    if not _available():
        raise api_error(409, "unavailable", NO_SIMULATOR)
    folder = _audit_folder(ctx, study_id)
    build = _build_for_study(ctx, study_id, folder)
    return _run_view(ctx, study_id, folder, build, fn, key=study_id)


def _attached_view(ctx: AppContext, name: str, fn: Callable[[Any], M]) -> M:
    folder = _attached(ctx, name)
    info = _attached_info(ctx, name, folder)
    if not info.available:
        raise api_error(409, "unavailable", info.reason or "This folder's views cannot be shown.")
    if info.study_id is not None:
        require_visible(ctx, info.study_id)
    build = _build_for_attached(ctx, folder, info)
    return _run_view(ctx, _attached_key(name), folder, build, fn, key=_attached_key(name))


def _attached_key(name: str) -> str:
    return f"audits/{name}"


def _run_view(
    ctx: AppContext,
    name: str,
    folder: Path,
    build: Callable[[], Any],
    fn: Callable[[Any], M],
    key: str,
) -> M:
    """``fn`` on the loaded screen; while it loads, 409 ``loading`` with the job loading it."""
    try:
        return screens(ctx).call(name, folder, None, fn)
    except NotLoaded:
        pass
    failed = ctx.jobs.latest("audit.load", key)
    if failed is not None and failed.status == "failed" and failed.error:
        if time.time() - (failed.finished or 0) < LOAD_RETRY_S:
            raise api_error(
                409, failed.error.get("code", "failed"), failed.error.get("message", "")
            )
    job = _load_job(ctx, name, folder, build, key)
    raise api_error(
        409,
        "loading",
        "The audit's live views are loading (about 15 s the first time on the demo). Ask again "
        "when the job is done.",
        job=job.model_dump() if job is not None else None,
    )


def _sentence(err: BaseException, capital: bool = True) -> str:
    """An exception's message as a sentence (the simulator's messages start in lower case)."""
    text = str(err).strip() or type(err).__name__
    if capital:
        text = text[0].upper() + text[1:]
    return text if text.endswith(".") else text + "."


# ---- status, the pre-check and the run -------------------------------------------------------


def _manifest_view(folder: Path, manifest: dict[str, Any]) -> AuditManifestView:
    from qpilot.integration.simulator import sha256_file

    sums = folder / "AUDIT.sha256"
    try:
        timings = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["timings_s"]
        seconds: float | None = round(sum(float(v) for v in timings.values()), 1)
    except (OSError, ValueError, KeyError, TypeError):
        seconds = None
    try:
        created: float | None = sums.stat().st_mtime
    except OSError:
        created = None
    return AuditManifestView.model_validate(
        _finite(
            {
                **manifest,
                "checksums_sha256": sha256_file(sums) if sums.exists() else "",
                "seconds": seconds,
                "created_at": created,
            }
        )
    )


def _chain_hashes(ctx: AppContext, study_id: str) -> list[str]:
    return [e.hash for e in ctx.store.entries(study_id)]


def _decisions_since(hashes: list[str], head: str | None) -> int:
    if head in hashes:
        return len(hashes) - hashes.index(head) - 1
    return len(hashes) if head else 0


def _load_job(
    ctx: AppContext, name: str, folder: Path, build: Callable[[], Any], key: str
) -> JobView | None:
    """Start (or find) the job that loads an audit's live views, unless they are loaded."""
    from qpilot.integration.simulator import AuditRefused, NotApplicable

    cache = screens(ctx)
    if cache.ready(name, folder):
        return None

    def work(progress: Progress) -> dict[str, Any]:
        progress("Rebuilding the study the audit describes")

        def warm(screen: Any) -> None:
            progress("Running every reasonable analysis once", 0.6)
            screen.reasonable()

        try:
            cache.call(name, folder, build, lambda screen: None)
            cache.call(name, folder, None, warm)  # views may run in between
        except (NotApplicable, AuditRefused) as err:
            raise JobError("not_applicable", _sentence(err)) from err
        except FileNotFoundError as err:
            raise JobError("incomplete", f"The audit's files are incomplete: {err}") from err
        except NotLoaded as err:  # replaced on disk meanwhile: the next view loads it again
            raise JobError("incomplete", "The audit changed while it was loading.") from err
        return {"study_id": key}

    job = ctx.jobs.submit(
        "audit.load", work, title="Loading the audit", key=key, typical_s=LOAD_TYPICAL_S
    )
    return JobView(**job.view())


def _check(ctx: AppContext, study_id: str) -> dict[str, Any]:
    """Whether the audit applies to the study, and its scope: the run's first step, alone."""
    from qpilot.integration import simulator
    from qpilot.qpcr.export import ExportError

    try:
        analysis = simulator.load_analysis(ctx.store, study_id)
        prepared = simulator.prepare(analysis)
        reproduced = simulator.reproduction(prepared, analysis.result)
    except ExportError as err:
        reason = "The audit cannot rebuild this study: " + _sentence(err, capital=False)
        return {"applicable": False, "code": "not_applicable", "reason": reason}
    except simulator.NotApplicable as err:
        reason = "The audit does not apply here: " + _sentence(err, capital=False)
        return {"applicable": False, "code": "not_applicable", "reason": reason}
    except simulator.AuditRefused as err:
        reason = "The audit would stop before writing anything. " + _sentence(err)
        return {"applicable": False, "code": "refused", "reason": reason}
    if not reproduced["ok"]:
        reason = (
            "The audit would stop before writing anything: the simulator's planned analysis "
            "does not reproduce qPilot's result for this study (genes that differ: "
            f"{', '.join(reproduced['mismatched'][:5]) or 'the gene lists differ'})."
        )
        return {"applicable": False, "code": "refused", "reason": reason}
    return {"applicable": True, "code": None, "reason": None, "scope": _finite(prepared.scope)}


def _check_job(ctx: AppContext, study_id: str) -> tuple[AuditCheck | None, JobView | None]:
    """The pre-check's answer once known, else the job finding it (started when needed)."""
    job = ctx.jobs.latest("audit.check", study_id)
    if job is not None and job.status == "done" and isinstance(job.result, dict):
        return AuditCheck.model_validate(job.result), None
    retry = job is not None and job.status == "failed" and time.time() - (job.finished or 0) > 60
    if job is None or retry:

        def work(progress: Progress) -> dict[str, Any]:
            progress("Rebuilding the study and checking the audit applies")
            return _check(ctx, study_id)

        job = ctx.jobs.submit(
            "audit.check",
            work,
            title="Checking the audit applies",
            key=study_id,
            typical_s=CHECK_TYPICAL_S,
        )
    return None, JobView(**job.view())


@router.get("/studies/{study_id}/audit", response_model=AuditStatus)
def audit_status(study_id: str, ctx: Ctx) -> AuditStatus:
    """Whether the study has an audit (and its manifest), one is running, or why not."""
    require_visible(ctx, study_id)
    base: dict[str, Any] = {"study_id": study_id, "typical_s": AUDIT_TYPICAL_S}
    job = ctx.jobs.latest("audit", study_id)
    if job is not None and job.status in ("queued", "running"):
        return AuditStatus(**base, status="running", job=JobView(**job.view()))
    if not _available():
        return AuditStatus(**base, status="unavailable", reason=NO_SIMULATOR)
    folder = views.audit_dir(ctx.store, study_id)
    if folder is not None:
        manifest = _manifest(folder)
        if manifest is None:
            return AuditStatus(
                **base, status="failed", reason="The audit's manifest cannot be read."
            )
        view = _manifest_view(folder, manifest)
        since = _decisions_since(_chain_hashes(ctx, study_id), view.chain_head)
        return AuditStatus(
            **base,
            status="ready",
            manifest=view,
            current=since == 0,
            decisions_since=since,
            loading=_load_job(
                ctx, study_id, folder, _build_for_study(ctx, study_id, folder), study_id
            ),
            views_ready=screens(ctx).ready(study_id, folder),
        )
    if job is not None and job.status == "failed" and job.error:
        code = job.error.get("code", "failed")
        status = code if code in ("refused", "not_applicable", "unavailable") else "failed"
        return AuditStatus(
            **base, status=status, reason=job.error.get("message"), job=JobView(**job.view())
        )
    check, checking = _check_job(ctx, study_id)
    if check is not None and not check.applicable:
        return AuditStatus(**base, status=check.code or "refused", reason=check.reason, check=check)
    return AuditStatus(**base, status="none", check=check, checking=checking)


@router.post("/studies/{study_id}/audit", response_model=JobStarted, status_code=202)
def run_audit(study_id: str, ctx: Ctx, body: AuditRunRequest | None = None) -> JobStarted:
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
    checked = ctx.jobs.latest("audit.check", study_id)
    if checked is not None and checked.status == "done" and isinstance(checked.result, dict):
        if not checked.result.get("applicable", True):
            code = checked.result.get("code") or "refused"
            raise api_error(409, code, checked.result.get("reason") or "The audit cannot run.")
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
    from qpilot.qpcr.export import ExportError

    root = ctx.store.root / "simulator_audits"
    root.mkdir(parents=True, exist_ok=True)
    partial = root / f".{study_id}.partial-{uuid.uuid4().hex[:8]}"
    progress("Rebuilding the study you confirmed and checking the audit reproduces it", 0.0)
    told = [0.0]  # when the grid's count was last told (0: not yet)
    stop = threading.Event()
    watcher = threading.Thread(
        target=_watch_stages,
        args=(partial, progress, stop, lambda stage: stage == 0 and told[0] > 0),
        daemon=True,
        name="audit-stages",
    )
    watcher.start()

    def grid(done: int, total: int) -> None:
        # The longest stage, told as it goes (at most twice a second).
        now = time.monotonic()
        if done < total and now - told[0] < 0.5:
            return
        told[0] = now
        start, end = RUN_STAGES[0][2], RUN_STAGES[1][2]
        progress(
            f"{RUN_STAGES[0][1]}: {done:,} of {total:,} analyses",
            start + (end - start) * done / max(1, total),
        )

    try:
        try:
            result = simulator.audit(ctx.store, study_id, partial, progress=grid)
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
        except ExportError as err:
            raise JobError(
                "not_applicable",
                "The audit cannot rebuild this study: " + _sentence(err, capital=False),
            ) from err
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


def _watch_stages(
    folder: Path,
    progress: Progress,
    stop: threading.Event,
    covered: Callable[[int], bool] = lambda stage: False,
) -> None:
    """Report the simulator's stages as its files appear (a stage told otherwise is skipped)."""
    done = 0
    while not stop.wait(POLL_S) and done < len(RUN_STAGES):
        while done < len(RUN_STAGES) and (folder / RUN_STAGES[done][0]).exists():
            _, step, fraction = RUN_STAGES[done]
            if not covered(done):
                progress(step, fraction)
            done += 1


# ---- verify and files ------------------------------------------------------------------------


def _listed(folder: Path) -> dict[str, str]:
    """The audit's own file list (AUDIT.sha256): name -> sha256."""
    try:
        text = (folder / "AUDIT.sha256").read_text(encoding="utf-8")
    except (OSError, ValueError):  # missing, or not text
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        digest, _, name = line.partition("  ")
        if name and len(digest) == 64:
            out[name] = digest
    return out


def _files(folder: Path) -> list[AuditFile]:
    listed = _listed(folder)
    names = (
        [*sorted(listed), "AUDIT.sha256"]
        if listed
        else [n for n in RUN_FILES if (folder / n).is_file()]
    )
    root = folder.resolve()
    out = []
    for name in names:
        path = folder / name
        if "/" in name or "\x00" in name or not path.is_file():
            continue
        if path.resolve().parent != root:
            continue  # a link to a file elsewhere: never listed, never served
        out.append(AuditFile(name=name, bytes=path.stat().st_size, sha256=listed.get(name)))
    return out


def _download(folder: Path, name: str) -> FileResponse:
    missing = api_error(404, "not_found", "This audit has no file with that name.")
    if name not in {f.name for f in _files(folder)}:  # checked before the name meets the disk
        raise missing
    path = (folder / name).resolve()
    if path.parent != folder.resolve() or not path.is_file():
        raise missing
    media = MEDIA.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=name)


def _verify_files(folder: Path, record: Path | None) -> Any:
    """:func:`~qpilot.integration.simulator.verify_audit`, with unreadable files as problems."""
    from qpilot.integration.simulator import AuditCheck as Check
    from qpilot.integration.simulator import verify_audit

    try:
        return verify_audit(folder, record)
    except (ValueError, OSError) as err:  # a damaged manifest or lock: not JSON, unreadable
        damaged = [
            name
            for name in ("audit_manifest.json", "lock.json")
            if (folder / name).exists() and not _readable_json(folder / name)
        ]
        problems = [f"{name} cannot be read (damaged)" for name in damaged]
        return Check(False, problems or [f"the audit's files cannot be read: {err}"])


def _readable_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return True


def _verify(ctx: AppContext, folder: Path, study_id: str | None, bind: bool) -> AuditVerifyView:
    from qpilot.core.record import RecordError, write_record
    from qpilot.integration.simulator import sha256_file

    manifest = _manifest(folder) or {}
    sums = folder / "AUDIT.sha256"
    files = _files(folder)
    head = manifest.get("chain_head")
    out: dict[str, Any] = {
        "files_checked": len(_listed(folder)),
        "files": files,
        "checksums_sha256": sha256_file(sums) if sums.exists() else None,
        "lock_sha256": manifest.get("lock_sha256"),
        "audit_chain_head": head,
        "bound_to_record": False,
    }
    if not bind or study_id is None:
        check = _verify_files(folder, None)
    else:
        with tempfile.TemporaryDirectory(dir=ctx.private) as tmp:
            record = Path(tmp) / "record"
            try:
                write_record(ctx.store, study_id, record, include_input=False)
            except (RecordError, StudyNotFound, OSError) as err:
                raise api_error(
                    409, "no_record", f"The study's record cannot be written: {err}"
                ) from err
            check = _verify_files(folder, record)
        hashes = _chain_hashes(ctx, study_id)
        since = _decisions_since(hashes, head)
        out.update(
            bound_to_record=True,
            record_chain_head=ctx.store.chain_head(study_id),
            decisions_since=since,
            head_in_chain=head in hashes if head else None,
            is_current=since == 0,
        )
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


@router.get("/studies/{study_id}/audit/files", response_model=AuditFiles)
def audit_files(study_id: str, ctx: Ctx) -> AuditFiles:
    """The audit's files (name, size, sha256 from its AUDIT.sha256), for download."""
    require_visible(ctx, study_id)
    return AuditFiles(files=_files(_audit_folder(ctx, study_id)))


@router.get("/studies/{study_id}/audit/files/{name}", response_class=FileResponse)
def audit_file(study_id: str, name: str, ctx: Ctx) -> FileResponse:
    """Download one of the audit's files (only those its AUDIT.sha256 lists)."""
    require_visible(ctx, study_id)
    return _download(_audit_folder(ctx, study_id), name)


# ---- the study's views ---------------------------------------------------------------------


@router.get("/studies/{study_id}/audit/overview", response_model=AuditOverview)
def audit_overview(study_id: str, ctx: Ctx) -> AuditOverview:
    """The audit's first screen: verdict counts, genes, choices, the top issues."""
    return _study_view(ctx, study_id, _Views.overview)


@router.get("/studies/{study_id}/audit/study", response_model=AuditStudyView)
def audit_study(study_id: str, ctx: Ctx) -> AuditStudyView:
    """The Study tab: the map, which choices matter, reference stability, influence."""
    return _study_view(ctx, study_id, _Views.study)


@router.get("/studies/{study_id}/audit/how", response_model=AuditHow)
def audit_how(study_id: str, ctx: Ctx) -> AuditHow:
    """How it works: stages, the call rule, the verdict rules, checks made and not made."""
    return _study_view(ctx, study_id, _Views.how)


@router.get("/studies/{study_id}/audit/issues", response_model=AuditIssues)
def audit_issues(study_id: str, ctx: Ctx) -> AuditIssues:
    """The whole investigation queue, in its order."""
    return _study_view(ctx, study_id, _Views.issues)


@router.get("/studies/{study_id}/audit/gene/{gene:path}", response_model=AuditGeneCard)
def audit_gene(study_id: str, gene: str, ctx: Ctx) -> AuditGeneCard:
    """One gene's card: result, verdict, what changes it, what it leans on, what to do."""
    return _study_view(ctx, study_id, lambda s: _Views.gene(s, gene))


@router.get("/studies/{study_id}/audit/analyses/{gene:path}", response_model=AuditAnalyses)
def audit_analyses(study_id: str, gene: str, ctx: Ctx) -> AuditAnalyses:
    """Every reasonable analysis of one gene."""
    return _study_view(ctx, study_id, lambda s: _Views.analyses(s, gene))


@router.get("/studies/{study_id}/audit/effects/{gene:path}", response_model=AuditEffects)
def audit_effects(study_id: str, gene: str, ctx: Ctx) -> AuditEffects:
    """One choice at a time for one gene."""
    return _study_view(ctx, study_id, lambda s: _Views.effects(s, gene))


@router.get("/studies/{study_id}/audit/lab/{gene:path}", response_model=AuditLab)
def audit_lab(study_id: str, gene: str, ctx: Ctx) -> AuditLab:
    """The assay's lab parameters and the planned control genes' stability."""
    return _study_view(ctx, study_id, lambda s: _Views.lab(s, gene))


@router.post("/studies/{study_id}/audit/whatif", response_model=AuditWhatIf)
def audit_whatif(study_id: str, body: AuditWhatIfRequest, ctx: Ctx) -> AuditWhatIf:
    """Every gene under other choices (a live engine run; nothing is written)."""
    return _study_view(ctx, study_id, lambda s: _Views.whatif(s, body))


@router.post("/studies/{study_id}/audit/samples", response_model=AuditSamples)
def audit_samples(study_id: str, body: AuditSamplesRequest, ctx: Ctx) -> AuditSamples:
    """One gene's samples under a set of choices (a live engine run; nothing is written)."""
    return _study_view(ctx, study_id, lambda s: _Views.samples(s, body))


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
            screen = Screen(folder)  # a plain simulator run: it reads its own input file
        else:
            from qpilot.integration.simulator import load_analysis, prepare

            prepared = prepare(load_analysis(ctx.store, info.study_id))
            screen = Screen.from_prepared(folder, prepared)
        screen.use_ask_client(_ask_client(ctx))
        return screen

    return build


def _attached_visible(ctx: AppContext, name: str) -> tuple[Path, AttachedAudit]:
    folder = _attached(ctx, name)
    info = _attached_info(ctx, name, folder)
    if info.study_id is not None and info.available:
        require_visible(ctx, info.study_id)
    return folder, info


@router.get("/audits", response_model=AttachedAuditList)
def list_attached_audits(ctx: Ctx) -> AttachedAuditList:
    """Results folders attached read-only with ``qpilot app --audit DIR``."""
    out = []
    for name, folder in sorted(ctx.audit_dirs.items()):
        info = _attached_info(ctx, name, folder)
        info.views_ready = screens(ctx).ready(_attached_key(name), folder)
        out.append(info)
    return AttachedAuditList(audits=out)


@router.get("/audits/{name}", response_model=AttachedAudit)
def attached_audit(name: str, ctx: Ctx) -> AttachedAudit:
    """One attached folder: what it describes; opening it starts loading its live views."""
    folder = _attached(ctx, name)
    info = _attached_info(ctx, name, folder)
    if info.available:
        if info.study_id is not None:
            require_visible(ctx, info.study_id)
        key = _attached_key(name)
        build = _build_for_attached(ctx, folder, info)
        info.loading = _load_job(ctx, key, folder, build, key)
        info.views_ready = screens(ctx).ready(key, folder)
    return info


@router.get("/audits/{name}/overview", response_model=AuditOverview)
def attached_overview(name: str, ctx: Ctx) -> AuditOverview:
    """An attached folder's first screen."""
    return _attached_view(ctx, name, _Views.overview)


@router.get("/audits/{name}/study", response_model=AuditStudyView)
def attached_study(name: str, ctx: Ctx) -> AuditStudyView:
    """An attached folder's Study tab."""
    return _attached_view(ctx, name, _Views.study)


@router.get("/audits/{name}/how", response_model=AuditHow)
def attached_how(name: str, ctx: Ctx) -> AuditHow:
    """An attached folder's How it works."""
    return _attached_view(ctx, name, _Views.how)


@router.get("/audits/{name}/issues", response_model=AuditIssues)
def attached_issues(name: str, ctx: Ctx) -> AuditIssues:
    """An attached folder's whole investigation queue."""
    return _attached_view(ctx, name, _Views.issues)


@router.get("/audits/{name}/gene/{gene:path}", response_model=AuditGeneCard)
def attached_gene(name: str, gene: str, ctx: Ctx) -> AuditGeneCard:
    """One gene's card in an attached folder."""
    return _attached_view(ctx, name, lambda s: _Views.gene(s, gene))


@router.get("/audits/{name}/analyses/{gene:path}", response_model=AuditAnalyses)
def attached_analyses(name: str, gene: str, ctx: Ctx) -> AuditAnalyses:
    """Every reasonable analysis of one gene in an attached folder."""
    return _attached_view(ctx, name, lambda s: _Views.analyses(s, gene))


@router.get("/audits/{name}/effects/{gene:path}", response_model=AuditEffects)
def attached_effects(name: str, gene: str, ctx: Ctx) -> AuditEffects:
    """One choice at a time for one gene in an attached folder."""
    return _attached_view(ctx, name, lambda s: _Views.effects(s, gene))


@router.get("/audits/{name}/lab/{gene:path}", response_model=AuditLab)
def attached_lab(name: str, gene: str, ctx: Ctx) -> AuditLab:
    """Lab parameters for one gene in an attached folder."""
    return _attached_view(ctx, name, lambda s: _Views.lab(s, gene))


@router.post("/audits/{name}/whatif", response_model=AuditWhatIf)
def attached_whatif(name: str, body: AuditWhatIfRequest, ctx: Ctx) -> AuditWhatIf:
    """Every gene under other choices, in an attached folder."""
    return _attached_view(ctx, name, lambda s: _Views.whatif(s, body))


@router.post("/audits/{name}/samples", response_model=AuditSamples)
def attached_samples(name: str, body: AuditSamplesRequest, ctx: Ctx) -> AuditSamples:
    """One gene's samples under a set of choices, in an attached folder."""
    return _attached_view(ctx, name, lambda s: _Views.samples(s, body))


@router.post("/audits/{name}/verify", response_model=AuditVerifyView)
def attached_verify(name: str, ctx: Ctx, body: AuditVerifyRequest | None = None) -> AuditVerifyView:
    """Check an attached audit's checksums (and its binding, when its study is here)."""
    folder, info = _attached_visible(ctx, name)
    bind = (True if body is None else body.bind_to_record) and info.available
    return _verify(ctx, folder, info.study_id, bind)


@router.get("/audits/{name}/files", response_model=AuditFiles)
def attached_files(name: str, ctx: Ctx) -> AuditFiles:
    """An attached folder's downloadable files."""
    folder, _ = _attached_visible(ctx, name)
    return AuditFiles(files=_files(folder))


@router.get("/audits/{name}/files/{file}", response_class=FileResponse)
def attached_file(name: str, file: str, ctx: Ctx) -> FileResponse:
    """Download one file of an attached folder (its listed files, or a run's result files)."""
    folder, _ = _attached_visible(ctx, name)
    return _download(folder, file)


__all__ = ["Screens", "audit_screen", "require_visible", "router", "screens"]
