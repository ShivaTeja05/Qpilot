"""qPilot Studio's dashboard: three panes and a stage strip over the Studio service (wiring only).

Every operation goes through :class:`qpilot.studio_service.Studio` (the stage rules, who may act,
the blind stages); every view is a pure function in :mod:`qpilot.studio_state`. This module only
connects the page to them.

* **Intake** (left): an RDML file (or the cached demo), an optional sample sheet, one optional
  sentence, Open; then the stage strip Design (blind) → Curves (blind) → Choices → Prism draft →
  Round trip.
* **What the AI thinks** (middle): the inbox of a stage, one card per proposal with the six fixed
  parts (Proposal, Why, Engine check, Consequence, Level, Actions) and a footer naming who made
  it; the bulk actions show their exact list before a second click acts on it.
* **Prism preview** (right): hidden until a person has confirmed both blind stages; then the
  study summary, the route comparison, the Decision Cards, the Prism project and its preview,
  Send to Prism, and the round trip.

Safety, all of it checked by ``tests/studio``:

* only a person's click decides: every accept, edit, reject, decision, Prism bundle and Prism
  launch is a click handler that passes ``actor="human"``; page load, picking a stage, a card or a
  gene only reads; the service and the proposal store refuse any other actor in code;
* blind stages: before both blind stages are confirmed nothing of the analysis is read, so no
  conclusion, fold change, p-value, card or Prism preview can reach the page; "What the model
  saw" then shows only the Design Interpreter's payload; every view is recomputed from the
  service on each event and the page keeps no result between events (after an accepted
  exclusion re-runs the analysis, only the new analysis is shown), nor an engine answer to
  "Does this matter?" once the proposal chain has moved on;
* the same hardened launch as :mod:`qpilot.app` (its ``LAUNCH_OPTIONS`` and ``launch_options``):
  telemetry off before ``import gradio``, bound to 127.0.0.1, foreign ``Host`` headers refused,
  no monitoring, run history, MCP server, API footer or server-side rendering; files are served
  only from a private export folder made for this launch; the page's actions are hidden from the
  API page and from the Gradio client libraries (``api_visibility="private"``);
* every string from a file, a sheet, a model or an agent is escaped (``esc``).
"""

from __future__ import annotations

import os

os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"  # read when Blocks() is built
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"  # frozen when huggingface_hub is imported

import inspect  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from collections.abc import Callable  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from typing import Any  # noqa: E402

import gradio as gr  # noqa: E402

from qpilot import __version__  # noqa: E402
from qpilot.ai import payload_log  # noqa: E402
from qpilot.app import CSS as APP_CSS  # noqa: E402
from qpilot.app import LAUNCH_OPTIONS, STALE_NOTICE, demo_path  # noqa: E402
from qpilot.app import launch_options as app_launch_options  # noqa: E402
from qpilot.app_state import (  # noqa: E402
    card_view,
    cards_in_order,
    esc,
    footer_lines,
    meter_html,
    next_card,
    study_summary,
)
from qpilot.core.decisions import MAX_REASON  # noqa: E402
from qpilot.core.store import sha256_file  # noqa: E402
from qpilot.core.validator import names_from_result  # noqa: E402
from qpilot.io.datasets import VERMEULEN_COMMIT, default_cache_dir  # noqa: E402
from qpilot.io.rdml_io import RdmlLoadError  # noqa: E402
from qpilot.qpcr.curve_judge import CurveJudgeError  # noqa: E402
from qpilot.qpcr.curves import CurveAnalysisError  # noqa: E402
from qpilot.studio_service import BLIND_STAGES, Studio  # noqa: E402
from qpilot.studio_state import (  # noqa: E402
    STAGE_LABELS,
    card_html,
    confirm_html,
    current_stage,
    curve_figure,
    curve_points,
    decided_html,
    describe,
    file_html,
    group_points,
    headline,
    inbox_head_html,
    is_blind_kind,
    matters_of,
    model_line_html,
    notice_html,
    ordered_pending,
    preview_tables,
    prism_figure,
    prism_preview_html,
    proposal_list_html,
    routes_html,
    seen_html,
    stage_strip_html,
    table_html,
)

PAGE_SIZE = 6
MAX_SENTENCE = 500
MAX_WELLS = 400
MAX_POINTS = 100_000
BUNDLE_FILE = "qpilot_bundle.json"
SENT_BACK_DIR = "sent_back"
INPUT_SUFFIXES = {"rdml": (".rdml", ".xml"), "sheet": (".xlsx", ".csv")}
CONFIRMABLE = ("design", "curves", "choices")
DECIDED = ("accepted", "edited", "rejected")
AI_MAKERS = ("model", "agent")
#: Failures shown on the page as a sentence (anything else is a bug and is raised).
ERRORS: tuple[type[BaseException], ...] = (
    ValueError,
    KeyError,
    OSError,
    RuntimeError,
    RdmlLoadError,
    CurveJudgeError,
    CurveAnalysisError,
)
OPEN_FIRST = "Open a file first (or press Open with no file for the cached demo)."
STALE_PROPOSAL = (
    "The inbox changed since this page showed it (another tab or an agent). Here is the current "
    "inbox: please look again, then decide."
)
MOVED_ANALYSIS = (
    "The analysis changed since this page showed the card (an accepted exclusion re-ran it). "
    "Here is the current card: please look again, then decide."
)
BLIND_PANE = (
    '<div class="qs-blind"><p><b>Results stay hidden</b> until you confirm the Design and the '
    "Curves stages. The design and the curve calls are facts about the experiment and are "
    "decided on the evidence, never on the answer they give.</p></div>"
)
HEADER = (
    "<h2>qPilot Studio</h2><p class='qs-hint'>The AI proposes. The engine checks. You decide: "
    "nothing below changes the analysis, the record or a Prism file until you press a button."
    "</p>"
)
ROUNDTRIP_HELP = (
    "<h4>Round trip</h4><p class='qs-hint'>After you edit in Prism, run <code>send_back.pzc</code> "
    "from the bundle: it writes every table into the bundle's <code>sent_back</code> folder. "
    "Then choose the bundle and that folder here.</p>"
)

STUDIO_CSS = """
.qs-hint { font-size: .85rem; opacity: .8; margin: .2rem 0; }
.qs-strip { list-style: none; padding: 0; margin: .4rem 0; }
.qs-strip li { padding: .3rem .5rem; margin: .2rem 0; border-left: 3px solid rgba(127,127,127,.3); }
.qs-strip li.current { border-left-color: #2a78d6; background: rgba(42,120,214,.08); }
.qs-strip li.confirmed .qs-mark { color: #16a34a; }
.qs-strip .qs-state { display: block; font-size: .8rem; opacity: .8; }
.qs-strip .qs-blockers { font-size: .8rem; margin: .2rem 0 0 1rem; padding-left: .8rem; }
.qs-card { border: 1px solid rgba(127,127,127,.35); border-radius: .5rem; padding: .5rem .8rem;
  border-left-width: 5px; }
.qs-card.check-contradicted { border-left-color: #dc2626; }
.qs-card.check-consistent { border-left-color: #16a34a; }
.qs-card.check-cannot_check { border-left-color: #9ca3af; }
.qs-part { margin: .35rem 0; }
.qs-part p { margin: .15rem 0; }
.qs-label { display: block; font-size: .7rem; text-transform: uppercase; letter-spacing: .05em;
  opacity: .7; }
.qs-what { font-weight: 600; }
.qs-meta, .qs-origin, .qs-note { font-size: .78rem; opacity: .75; }
.qs-quote { margin: .2rem 0; padding: .2rem .5rem; border-left: 3px solid rgba(127,127,127,.45);
  font-family: ui-monospace, monospace; white-space: pre-wrap; word-break: break-word; }
.qs-flag { font-size: .8rem; font-weight: 600; }
.qs-check { display: inline-block; padding: 0 .45rem; border-radius: .5rem; font-weight: 600; }
.qs-check.consistent { background: #bbf7d0; color: #14532d; }
.qs-check.contradicted { background: #fecaca; color: #7f1d1d; }
.qs-check.cannot_check { background: rgba(127,127,127,.2); }
.qs-kv { border-collapse: collapse; font-size: .8rem; margin: .2rem 0; }
.qs-kv th, .qs-kv td { text-align: left; vertical-align: top; padding: .1rem .4rem;
  border-bottom: 1px solid rgba(127,127,127,.2); }
.qs-pre { max-height: 16rem; overflow: auto; font-size: .72rem; white-space: pre-wrap;
  word-break: break-word; }
.qs-matters { font-weight: 600; }
.qs-stale { border-left: 3px solid #c0392b; padding-left: .5rem; }
.qs-footer { font-size: .78rem; opacity: .85; margin-top: .4rem; padding-top: .3rem;
  border-top: 1px dashed rgba(127,127,127,.35); }
.qs-list { font-size: .85rem; max-height: 22rem; overflow: auto; }
.qs-id { font-family: ui-monospace, monospace; font-size: .72rem; opacity: .7; }
.qs-blind { padding: .6rem .8rem; border-radius: .4rem; background: rgba(127,127,127,.12); }
.qs-scroll { max-height: 18rem; overflow: auto; }
.qs-model { font-size: .85rem; margin: 0; }
"""


