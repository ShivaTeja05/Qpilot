"""What the store holds about one study, read once for a report.

:func:`gather` reads the study's result, cards, decision log, confirmed design, the session's
proposal chain, the robustness audit (when one was run), the software versions and the input
file's RDML metadata. It never writes. Each part that is missing or unreadable is left empty and
the report says so; only the result itself is required.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qpilot.core.record import versions as software_versions
from qpilot.core.store import SESSIONS_DIR, StudyNotFound, StudyStore
from qpilot.report.rdml_meta import RdmlMeta, read_meta
from qpilot.schemas import DecisionCard, DecisionEntry, StudyResult
from qpilot.schemas_studio import StudyDesign

AUDITS_DIR = "simulator_audits"
_meta_lock = threading.Lock()
_metas: OrderedDict[tuple[str, int, int], RdmlMeta | None] = OrderedDict()
MAX_METAS = 4


@dataclass
class Audit:
    """The audit's files the report reads (``simulator_audits/<study id>``)."""

    folder: Path
    manifest: dict[str, Any]
    summary: dict[str, Any]
    explain: dict[str, Any]


@dataclass
class StudyInputs:
    """Everything the report reads about one study."""

    study_id: str
    session: str | None
    result: StudyResult
    cards: list[DecisionCard]  # the analysis's choices (cards opened on demand are in traced)
    entries: list[DecisionEntry]
    pending: list[DecisionEntry]
    head: str
    design: StudyDesign | None
    source: Path | None
    headline: list[str] = field(default_factory=list)
    grid_options: dict[str, list[str]] = field(default_factory=dict)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    audit: Audit | None = None
    versions: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    #: Cards opened on demand by Trace (``trace_set_aside``): decisions about a place, not
    #: analysis choices, so Methods and the open-choice checks leave them out.
    traced: list[DecisionCard] = field(default_factory=list)
    _rdml: RdmlMeta | None = None
    _rdml_read: bool = False

    @property
    def rdml(self) -> RdmlMeta | None:
        """The input file's metadata (read once per file; None without the file)."""
        if not self._rdml_read:
            self._rdml_read = True
            self._rdml = rdml_meta(self.source)
            if self.source is not None and self._rdml is None:
                self.problems.append("the input file's metadata could not be read")
        return self._rdml


def rdml_meta(path: Path | None) -> RdmlMeta | None:
    """:func:`read_meta`, cached by the file's path, size and modification time."""
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _meta_lock:
        if key in _metas:
            return _metas[key]
    try:
        meta: RdmlMeta | None = read_meta(path)
    except Exception:  # an unreadable file only leaves the MIQE items it would answer open
        meta = None
    with _meta_lock:
        _metas[key] = meta
        while len(_metas) > MAX_METAS:
            _metas.popitem(last=False)
    return meta


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def audit_of(store: StudyStore, study_id: str) -> Audit | None:
    """The study's robustness audit, when one was run and its manifest reads."""
    folder = store.root / AUDITS_DIR / study_id
    manifest = _json(folder / "audit_manifest.json")
    if not manifest:
        return None
    return Audit(
        folder=folder,
        manifest=manifest,
        summary=_json(folder / "summary.json"),
        explain=_json(folder / "explain.json"),
    )


def proposals_of(store: StudyStore, result: StudyResult) -> list[dict[str, Any]]:
    """The input's Studio proposal chain (``sessions/<input sha>/proposals.jsonl``), in order."""
    path = store.root / SESSIONS_DIR / result.input_sha256 / "proposals.jsonl"
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def gather(store: StudyStore, study_id: str, session: str | None = None) -> StudyInputs:
    """Read one study for its report.

    Raises:
        StudyNotFound: No analysed study with this id.
    """
    from qpilot.core.store import ON_DEMAND_KINDS

    result = store.get(study_id)
    head, every, pending = store.snapshot(study_id)
    cards = [c for c in every if c.kind not in ON_DEMAND_KINDS]
    traced = [c for c in every if c.kind in ON_DEMAND_KINDS]
    problems: list[str] = []
    try:
        design = store.design(study_id)
    except (StudyNotFound, OSError, ValueError):
        design = None
        problems.append("the confirmed design could not be read")
    source = store.source(study_id)
    if source is not None and not source.is_file():
        source = None
    from qpilot.web.results_views import headline_genes, load_grid

    try:
        grid = load_grid(store, result)
    except (OSError, ValueError, KeyError):
        grid = None
        problems.append("the analysis grid could not be read")
    return StudyInputs(
        study_id=study_id,
        session=session,
        result=result,
        cards=list(cards),
        entries=list(store.entries(study_id)),
        pending=list(pending),
        head=head,
        design=design,
        source=source,
        headline=headline_genes(result, cards, store),
        grid_options=dict(grid.options) if grid is not None else {},
        proposals=proposals_of(store, result),
        audit=audit_of(store, study_id),
        versions=software_versions(),
        problems=problems,
        traced=traced,
    )


def fingerprint(store: StudyStore, study_id: str) -> tuple:
    """What a cached report depends on: the study's files, its audit's and the session's chain."""
    workspace = store.workspace(study_id)
    paths = [
        workspace / name
        for name in (
            "results.json",
            "cards.json",
            "facts.json",
            "decisions.jsonl",
            "pending.jsonl",
            "study_design.json",
            "grid.csv",
            "source.json",
        )
    ]
    folder = store.root / AUDITS_DIR / study_id
    paths += [folder / "audit_manifest.json", folder / "summary.json", folder / "explain.json"]
    try:
        sha = store.get(study_id).input_sha256
        paths.append(store.root / SESSIONS_DIR / sha / "proposals.jsonl")
    except (StudyNotFound, OSError, ValueError):
        pass
    out = []
    for path in paths:
        try:
            stat = path.stat()
            out.append((path.name, stat.st_size, stat.st_mtime_ns))
        except OSError:
            out.append((path.name, None, None))
    return (study_id, *out)