# ---------- per-tab state ----------


def new_session() -> dict[str, Any]:
    """What the tab is looking at: ids and the lists it last showed (plain values; no results)."""
    return {
        "sid": None,
        "name": "",
        "sheet": False,
        "stage": None,  # the stage the person picked; None follows the current stage
        "shown": None,  # the stage the inbox last showed
        "page": 0,
        "slots": [],  # proposal ids in the card slots, as last shown
        "head": None,  # proposal chain head when the page last showed the inbox
        "bulk": None,  # {"stage", "ids"} shown by "Accept all consistent…"
        "reject": None,  # {"stage", "ids"} shown by "Reject all contradicted AI calls…"
        "confirm": None,  # {"stage", "id"} of the pending stage.confirm shown
        "matters": {},  # proposal id -> the engine's yes/no, when a person asked
        "matters_head": None,  # the proposal chain head those answers hold for
        "seen": False,  # the "What the model saw" panel was opened
        "card_id": None,
        "card_head": None,  # decision chain head when the card was shown
        "card_study": None,  # the analysis the card belonged to
        "gene": None,
        "bundle": None,
        "send": None,  # {"study", "html", "zip"} of the last Send to Prism on this page
    }


def _fresh(session: dict[str, Any] | None) -> dict[str, Any]:
    return {**new_session(), **(session or {})}


def _error(err: BaseException) -> str:
    text = str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err)
    return (text[:1].upper() + text[1:]) if text else type(err).__name__


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


# ---------- the page ----------


def build_app(
    studio: Studio,
    default_rdml: Path | None = None,
    export_root: Path | None = None,
    inputs_root: Path | None = None,
) -> gr.Blocks:
    """Build the Studio page over ``studio``.

    Args:
        studio: The Studio service (its store is shared with ``qpilot serve`` and the MCP tools).
        default_rdml: Opened when Open is pressed with no file uploaded (the cached demo).
        export_root: The only folder files are served from (Prism bundles and their zips); a
            private temporary folder by default.
        inputs_root: Where uploaded files are kept so a session can find its input again (not
            served); ``<cache>/studio-inputs`` by default.
    """
    exports = Path(export_root) if export_root else Path(tempfile.mkdtemp(prefix="qpilot-exports-"))
    exports.mkdir(parents=True, exist_ok=True)
    inputs = Path(inputs_root) if inputs_root else default_cache_dir() / "studio-inputs"
    ui = SimpleNamespace()

    # ---------- reading the service ----------

    def find(sid: str, pid: str | None):
        for proposal in studio.inbox(sid):
            if proposal.id == pid:
                return proposal
        return None

    def well_curve(sid: str, key: str) -> dict[str, list[float]]:
        """``Studio.curve``; while it trips over the non-numeric columns, the same row's cycles."""
        try:
            return studio.curve(sid, key)
        except ValueError:  # Studio.curve converts sample/target too (reported); read Cyc only
            from qpilot.qpcr import curve_judge

            design = studio.assemble(sid).design
            experiment = design.experiment_id if design is not None else None
            features = curve_judge.features_from_rdml(studio.source(sid), experiment)
            run_id, _, well = key.rpartition("/")
            row = features.loc[(run_id, well)]
            cycles = [c for c in features.columns if str(c).startswith("Cyc")]
            values = [float(row[c]) for c in cycles]
            return {"cycle": list(range(1, len(values) + 1)), "fluorescence": values}

    def full_preview(sid: str, preview: dict[str, Any]) -> dict[str, Any]:
        """The previewed tables with every row, for the graph (still writes nothing)."""
        if "rows" in inspect.signature(studio.preview_prism).parameters:
            return studio.preview_prism(sid, rows=MAX_POINTS)
        from qpilot.prism import preview as prism_preview

        genes = list(preview.get("tables") or {})
        template = (preview.get("bundle") or {}).get("template_id") or "two_groups_log2"
        return prism_preview(studio.store, studio.study(sid), genes, template, rows=MAX_POINTS)

    def bundles() -> list[str]:
        """Bundle folders Send to Prism wrote from this page (inside the export folder)."""
        return sorted(str(p.parent) for p in exports.glob(f"prism-*/{BUNDLE_FILE}"))

    def keep_input(upload: str, kind: str) -> Path:
        """Copy an upload where the session can find it again (named by its sha256)."""
        source = Path(upload)
        suffix = source.suffix.lower()
        if suffix not in INPUT_SUFFIXES[kind]:
            raise ValueError(f"{source.name}: expected {' or '.join(INPUT_SUFFIXES[kind])}")
        inputs.mkdir(parents=True, exist_ok=True)
        kept = inputs / f"{sha256_file(source)[:24]}{suffix}"
        if not kept.exists():
            shutil.copyfile(source, kept)
        return kept

    # ---------- the view: everything recomputed from the service on every event ----------

    def render(session: dict[str, Any] | None, note: str = "") -> dict[Any, Any]:
        session = _fresh(session)
        out: dict[Any, Any] = {ui.notice: notice_html(note), ui.model_line: model_line()}
        sid = session["sid"]
        if not sid:
            out.update(empty_inbox())
            out.update(hidden_results())
            out[ui.seen] = seen_panel(session, False)
            out[ui.session] = {**session, "slots": [], "send": None}
            return out
        stages = studio.stages(sid)
        by = {s.stage: s for s in stages}
        visible = bool(studio.results_visible(sid))
        out[ui.seen] = seen_panel(session, visible)  # re-gated: a stage may be blind again
        stage = session["stage"]
        if stage not in by or not by[stage].open:
            stage = current_stage(stages)
            session = {**session, "stage": None}  # a stage that closed again is not kept
        proposals = studio.inbox(sid, stage)
        head = studio.head(sid)
        pending_all = [p for p in proposals if p.status == "proposed"]
        pending = ordered_pending([p for p in pending_all if p.kind != "stage.confirm"])
        confirms = [p for p in pending_all if p.kind == "stage.confirm"]
        decided = [p for p in proposals if p.status in DECIDED]
        n_pages = max(1, math.ceil(len(pending) / PAGE_SIZE))
        page = min(max(0, int(session["page"])), n_pages - 1)
        shown = pending[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        by_id = {p.id: p for p in proposals}

        out[ui.file_info] = file_info(session, sid)
        out[ui.strip] = stage_strip_html(stages, stage)
        out[ui.stage_pick] = gr.update(
            choices=[(STAGE_LABELS[s.stage], s.stage) for s in stages if s.open], value=stage
        )
        head_html = inbox_head_html(stage, len(pending), len(decided), page, n_pages)
        if stage == "choices":
            head_html += (
                "<p>The Choices stage has no AI proposals: its Decision Cards are in the "
                "right-hand pane.</p>"
            )
        out[ui.inbox_head] = head_html
        out.update(stage_buttons(stage, by, proposals, pending, confirms))

        # the bulk lists: shown exactly as they will be acted on, dropped when the stage changes
        bulk = session["bulk"] if (session["bulk"] or {}).get("stage") == stage else None
        rejecting = session["reject"] if (session["reject"] or {}).get("stage") == stage else None
        out[ui.bulk_box] = gr.update(visible=bool(bulk))
        out[ui.bulk_html] = (
            proposal_list_html(
                [by_id[i] for i in bulk["ids"] if i in by_id],
                f"“Accept all consistent” will accept exactly these {len(bulk['ids'])} "
                "proposals, one record entry each. Contradicted and cannot-check proposals are "
                "never on this list.",
            )
            if bulk
            else ""
        )
        out[ui.bulk_accept] = gr.update(
            value=f"Accept these {len(bulk['ids'])}" if bulk else "Accept"
        )
        out[ui.reject_box] = gr.update(visible=bool(rejecting))
        out[ui.reject_html] = (
            proposal_list_html(
                [by_id[i] for i in rejecting["ids"] if i in by_id],
                f"“Reject all listed” will reject exactly these {len(rejecting['ids'])} "
                "proposals made by a model or an agent that the engine's check contradicts, "
                "each with the reason you give.",
            )
            if rejecting
            else ""
        )
        out[ui.reject_all] = gr.update(
            value=f"Reject these {len(rejecting['ids'])}" if rejecting else "Reject"
        )
        if not rejecting:
            out[ui.reject_reason] = gr.update(value="")

        # the confirm click: what it covers is shown first
        confirm = confirms[-1] if confirms else None
        out[ui.confirm_box] = gr.update(visible=confirm is not None)
        if confirm is not None:
            covered = [by_id[i] for i in confirm.payload.get("covers") or [] if i in by_id]
            info = confirm_html(confirm, covered)
            if confirm.subject == "choices" and visible:
                _, cards, _ = studio.store.snapshot(studio.study(sid))
                still = [c for c in cards if c.status in ("open", "pending_human")]
                if still:
                    info += notice_html(
                        f"{len(still)} Decision Card(s) are still open: they would be exported "
                        "at their recommended option, and deciding them later re-opens this stage."
                    )
            out[ui.confirm_info] = info
            label = STAGE_LABELS.get(confirm.subject, confirm.subject)
            out[ui.confirm_btn] = gr.update(value=f"Yes, confirm the {label} stage")
        else:
            out[ui.confirm_info] = ""
            out[ui.confirm_reason] = gr.update(value="")

        # the cards
        quarantine = {e.text_id: e for e in studio.quarantined(sid)}
        try:
            cells = {c.cell: c.text_id for c in studio.summary(sid).sheet}
        except ERRORS:
            cells = {}
        last = payload_log.last_payload()  # while blind, footers show only the interpreter's
        # an engine answer holds for the chain it was computed on: any accept, edit, reject or
        # new proposal since then drops it, and "Does this matter?" can be asked again
        asked = session["matters"] if session["matters_head"] == head else {}
        old = list(session["slots"])
        for i, slot in enumerate(ui.slots):
            if i < len(shown):
                p = shown[i]
                changed = i >= len(old) or old[i] != p.id
                matters = matters_of(p, asked.get(p.id))
                stale = studio.stale_consequence(sid, p) if visible else None
                out[slot.box] = gr.update(visible=True)
                out[slot.html] = card_html(
                    p,
                    quarantine=quarantine,
                    sheet_cells=cells,
                    results_visible=visible,
                    matters=matters,
                    last_payload=last,
                    stale=stale,
                )
                out[slot.accept] = gr.update(
                    value="Accept: exclude this value"
                    if p.kind == "prism.exclusion_reason"
                    else "Accept"
                )
                can_ask = (
                    is_blind_kind(p)
                    and p.kind.startswith("design.")
                    and bool(p.alternatives)
                    and matters is None
                )
                out[slot.matters] = gr.update(visible=can_ask)
                if changed:  # a reason or an edit typed for another card never carries over
                    out[slot.reason] = gr.update(value="")
                    out[slot.code] = gr.update(
                        value=json.dumps(p.payload, indent=2, ensure_ascii=False)
                    )
                    out[slot.acc] = gr.update(open=False)
            else:
                out[slot.box] = gr.update(visible=False)
                out[slot.html] = ""
                out[slot.reason] = gr.update(value="")
                out[slot.code] = gr.update(value="")
        out[ui.prev_btn] = gr.update(interactive=page > 0)
        out[ui.next_btn] = gr.update(interactive=page < n_pages - 1)
        out[ui.page_info] = f"<p class='qs-hint'>Page {page + 1} of {n_pages}</p>"
        out[ui.decided] = decided_html(decided)
        wells = list(
            dict.fromkeys(e.ref for p in pending for e in p.evidence if e.kind in ("well", "curve"))
        )[:MAX_WELLS]
        out[ui.well_pick] = gr.update(choices=wells, value=None)

        session = {
            **session,
            "shown": stage,
            "page": page,
            "slots": [p.id for p in shown],
            "head": head,
            "matters": asked,
            "matters_head": head if asked else None,
            "bulk": bulk,
            "reject": rejecting,
            "confirm": {"stage": stage, "id": confirm.id} if confirm else None,
        }
        if visible:
            session = results(session, sid, by, out)
        else:  # blind: nothing of the analysis is read, and nothing of it stays on the page
            out.update(hidden_results())
            session = {
                **session,
                "card_id": None,
                "card_head": None,
                "card_study": None,
                "gene": None,
                "send": None,
            }
        out[ui.session] = session
        return out

    def model_line() -> str:
        try:
            return model_line_html(studio.model_status())
        except ERRORS as err:
            return notice_html(f"Model status unknown: {_error(err)}")

    def seen_panel(session: dict[str, Any], visible: bool) -> dict[str, Any]:
        """The "What the model saw" panel, recomputed on every event once opened (blind-gated)."""
        if not session["seen"]:
            return gr.update(value="", visible=False)
        html = seen_html(payload_log.last_payload(), results_visible=visible)
        return gr.update(value=html, visible=True)

    def file_info(session: dict[str, Any], sid: str) -> str:
        try:
            return file_html(session["name"] or sid, studio.summary(sid), bool(session["sheet"]))
        except ERRORS as err:
            return notice_html(_error(err))

    def stage_buttons(stage, by, proposals, pending, confirms) -> dict[Any, Any]:
        status = by[stage]
        accepted = [p for p in proposals if p.status in ("accepted", "edited")]
        groups = {
            str(p.effective_payload().get("group")) for p in accepted if p.kind == "design.group"
        }
        compared = any(p.kind in ("design.comparison", "design.preset") for p in accepted)
        ai_contradicted = [
            p for p in pending if p.check.status == "contradicted" and p.made_by.kind in AI_MAKERS
        ]
        return {
            ui.design_btn: gr.update(
                visible=stage == "design", interactive=status.open and not status.confirmed
            ),
            ui.comparison_btn: gr.update(
                visible=stage == "design", interactive=len(groups) == 2 and not compared
            ),
            ui.curves_btn: gr.update(
                visible=stage == "curves", interactive=status.open and not status.confirmed
            ),
            ui.bulk_show: gr.update(visible=bool(pending)),
            ui.reject_show: gr.update(visible=bool(ai_contradicted)),
            ui.confirm_prepare: gr.update(
                visible=stage in CONFIRMABLE
                and status.open
                and not status.confirmed
                and not confirms,
                interactive=not pending,
                value="Confirm this stage…"
                if not pending
                else "Confirm this stage… (decide every proposal first)",
            ),
        }

    def empty_inbox() -> dict[Any, Any]:
        out: dict[Any, Any] = {
            ui.file_info: "<p class='qs-hint'>Nothing open yet.</p>",
            ui.strip: "",
            ui.stage_pick: gr.update(choices=[], value=None),
            ui.inbox_head: (
                "<h3>What the AI thinks</h3><p class='qs-hint'>Open a file to begin.</p>"
            ),
            ui.design_btn: gr.update(visible=False),
            ui.comparison_btn: gr.update(visible=False),
            ui.curves_btn: gr.update(visible=False),
            ui.bulk_show: gr.update(visible=False),
            ui.reject_show: gr.update(visible=False),
            ui.confirm_prepare: gr.update(visible=False),
            ui.bulk_box: gr.update(visible=False),
            ui.bulk_html: "",
            ui.bulk_accept: gr.update(value="Accept"),
            ui.reject_box: gr.update(visible=False),
            ui.reject_html: "",
            ui.reject_all: gr.update(value="Reject"),
            ui.reject_reason: gr.update(value=""),
            ui.confirm_box: gr.update(visible=False),
            ui.confirm_info: "",
            ui.confirm_btn: gr.update(),
            ui.confirm_reason: gr.update(value=""),
            ui.prev_btn: gr.update(interactive=False),
            ui.next_btn: gr.update(interactive=False),
            ui.page_info: "",
            ui.decided: "",
            ui.well_pick: gr.update(choices=[], value=None),
        }
        for slot in ui.slots:
            out[slot.box] = gr.update(visible=False)
            out[slot.html] = ""
            out[slot.reason] = gr.update(value="")
            out[slot.code] = gr.update(value="")
            out[slot.matters] = gr.update(visible=False)
            out[slot.accept] = gr.update()
        return out

    def hidden_results() -> dict[Any, Any]:
        return {
            ui.blind_note: gr.update(visible=True),
            ui.right: gr.update(visible=False),
            ui.summary: "",
            ui.routes: "",
            ui.card_pick: gr.update(choices=[], value=None),
            ui.card: "",
            ui.card_options: gr.update(choices=[], value=None),
            ui.card_reason: gr.update(value=""),
            ui.prism_status: "",
            ui.prism_btn: gr.update(interactive=False),
            ui.preview: "",
            ui.gene_pick: gr.update(choices=[], value=None),
            ui.prism_plot: gr.update(value=None, visible=False),
            ui.prism_table: "",
            ui.send_btn: gr.update(interactive=False),
            ui.send_info: "",
            ui.download: gr.update(value=None, visible=False),
            ui.bundle_pick: gr.update(choices=[], value=None),
            ui.sent_back: gr.update(value=""),
        }

    def results(session: dict[str, Any], sid: str, by, out: dict[Any, Any]) -> dict[str, Any]:
        """The right-hand pane, read fresh from the service (only once results are visible)."""
        study_id = studio.study(sid)
        result = studio.store.get(study_id)
        chain_head, cards, pending = studio.store.snapshot(study_id)
        cards = cards_in_order(cards)
        out[ui.blind_note] = gr.update(visible=False)
        out[ui.right] = gr.update(visible=True)
        out[ui.summary] = (
            study_summary(result).html
            + meter_html(result, headline(result))
            + f"<p class='qs-hint'>Analysis <code>{esc(study_id)}</code>.</p>"
        )
        out[ui.routes] = routes_html(result.facts)

        # the Decision Cards (the Choices stage)
        if session["card_study"] != study_id:
            session = {**session, "card_id": None}
        by_card = {c.id: c for c in cards}
        card = by_card.get(session["card_id"]) or next_card(cards) or (cards[0] if cards else None)
        if card is None:
            out[ui.card] = "<p>This analysis has no Decision Cards.</p>"
            out[ui.card_pick] = gr.update(choices=[], value=None)
            out[ui.card_options] = gr.update(choices=[], value=None)
        else:
            asked = [e.option for e in pending if e.card_id == card.id]
            view = card_view(
                card,
                result.facts,
                allowed_names=names_from_result(result),
                pending_option=asked[-1] if asked else None,
            )
            out[ui.card] = view.html
            out[ui.card_pick] = gr.update(
                choices=[
                    (f"{c.rank}. {c.kind.replace('_', ' ')} ({c.status.replace('_', ' ')})", c.id)
                    for c in cards
                ],
                value=card.id,
            )
            out[ui.card_options] = gr.update(
                choices=[(o.label, o.id) for o in card.options], value=None
            )
            if card.id != session["card_id"] or session["card_study"] != study_id:
                out[ui.card_reason] = gr.update(value="")
        out[ui.decide_btn] = gr.update(interactive=card is not None)
        session = {
            **session,
            "card_id": card.id if card else None,
            "card_head": chain_head,
            "card_study": study_id,
        }

        # the Prism project and its preview
        projects = studio.inbox(sid, "prism")
        accepted = [
            p
            for p in projects
            if p.status in ("accepted", "edited")
            and p.effective_payload().get("study_id") == study_id
        ]
        waiting = [p for p in projects if p.status == "proposed"]
        if accepted:
            project = accepted[-1]
            words = describe(project, project.effective_payload())
            status = f"Prism project for this analysis: accepted — {words}."
        elif waiting:
            status = "A Prism project is waiting for you in the Prism draft inbox."
        elif by["choices"].confirmed:
            status = "No Prism project yet: press “Draft the Prism project”."
        else:
            status = "The Prism project is drafted once the Choices stage is confirmed."
        out[ui.prism_status] = f"<p>{esc(status)}</p>"
        out[ui.prism_btn] = gr.update(interactive=bool(by["choices"].confirmed))
        out[ui.send_btn] = gr.update(interactive=bool(accepted) and bool(by["choices"].confirmed))
        try:
            preview = studio.preview_prism(sid)
        except ERRORS as err:
            out[ui.preview] = notice_html(f"No Prism preview: {_error(err)}")
            out[ui.gene_pick] = gr.update(choices=[], value=None)
            out[ui.prism_plot] = gr.update(value=None, visible=False)
            out[ui.prism_table] = ""
            genes: list[str] = []
        else:
            out[ui.preview] = prism_preview_html(preview)
            genes = list(preview.get("tables") or {})
            gene = session["gene"] if session["gene"] in genes else (genes[0] if genes else None)
            session = {**session, "gene": gene}
            out[ui.gene_pick] = gr.update(choices=genes, value=gene)
            out.update(prism_graph(sid, preview, gene))

        # Send to Prism: what this page last sent, for this analysis only
        sent = session["send"] if (session["send"] or {}).get("study") == study_id else None
        session = {**session, "send": sent}
        out[ui.send_info] = sent["html"] if sent else ""
        out[ui.download] = (
            gr.update(value=sent["zip"], visible=True)
            if sent and sent.get("zip")
            else gr.update(value=None, visible=False)
        )
        choices = bundles()
        bundle = (
            session["bundle"]
            if session["bundle"] in choices
            else (choices[-1] if choices else None)
        )
        if bundle != session["bundle"] or bundle is None:
            out[ui.sent_back] = gr.update(value=str(Path(bundle) / SENT_BACK_DIR) if bundle else "")
        out[ui.bundle_pick] = gr.update(choices=choices, value=bundle)
        return {**session, "bundle": bundle}

    def prism_graph(sid: str, preview: dict[str, Any], gene: str | None) -> dict[Any, Any]:
        """Every unit per group with mean ± 95 % CI; the table when no graph can be drawn."""
        if gene is None:
            return {ui.prism_plot: gr.update(value=None, visible=False), ui.prism_table: ""}
        layout = (preview.get("template") or {}).get("layout")
        head = preview_tables(preview).get(gene, {})
        if layout == "column":
            try:
                table = preview_tables(full_preview(sid, preview)).get(gene, {})
            except ERRORS:
                table = {}
            groups = group_points(table.get("columns", []), table.get("rows", []))
            if any(groups.values()):
                return {
                    ui.prism_plot: gr.update(value=prism_figure(gene, groups), visible=True),
                    ui.prism_table: "<p class='qs-hint'>An approximation of the template's graph: "
                    "every biological unit, the group mean and its 95 % confidence interval. "
                    "Prism draws the real one.</p>",
                }
        return {
            ui.prism_plot: gr.update(value=None, visible=False),
            ui.prism_table: table_html(gene, head) if head else "",
        }

    # ---------- handlers: reading ----------

    def on_load(session):
        return render(session)

    def on_stage(session, stage):
        session = _fresh(session)
        return render({**session, "stage": stage or None, "page": 0})

    def on_prev(session):
        session = _fresh(session)
        return render({**session, "page": max(0, int(session["page"]) - 1)})

    def on_next(session):
        session = _fresh(session)
        return render({**session, "page": int(session["page"]) + 1})

    def on_card_pick(session, card_id):
        session = _fresh(session)
        return render({**session, "card_id": card_id})

    def on_gene(session, gene):
        session = _fresh(session)
        sid = session["sid"]
        if not sid or not studio.results_visible(sid):
            return {
                ui.session: session,
                ui.prism_plot: gr.update(value=None, visible=False),
                ui.prism_table: "",
            }
        try:
            preview = studio.preview_prism(sid)
        except ERRORS as err:
            return {
                ui.session: session,
                ui.prism_plot: gr.update(value=None, visible=False),
                ui.prism_table: notice_html(_error(err)),
            }
        genes = list(preview.get("tables") or {})
        gene = gene if gene in genes else (genes[0] if genes else None)
        return {ui.session: {**session, "gene": gene}, **prism_graph(sid, preview, gene)}

    def on_curve(session, well):
        session = _fresh(session)
        sid = session["sid"]
        if not sid or not well:
            return {
                ui.curve_plot: gr.update(visible=False),
                ui.notice: notice_html("Choose a well first."),
            }
        try:
            points = curve_points(well_curve(sid, well))
        except ERRORS as err:
            return {ui.curve_plot: gr.update(visible=False), ui.notice: notice_html(_error(err))}
        return {
            ui.curve_plot: gr.update(value=curve_figure(well, points), visible=True),
            ui.notice: "",
        }

    def on_seen(session):
        session = {**_fresh(session), "seen": True}
        sid = session["sid"]
        visible = bool(sid) and bool(studio.results_visible(sid))
        return {ui.session: session, ui.seen: seen_panel(session, visible)}

    # ---------- handlers: proposing (the system proposes; nothing is decided) ----------

    def on_open(session, upload, sheet_file):
        path = Path(upload) if upload else default_rdml
        if path is None or not Path(path).exists():
            return render(
                session, "No file: upload an RDML file, or run `qpilot fetch-demo` for the demo."
            )
        try:
            rdml = keep_input(str(path), "rdml") if upload else Path(path)
            sheet = keep_input(sheet_file, "sheet") if sheet_file else None
            sid = studio.open(rdml, sheet)
        except ERRORS as err:
            return render(session, f"Could not open {Path(path).name}: {_error(err)}")
        fresh = {**new_session(), "sid": sid, "name": Path(path).name, "sheet": sheet is not None}
        earlier = len(studio.inbox(sid))
        note = (
            f"Opened {Path(path).name}: its Studio session continues where it was left "
            f"({earlier} proposal(s) so far; every decision already made is kept)."
            if earlier
            else f"Opened {Path(path).name}. Nothing is analysed and nothing is proposed yet."
        )
        out = render(fresh, note)
        out[ui.curve_plot] = gr.update(value=None, visible=False)
        return out

    def report_note(report: dict[str, Any], what: str) -> str:
        proposed = len(report.get("proposed", []))
        parts = [f"{proposed} {what} proposal(s) added to the inbox."]
        refused = report.get("refused") or []
        if refused:
            parts.append(
                f"{len(refused)} refused: " + "; ".join(str(r.get("reason")) for r in refused[:3])
            )
        if report.get("fallback") is True:
            parts.append("The model was not used; the rules proposed alone.")
        for note in map(str, report.get("notes", [])):
            note = note[:1].upper() + note[1:]
            parts.append(note if note.endswith((".", "!", "?")) else note + ".")
        return " ".join(parts)

    def on_propose_design(session, sentence):
        session = _fresh(session)
        if not session["sid"]:
            return render(session, OPEN_FIRST)
        try:
            report = studio.propose_design(session["sid"], (sentence or "")[:MAX_SENTENCE])
        except ERRORS as err:
            return render(session, f"No design proposed: {_error(err)}")
        return render({**session, "stage": None, "page": 0}, report_note(report, "design"))

    def on_propose_comparison(session):
        session = _fresh(session)
        if not session["sid"]:
            return render(session, OPEN_FIRST)
        try:
            outcome = studio.propose_comparison(session["sid"])
        except ERRORS as err:
            return render(session, _error(err))
        if outcome is None:
            note = (
                "A comparison is proposed once exactly two groups are accepted and no "
                "comparison is."
            )
        elif outcome.status == "proposed":
            note = "The comparison is proposed: check which group is the reference, then decide."
        else:
            note = f"No comparison proposed: {outcome.reason or outcome.status}"
        return render(session, note)

    def on_propose_curves(session):
        session = _fresh(session)
        if not session["sid"]:
            return render(session, OPEN_FIRST)
        try:
            report = studio.propose_curves(session["sid"])
        except ERRORS as err:
            return render(session, f"No curve calls proposed: {_error(err)}")
        note = report_note(report, "curve")
        if "disagreements" in report:
            note += (
                f" The Curve Judge disagrees with LinRegPCR on {report['disagreements']} study "
                f"wells; {report.get('targets_that_matter', 0)} target(s) where that could "
                "change a conclusion are listed well by well."
            )
        return render({**session, "stage": None, "page": 0}, note)

    def on_confirm_prepare(session):
        session = _fresh(session)
        sid, stage = session["sid"], session["shown"]
        if not sid or stage not in CONFIRMABLE:
            return render(session, OPEN_FIRST if not sid else "This stage has no confirm step.")
        try:
            outcome = studio.propose_confirm(sid, stage)
        except ERRORS as err:
            return render(session, f"Not ready to confirm: {_error(err)}")
        if outcome.status != "proposed":
            return render(session, f"Not ready to confirm: {outcome.reason or outcome.status}")
        return render(
            session,
            f"Here is what confirming the {STAGE_LABELS[stage]} stage covers. Nothing is "
            "confirmed until you press “Yes, confirm”.",
        )

    def on_propose_prism(session):
        session = _fresh(session)
        if not session["sid"]:
            return render(session, OPEN_FIRST)
        try:
            outcome = studio.propose_prism(session["sid"])
        except ERRORS as err:
            return render(session, f"No Prism project drafted: {_error(err)}")
        if outcome.status != "proposed":
            return render(session, f"No Prism project drafted: {outcome.reason or outcome.status}")
        return render(
            {**session, "stage": None, "page": 0},
            "The Prism project is drafted: check it in the Prism draft inbox, then accept it.",
        )

    def on_roundtrip(session, bundle, folder):
        session = _fresh(session)
        sid = session["sid"]
        if not sid:
            return render(session, OPEN_FIRST)
        if not bundle or bundle not in bundles():
            return render(session, "Choose a bundle that Send to Prism wrote from this page.")
        try:
            sent_back = allowed_folder(folder)
            report = studio.round_trip(sid, bundle, sent_back)
        except ERRORS as err:
            return render(session, f"Could not read what came back from Prism: {_error(err)}")
        items = report.get("items", [])
        added = len((report.get("inbox") or {}).get("proposed", []))
        note = (
            f"{len(items)} difference(s) since the export; {added} question(s) added to the "
            "Round trip inbox."
        )
        notes = [str(n) for n in report.get("notes", [])]
        combined = report.get("combined_consequence") or {}
        if len(combined.get("exclusions") or []) > 1:
            changed = combined.get("changed_genes") or []
            notes.append(
                f"All {len(combined['exclusions'])} exclusions together change "
                f"{len(changed)} of {combined.get('n_genes', '?')} conclusions"
                + (f" ({', '.join(map(str, changed))})." if changed else ".")
            )
        return render({**session, "stage": None, "page": 0}, " ".join([note, *notes]))

    def allowed_folder(text: str) -> Path:
        """A folder inside the export folder or the home folder (never a link, never the store)."""
        raw = Path((text or "").strip()).expanduser()
        if not str(raw).strip() or str(raw) == ".":
            raise ValueError("give the folder Prism sent the tables back to")
        if raw.is_symlink() or not raw.is_dir():
            raise ValueError(f"not a folder: {raw}")
        folder = raw.resolve()
        roots = [exports.resolve(), Path.home().resolve()]
        if not any(_within(folder, root) for root in roots):
            raise ValueError("the folder must be inside the export folder or your home folder")
        if _within(folder, Path(studio.store.root).resolve()):
            raise ValueError("the study store is not a folder Prism sends tables back to")
        return folder

    # ---------- handlers: a person decides (each one a click; actor="human") ----------

    def outcome_note(session, outcome, done: str):
        if outcome.status == "stale":
            return render(session, STALE_PROPOSAL)
        if outcome.status in DECIDED:
            return render(session, done)
        return render(session, f"Not done: {outcome.reason or outcome.status}")

    def slot_target(session, i):
        session = _fresh(session)
        slots = session["slots"]
        pid = slots[i] if i < len(slots) else None
        if not session["sid"] or not pid:
            return session, None
        return session, find(session["sid"], pid)

    def make_accept(i: int) -> Callable:
        def on_accept(session, reason):
            session, proposal = slot_target(session, i)
            if proposal is None:
                return render(session, "Nothing to accept here: the inbox was re-read.")
            text = (reason or "").strip()
            if proposal.kind == "prism.exclusion_reason" and not text:
                return render(
                    session,
                    "Say why this value was excluded in Prism (the reason is kept in the record).",
                )
            try:
                outcome = studio.accept(
                    session["sid"],
                    proposal.id,
                    actor="human",
                    reason=text,
                    expected_head=session["head"],
                )
            except ERRORS as err:
                return render(session, _error(err))
            return outcome_note(session, outcome, f"Accepted: {describe(proposal)}.")

        on_accept.__name__ = f"on_accept_{i}"
        return on_accept

    def make_reject(i: int) -> Callable:
        def on_reject(session, reason):
            session, proposal = slot_target(session, i)
            if proposal is None:
                return render(session, "Nothing to reject here: the inbox was re-read.")
            text = (reason or "").strip()
            if not text:
                return render(session, "Give a reason to reject (it is kept in the record).")
            try:
                outcome = studio.reject(
                    session["sid"],
                    proposal.id,
                    actor="human",
                    reason=text,
                    expected_head=session["head"],
                )
            except ERRORS as err:
                return render(session, _error(err))
            return outcome_note(session, outcome, f"Rejected: {describe(proposal)}.")

        on_reject.__name__ = f"on_reject_{i}"
        return on_reject

    def make_edit(i: int) -> Callable:
        def on_edit(session, code, reason):
            session, proposal = slot_target(session, i)
            if proposal is None:
                return render(session, "Nothing to edit here: the inbox was re-read.")
            try:
                edited = json.loads(code or "")
            except ValueError:
                return render(session, "The edited payload is not valid JSON; nothing was changed.")
            if not isinstance(edited, dict):
                return render(
                    session, "The edited payload must be a JSON object; nothing was changed."
                )
            missing = object()
            edits = {k: v for k, v in edited.items() if proposal.payload.get(k, missing) != v}
            if not edits:
                return render(
                    session, "Nothing was changed; use Accept to accept the proposal as it is."
                )
            text = (reason or "").strip()
            if proposal.kind == "prism.exclusion_reason" and not text:
                return render(session, "Say why (the reason is kept in the record).")
            try:
                outcome = studio.edit(
                    session["sid"],
                    proposal.id,
                    actor="human",
                    edits=edits,
                    reason=text,
                    expected_head=session["head"],
                )
            except ERRORS as err:
                return render(session, _error(err))
            return outcome_note(
                session,
                outcome,
                f"Edited and accepted: {describe(proposal, {**proposal.payload, **edits})}.",
            )

        on_edit.__name__ = f"on_edit_{i}"
        return on_edit

    def make_matters(i: int) -> Callable:
        def on_matters(session):
            session, proposal = slot_target(session, i)
            if proposal is None:
                return render(session)
            head = studio.head(session["sid"])  # read first: the answer is for this chain
            try:
                answer = studio.matters(session["sid"], proposal)
            except ERRORS as err:
                return render(session, _error(err))
            if answer is None:
                return render(
                    session, "The engine cannot tell yet: the rest of the design does not run."
                )
            kept = session["matters"] if session["matters_head"] == head else {}
            asked = {**kept, proposal.id: bool(answer)}
            return render({**session, "matters": asked, "matters_head": head})

        on_matters.__name__ = f"on_matters_{i}"
        return on_matters

    def on_bulk_show(session):
        session = _fresh(session)
        sid, stage = session["sid"], session["shown"]
        if not sid or not stage:
            return render(session, OPEN_FIRST)
        ids = studio.consistent_ids(sid, stage)
        if not ids:
            return render(
                {**session, "bulk": None},
                "No waiting proposal of this stage is consistent with the engine's check.",
            )
        return render(
            {**session, "bulk": {"stage": stage, "ids": list(ids)}},
            "Check the list below; only these are accepted, and only when you press the "
            "button under it.",
        )

    def on_bulk_accept(session):
        session = _fresh(session)
        bulk, sid = session["bulk"], session["sid"]
        if not sid or not bulk or bulk.get("stage") != session["shown"]:
            return render(
                session,
                "Press “Accept all consistent…” first: it shows the list before anything is "
                "accepted.",
            )
        try:
            outcomes = studio.accept_all_consistent(
                sid, bulk["stage"], actor="human", ids=list(bulk["ids"])
            )
        except ERRORS as err:
            return render({**session, "bulk": None}, _error(err))
        done = sum(1 for o in outcomes if o.status == "accepted")
        others = [o for o in outcomes if o.status != "accepted"]
        note = f"Accepted {done} proposal(s), one record entry each."
        if others:
            note += f" {len(others)} not accepted: " + "; ".join(
                sorted({str(o.reason or o.status) for o in others})
            )
        return render({**session, "bulk": None}, note)

    def on_bulk_cancel(session):
        return render({**_fresh(session), "bulk": None})

    def on_reject_show(session):
        session = _fresh(session)
        sid, stage = session["sid"], session["shown"]
        if not sid or not stage:
            return render(session, OPEN_FIRST)
        ids = [
            p.id
            for p in studio.inbox(sid, stage, status="proposed")
            if p.kind != "stage.confirm"
            and p.check.status == "contradicted"
            and p.made_by.kind in AI_MAKERS
        ]
        if not ids:
            return render(
                {**session, "reject": None},
                "No waiting AI proposal of this stage is contradicted by the engine's check.",
            )
        return render(
            {**session, "reject": {"stage": stage, "ids": ids}},
            "Check the list below and give one reason; only these are rejected, and only "
            "when you press the button.",
        )

    def on_reject_all(session, reason):
        session = _fresh(session)
        listed, sid = session["reject"], session["sid"]
        if not sid or not listed or listed.get("stage") != session["shown"]:
            return render(
                session, "Press “Reject all contradicted AI calls…” first: it shows the list."
            )
        text = (reason or "").strip()
        if not text:
            return render(session, "Give the reason for rejecting them (it is kept with each one).")
        try:
            outcomes = studio.reject_many(sid, list(listed["ids"]), actor="human", reason=text)
        except ERRORS as err:
            return render({**session, "reject": None}, _error(err))
        done = sum(1 for o in outcomes if o.status == "rejected")
        return render(
            {**session, "reject": None},
            f"Rejected {done} proposal(s), one record entry each, with your reason.",
        )

    def on_reject_cancel(session):
        return render({**_fresh(session), "reject": None})

    def on_confirm(session):
        session = _fresh(session)
        sid, shown = session["sid"], session["confirm"]
        if not sid or not shown or shown.get("stage") != session["shown"]:
            return render(
                session, "Press “Confirm this stage…” first: it shows what the confirm covers."
            )
        try:
            outcome = studio.accept(sid, shown["id"], actor="human", expected_head=session["head"])
        except ERRORS as err:
            return render(session, _error(err))
        if outcome.status != "accepted":
            return outcome_note(session, outcome, "")
        stage = shown["stage"]
        after = {s.stage: s for s in studio.stages(sid)}
        if not after[stage].confirmed:
            note = (
                f"The confirm was recorded, but the {STAGE_LABELS[stage]} stage changed since it "
                "was proposed, so it is not confirmed: confirm it again."
            )
        else:
            note = f"The {STAGE_LABELS[stage]} stage is confirmed."
            if stage in BLIND_STAGES and studio.results_visible(sid):
                note += (
                    " Both blind stages are confirmed: the results are shown in the right-hand "
                    "pane."
                )
        return render({**session, "stage": None, "page": 0, "confirm": None}, note)

    def on_confirm_withdraw(session, reason):
        session = _fresh(session)
        sid, shown = session["sid"], session["confirm"]
        if not sid or not shown:
            return render(session)
        text = (reason or "").strip()
        if not text:
            return render(
                session, "Give a reason for not confirming yet (it is kept in the record)."
            )
        try:
            outcome = studio.reject(
                sid, shown["id"], actor="human", reason=text, expected_head=session["head"]
            )
        except ERRORS as err:
            return render(session, _error(err))
        return outcome_note(
            {**session, "confirm": None}, outcome, "Not confirmed; the stage stays open."
        )

    def on_decide(session, option, reason):
        session = _fresh(session)
        sid, card_id = session["sid"], session["card_id"]
        if not sid or not card_id:
            return render(session, "No Decision Card is shown.")
        if not option:
            return render(session, "Pick an option first.")
        try:
            if studio.study(sid) != session["card_study"]:
                return render(session, MOVED_ANALYSIS)
            outcome = studio.decide(
                sid,
                card_id,
                option,
                (reason or "").strip(),
                actor="human",
                expected_head=session["card_head"],
            )
        except ERRORS as err:
            return render(session, _error(err))
        if outcome.status == "stale":
            return render(session, STALE_NOTICE)
        if outcome.status == "applied":
            labels = {o.id: o.label for o in outcome.card.options} if outcome.card else {}
            return render({**session, "card_id": None}, f"Decided: {labels.get(option, option)}.")
        return render(session, outcome.reason or outcome.status)

    def on_send(session):
        session = _fresh(session)
        sid = session["sid"]
        if not sid:
            return render(session, OPEN_FIRST)
        if not studio.results_visible(sid):
            return render(session, "Confirm the Design and Curves stages first.")
        folder = Path(tempfile.mkdtemp(prefix="prism-", dir=exports))
        try:
            result = studio.send_to_prism(sid, folder, actor="human")
        except ERRORS as err:
            shutil.rmtree(folder, ignore_errors=True)
            return render(session, f"Not sent: {_error(err)}")
        try:
            launched = studio.launch_prism(result, actor="human")
        except ERRORS as err:
            launched = {"launched": False, "note": f"Prism could not be started: {_error(err)}"}
        archive = None
        if not launched.get("launched"):
            archive = shutil.make_archive(str(folder) + "-bundle", "zip", root_dir=folder)
        bundle = result.bundle
        lines = [
            f"Wrote {len(result.files)} files (bundle sha256 {bundle.bundle_sha256[:16]}…) to "
            f"{result.out_dir}.",
            *[f"Note: {n}" for n in result.notes],
        ]
        if launched.get("launched"):
            done = (
                "Prism finished the script."
                if launched.get("done")
                else "Prism has not finished yet."
            )
            lines.append(f"Prism ran run.pzc. {done}")
        else:
            lines.append(str(launched.get("note") or "Prism was not started."))
            lines.append(f"On the computer with Prism, run: {result.launch.command_line}")
            lines.append("The bundle is also offered as a zip below.")
        html = "".join(f"<p>{esc(line)}</p>" for line in lines)
        sent = {"study": bundle.study_id, "html": html, "zip": archive}
        return render(
            {**session, "send": sent, "bundle": str(folder)},
            "Sent to Prism." if launched.get("launched") else "The Prism bundle is written.",
        )

    # ---------- layout ----------

    with gr.Blocks(title="qPilot Studio", analytics_enabled=False) as page:
        ui.session = gr.State(new_session())
        gr.HTML(HEADER)
        ui.model_line = gr.HTML()
        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=260):
                gr.HTML("<h3>1 · Intake</h3>")
                ui.upload = gr.File(
                    label="RDML file (leave empty for the cached demo)",
                    file_types=[".rdml", ".xml"],
                    height=110,
                    elem_id="qs-upload",
                )
                ui.sheet = gr.File(
                    label="Sample sheet (optional: .xlsx or .csv)",
                    file_types=[".xlsx", ".csv"],
                    height=90,
                    elem_id="qs-sheet",
                )
                ui.sentence = gr.Textbox(
                    label="One sentence about the experiment (optional; used when the design "
                    "is proposed; the model sees it as quoted data, never as instructions)",
                    max_length=MAX_SENTENCE,
                    lines=2,
                    elem_id="qs-sentence",
                )
                ui.open_btn = gr.Button("Open", variant="primary", elem_id="qs-open")
                ui.file_info = gr.HTML()
                ui.strip = gr.HTML()
                ui.seen_btn = gr.Button("What the model saw", size="sm", elem_id="qs-seen-btn")
                ui.seen = gr.HTML(visible=False)
            with gr.Column(scale=2, min_width=380):
                gr.HTML("<h3>2 · What the AI thinks</h3>")
                ui.notice = gr.HTML()
                ui.stage_pick = gr.Radio(choices=[], label="Inbox of stage", elem_id="qs-stage")
                ui.inbox_head = gr.HTML()
                with gr.Row():
                    ui.design_btn = gr.Button(
                        "Propose the design", visible=False, elem_id="qs-propose-design"
                    )
                    ui.comparison_btn = gr.Button(
                        "Propose the comparison", visible=False, elem_id="qs-propose-comparison"
                    )
                    ui.curves_btn = gr.Button(
                        "Check the curves", visible=False, elem_id="qs-propose-curves"
                    )
                with gr.Row():
                    ui.bulk_show = gr.Button(
                        "Accept all consistent…", visible=False, elem_id="qs-bulk-show"
                    )
                    ui.reject_show = gr.Button(
                        "Reject all contradicted AI calls…", visible=False, elem_id="qs-reject-show"
                    )
                    ui.confirm_prepare = gr.Button(
                        "Confirm this stage…", visible=False, elem_id="qs-confirm-prepare"
                    )
                with gr.Group(visible=False) as ui.bulk_box:
                    ui.bulk_html = gr.HTML()
                    with gr.Row():
                        ui.bulk_accept = gr.Button(
                            "Accept", variant="primary", elem_id="qs-bulk-accept"
                        )
                        ui.bulk_cancel = gr.Button("Cancel", elem_id="qs-bulk-cancel")
                with gr.Group(visible=False) as ui.reject_box:
                    ui.reject_html = gr.HTML()
                    ui.reject_reason = gr.Textbox(
                        label="Reason (required, kept with each one)",
                        max_length=MAX_REASON,
                        elem_id="qs-reject-reason",
                    )
                    with gr.Row():
                        ui.reject_all = gr.Button("Reject", variant="stop", elem_id="qs-reject-all")
                        ui.reject_cancel = gr.Button("Cancel", elem_id="qs-reject-cancel")
                with gr.Group(visible=False) as ui.confirm_box:
                    ui.confirm_info = gr.HTML()
                    ui.confirm_reason = gr.Textbox(
                        label="Reason, only for “Not yet”",
                        max_length=MAX_REASON,
                        elem_id="qs-confirm-reason",
                    )
                    with gr.Row():
                        ui.confirm_btn = gr.Button(
                            "Yes, confirm", variant="primary", elem_id="qs-confirm"
                        )
                        ui.withdraw_btn = gr.Button("Not yet", elem_id="qs-confirm-withdraw")
                ui.slots = []
                for i in range(PAGE_SIZE):
                    with gr.Group(visible=False) as box:
                        html = gr.HTML()
                        reason = gr.Textbox(
                            label="Reason (required to reject, and to accept what the engine's "
                            "check contradicts)",
                            max_length=MAX_REASON,
                            lines=1,
                            elem_id=f"qs-reason-{i}",
                        )
                        with gr.Row():
                            accept = gr.Button(
                                "Accept", variant="primary", elem_id=f"qs-accept-{i}"
                            )
                            reject = gr.Button("Reject", elem_id=f"qs-reject-{i}")
                            matters = gr.Button(
                                "Does this matter?", visible=False, elem_id=f"qs-matters-{i}"
                            )
                        with gr.Accordion("Edit, then accept", open=False) as acc:
                            code = gr.Code(
                                language="json",
                                label="Payload (change values only)",
                                elem_id=f"qs-edit-{i}",
                            )
                            edit = gr.Button(
                                "Accept with these edits", elem_id=f"qs-edit-accept-{i}"
                            )
                    ui.slots.append(
                        SimpleNamespace(
                            box=box,
                            html=html,
                            reason=reason,
                            accept=accept,
                            reject=reject,
                            matters=matters,
                            acc=acc,
                            code=code,
                            edit=edit,
                        )
                    )
                with gr.Row():
                    ui.prev_btn = gr.Button("◀ Previous", size="sm", elem_id="qs-prev")
                    ui.page_info = gr.HTML()
                    ui.next_btn = gr.Button("Next ▶", size="sm", elem_id="qs-next")
                ui.decided = gr.HTML()
                with gr.Row():
                    ui.well_pick = gr.Dropdown(
                        choices=[], label="Curve of a cited well", elem_id="qs-well", scale=3
                    )
                    ui.curve_btn = gr.Button(
                        "Show the curve", size="sm", elem_id="qs-curve", scale=1
                    )
                ui.curve_plot = gr.Plot(visible=False, show_label=False)
            with gr.Column(scale=2, min_width=380):
                gr.HTML("<h3>3 · Prism preview</h3>")
                ui.blind_note = gr.HTML(BLIND_PANE)
                with gr.Column(visible=False) as ui.right:
                    ui.summary = gr.HTML()
                    ui.routes = gr.HTML()
                    gr.HTML("<h4>Decision Cards (the Choices stage)</h4>")
                    ui.card_pick = gr.Dropdown(choices=[], label="Card", elem_id="qs-card")
                    ui.card = gr.HTML()
                    ui.card_options = gr.Radio(choices=[], label="Your choice", elem_id="qs-option")
                    ui.card_reason = gr.Textbox(
                        label="Reason (required, kept in the record)",
                        max_length=MAX_REASON,
                        lines=2,
                        elem_id="qs-card-reason",
                    )
                    ui.decide_btn = gr.Button("Decide", variant="primary", elem_id="qs-decide")
                    gr.HTML("<h4>The Prism project</h4>")
                    ui.prism_status = gr.HTML()
                    ui.prism_btn = gr.Button("Draft the Prism project", elem_id="qs-propose-prism")
                    ui.preview = gr.HTML()
                    ui.gene_pick = gr.Dropdown(choices=[], label="Graph of", elem_id="qs-gene")
                    ui.prism_plot = gr.Plot(visible=False, show_label=False)
                    ui.prism_table = gr.HTML()
                    ui.send_btn = gr.Button("Send to Prism", variant="primary", elem_id="qs-send")
                    ui.send_info = gr.HTML()
                    ui.download = gr.DownloadButton("Download the bundle (.zip)", visible=False)
                    gr.HTML(ROUNDTRIP_HELP)
                    ui.bundle_pick = gr.Dropdown(
                        choices=[], label="Bundle sent from this page", elem_id="qs-bundle"
                    )
                    ui.sent_back = gr.Textbox(
                        label="Folder the tables came back to (inside the export folder or "
                        "your home folder)",
                        elem_id="qs-sent-back",
                    )
                    ui.roundtrip_btn = gr.Button(
                        "Read what changed in Prism", elem_id="qs-roundtrip"
                    )
        gr.HTML(
            '<div class="qp-footer">'
            + "<br>".join(footer_lines(__version__, VERMEULEN_COMMIT))
            + "<br>Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad "
            "Software or Dotmatics.</div>"
        )

        view = [
            ui.session,
            ui.model_line,
            ui.notice,
            ui.file_info,
            ui.strip,
            ui.stage_pick,
            ui.inbox_head,
            ui.design_btn,
            ui.comparison_btn,
            ui.curves_btn,
            ui.bulk_show,
            ui.reject_show,
            ui.confirm_prepare,
            ui.bulk_box,
            ui.bulk_html,
            ui.bulk_accept,
            ui.reject_box,
            ui.reject_html,
            ui.reject_all,
            ui.reject_reason,
            ui.confirm_box,
            ui.confirm_info,
            ui.confirm_btn,
            ui.confirm_reason,
            ui.prev_btn,
            ui.page_info,
            ui.next_btn,
            ui.decided,
            ui.well_pick,
            ui.curve_plot,
            ui.blind_note,
            ui.right,
            ui.summary,
            ui.routes,
            ui.card_pick,
            ui.card,
            ui.card_options,
            ui.card_reason,
            ui.decide_btn,
            ui.prism_status,
            ui.prism_btn,
            ui.preview,
            ui.gene_pick,
            ui.prism_plot,
            ui.prism_table,
            ui.send_btn,
            ui.send_info,
            ui.download,
            ui.bundle_pick,
            ui.sent_back,
            ui.seen,
        ]
        for slot in ui.slots:
            view += [
                slot.box,
                slot.html,
                slot.reason,
                slot.accept,
                slot.matters,
                slot.acc,
                slot.code,
            ]
        ui.view = view
        private = {"api_visibility": "private"}
        s = ui.session

        page.load(on_load, [s], view, **private)
        ui.stage_pick.input(on_stage, [s, ui.stage_pick], view, **private)
        ui.prev_btn.click(on_prev, [s], view, **private)
        ui.next_btn.click(on_next, [s], view, **private)
        ui.card_pick.input(on_card_pick, [s, ui.card_pick], view, **private)
        ui.gene_pick.input(
            on_gene, [s, ui.gene_pick], [s, ui.prism_plot, ui.prism_table], **private
        )
        ui.curve_btn.click(on_curve, [s, ui.well_pick], [ui.curve_plot, ui.notice], **private)
        ui.seen_btn.click(on_seen, [s], [s, ui.seen], **private)
        ui.open_btn.click(on_open, [s, ui.upload, ui.sheet], view, concurrency_limit=1, **private)
        ui.design_btn.click(
            on_propose_design, [s, ui.sentence], view, concurrency_limit=1, **private
        )
        ui.comparison_btn.click(on_propose_comparison, [s], view, **private)
        ui.curves_btn.click(on_propose_curves, [s], view, concurrency_limit=1, **private)
        ui.confirm_prepare.click(on_confirm_prepare, [s], view, **private)
        ui.prism_btn.click(on_propose_prism, [s], view, **private)
        ui.roundtrip_btn.click(on_roundtrip, [s, ui.bundle_pick, ui.sent_back], view, **private)
        ui.bulk_show.click(on_bulk_show, [s], view, **private)
        ui.bulk_accept.click(on_bulk_accept, [s], view, **private)
        ui.bulk_cancel.click(on_bulk_cancel, [s], view, **private)
        ui.reject_show.click(on_reject_show, [s], view, **private)
        ui.reject_all.click(on_reject_all, [s, ui.reject_reason], view, **private)
        ui.reject_cancel.click(on_reject_cancel, [s], view, **private)
        ui.confirm_btn.click(on_confirm, [s], view, **private)
        ui.withdraw_btn.click(on_confirm_withdraw, [s, ui.confirm_reason], view, **private)
        ui.decide_btn.click(on_decide, [s, ui.card_options, ui.card_reason], view, **private)
        ui.send_btn.click(on_send, [s], view, concurrency_limit=1, **private)
        for i, slot in enumerate(ui.slots):
            slot.accept.click(make_accept(i), [s, slot.reason], view, **private)
            slot.reject.click(make_reject(i), [s, slot.reason], view, **private)
            slot.edit.click(make_edit(i), [s, slot.code, slot.reason], view, **private)
            slot.matters.click(make_matters(i), [s], view, **private)
    page.qpilot_export_root = exports  # for launch_options and tests
    page.qpilot_ui = ui  # for tests
    return page


def launch_options(studio: Studio, export_root: Path) -> dict[str, Any]:
    """``launch`` arguments: :func:`qpilot.app.launch_options` (the same hardening), our CSS."""
    return {**app_launch_options(studio.store, export_root), "css": APP_CSS + STUDIO_CSS}


def main(port: int | None = None, studio: Studio | None = None) -> None:
    """Serve Studio on 127.0.0.1 (Open with no file uses the cached demo when it is there)."""
    studio = studio or Studio()
    rdml = demo_path()
    page = build_app(studio, rdml if rdml.exists() else None)
    page.launch(server_port=port, **launch_options(studio, page.qpilot_export_root))


__all__ = ["LAUNCH_OPTIONS", "build_app", "launch_options", "main", "new_session"]


if __name__ == "__main__":
    main()
