"""qPilot's one-page app: a Gradio front end over the on-disk study store (wiring only).

Every view is a pure function in :mod:`qpilot.app_state`; this module only connects the page to
the study store, the decision rules, the model layer, the harness and the Analysis Record.

Hardening, all of it set here and checked by ``tests/app/test_app.py``:

* telemetry off: ``GRADIO_ANALYTICS_ENABLED`` and ``HF_HUB_DISABLE_TELEMETRY`` are forced before
  ``import gradio`` (Hugging Face reads its flag at import time), and the page is built with
  ``analytics_enabled=False``;
* reachable from this machine only: bound to ``127.0.0.1``, never shared, and requests whose
  ``Host`` is not ``127.0.0.1`` or ``localhost`` are refused (a web page that rebinds its own name
  to this machine cannot drive the app); no monitoring routes, no run history kept in the
  browser, no API link in the footer, no server-side rendering process;
* the API key (``QPILOT_API_KEY``) is never shown on the page and is sent only with the
  configuration it was set for: Anthropic, or the local endpoint named in
  ``QPILOT_MODEL_ENDPOINT``, never an endpoint typed into the page;
* files are served only from a private export folder created for this launch; the study store
  and the dataset cache are blocked.

Decisions follow the escalation rule in :mod:`qpilot.core.decisions`: a person makes every
choice that can change a conclusion. Each Decide sends the chain head the page last showed; if
anything was written since (another tab, an agent), the card is re-read and the person is asked
to look again. In *Suggest* mode the model may only ask; in *Decide and tell me* it may apply
choices that change no conclusion, and the core still turns anything else into a request.
"""

from __future__ import annotations

import os

os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"  # read when Blocks() is built
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"  # frozen when huggingface_hub is imported

import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import gradio as gr  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

from qpilot import __version__  # noqa: E402
from qpilot.ai import payload_log  # noqa: E402
from qpilot.ai.ask import ask  # noqa: E402
from qpilot.ai.client import (  # noqa: E402
    AnthropicBackend,
    ModelClient,
    ModelUnavailable,
    NoneBackend,
    OpenAICompatibleBackend,
)
from qpilot.ai.config import ModelConfig  # noqa: E402
from qpilot.ai.explain import explain_card, log_line  # noqa: E402
from qpilot.ai.profile import Profile, build_fewshots, load_profile  # noqa: E402
from qpilot.app_state import (  # noqa: E402
    REVIEW_OUTCOME_CHOICES,
    card_view,
    cards_in_order,
    confidence_badge,
    decision_counter,
    esc,
    evidence_view,
    footer_lines,
    meter_html,
    next_card,
    policy_lines,
    results_table,
    review_body,
    review_head_line,
    study_summary,
)
from qpilot.core.decisions import (  # noqa: E402
    MAX_REASON,
    DecisionError,
    apply_decision,
    check_request,
    needs_human,
    reject_request,
)
from qpilot.core.record import RecordError, write_record, zip_record  # noqa: E402
from qpilot.core.store import MAX_REVIEWER, StaleReview, StudyNotFound, StudyStore  # noqa: E402
from qpilot.core.validator import names_from_result  # noqa: E402
from qpilot.explain.templates import to_html  # noqa: E402
from qpilot.harness.make_evalset import build_items  # noqa: E402
from qpilot.harness.report import Report, markdown  # noqa: E402
from qpilot.harness.run import run as run_harness  # noqa: E402
from qpilot.io.datasets import (  # noqa: E402
    VERMEULEN_COMMIT,
    VERMEULEN_FILENAME,
    VERMEULEN_SHA256,
    default_cache_dir,
)
from qpilot.qpcr.study import HEADLINE_GENES  # noqa: E402
from qpilot.report.run_review import build_review, render_html, run_review  # noqa: E402
from qpilot.schemas import DecisionCard, DecisionEntry, DecisionOutcome  # noqa: E402

PROVIDERS = {"None": "none", "Anthropic": "anthropic", "Local": "openai_compatible"}
PROVIDER_LABELS = {value: label for label, value in PROVIDERS.items()}
SCORECARD_KEYS = {"none": "none", "anthropic": "anthropic", "openai_compatible": "local"}
AUTONOMY_CHOICES = [("Suggest", "suggest"), ("Decide and tell me", "decide_and_tell")]
MODEL_TIMEOUT_S = 15.0
HARNESS_ITEMS_PER_TYPE = 3
UNDO_PREFIX = "Undo:"
DEMO_STUDY_ID = VERMEULEN_SHA256[:12]
LOCAL_HOSTS = ["127.0.0.1", "localhost"]
STALE_NOTICE = "This card changed since you read it. Please re-read it, then decide again."
MOVED_NOTICE = (
    "Something was decided since this page last showed the study (another tab or an agent); "
    "the card below is current."
)
REVIEW_STALE_NOTICE = (
    "Something was decided since the Run Review was shown, so it is shown again below. Look at "
    "it, then sign off again."
)
EVIDENCE_FILE = "evidence.json"
SUGGEST_ONLY_REASON = (
    "Suggest mode: the assistant may only ask. This choice changes no conclusion, but a person "
    "confirms it."
)

#: Everything passed to ``launch`` apart from per-launch paths; tests assert on it. Gradio falls
#: back to environment variables for options left unset, so every one is explicit.
LAUNCH_OPTIONS: dict[str, Any] = {
    "server_name": "127.0.0.1",
    "share": False,
    "inbrowser": False,
    "max_file_size": "200mb",
    "footer_links": [],
    "enable_monitoring": False,
    "run_history": False,
    "mcp_server": False,
    "ssr_mode": False,
    "show_error": False,
}

CSS = """
.qp-summary, .qp-rule, .qp-design { margin: 0 0 .4rem 0; }
.qp-rule, .qp-design { font-size: .85rem; opacity: .85; }
.fact { border-bottom: 1px dotted currentColor; cursor: help; }
.qp-meter-row { display: grid; grid-template-columns: 4.5rem 6.5rem 1fr 9rem;
  gap: .5rem; align-items: center; margin: .25rem 0; font-size: .9rem; }
.qp-bar { height: .6rem; border-radius: .3rem; background: rgba(127,127,127,.25); }
.qp-fill { display: block; height: 100%; border-radius: .3rem; background: #16a34a; }
.qp-meter-row.fragile .qp-fill { background: #d97706; }
.qp-badge { display: inline-block; padding: 0 .45rem; border-radius: .5rem; font-weight: 600;
  background: rgba(127,127,127,.2); }
.qp-badge.level-high { background: #bbf7d0; color: #14532d; }
.qp-badge.level-moderate { background: #fef08a; color: #713f12; }
.qp-badge.level-low { background: #fed7aa; color: #7c2d12; }
.qp-badge.level-very_low { background: #fecaca; color: #7f1d1d; }
.qp-card h3 { margin: 0 0 .3rem 0; }
.qp-impact { font-weight: 600; }
.qp-options { width: 100%; border-collapse: collapse; font-size: .9rem; }
.qp-options th, .qp-options td { padding: .25rem .4rem; text-align: left;
  border-bottom: 1px solid rgba(127,127,127,.25); }
.qp-options tr.recommended td:first-child { font-weight: 600; }
.qp-tag { font-size: .7rem; padding: 0 .3rem; border-radius: .4rem;
  background: rgba(127,127,127,.2); }
.qp-tag.chosen { background: #bfdbfe; color: #1e3a8a; }
.qp-tag.miqe { background: #fecaca; color: #7f1d1d; }
.qp-c-no_call { opacity: .7; }
.qp-notice { padding: .4rem .6rem; border-radius: .4rem; background: rgba(217,119,6,.15); }
.qp-dot { display: inline-block; width: .6rem; height: .6rem; border-radius: 50%;
  margin-right: .35rem; background: #9ca3af; }
.qp-dot.on { background: #16a34a; } .qp-dot.off { background: #dc2626; }
.qp-policy { font-size: .85rem; margin: 0; padding-left: 1.1rem; }
.qp-footer { font-size: .8rem; opacity: .8; }
.qp-ev, .qp-review .status { display: inline-block; padding: 0 .45rem; border-radius: .5rem;
  font-size: .8rem; font-weight: 600; background: rgba(127,127,127,.2); white-space: nowrap; }
.qp-ev-present, .qp-review .status-present { background: #bbf7d0; color: #14532d; }
.qp-ev-absent, .qp-review .status-absent { background: #fed7aa; color: #7c2d12; }
.qp-ev-items, .qp-ev-lines { margin: .2rem 0; padding-left: 1.1rem; font-size: .9rem; }
.qp-evidence h5 { margin: .4rem 0 .2rem 0; }
.qp-review .muted { font-size: .85rem; opacity: .8; }
.qp-review table { width: 100%; border-collapse: collapse; font-size: .9rem; }
.qp-review th, .qp-review td { padding: .25rem .4rem; text-align: left; vertical-align: top;
  border-bottom: 1px solid rgba(127,127,127,.25); }
"""


# ---------- per-tab state ----------


def new_session() -> dict[str, Any]:
    """What the tab is looking at: plain values only (Gradio deep-copies state)."""
    return {"study_id": None, "card_id": None, "head": None, "review_head": None}


def default_settings() -> dict[str, Any]:
    """The tab's settings, kept apart from the session so a slow handler can never undo them.

    The model fields start from ``QPILOT_MODEL_PROVIDER`` / ``_ENDPOINT`` / ``_NAME`` when set.
    """
    settings = {"autonomy": "suggest", "provider": "None", "endpoint": "", "model": ""}
    try:
        config = ModelConfig.from_env()
    except ValueError:
        return settings
    return {
        **settings,
        "provider": PROVIDER_LABELS.get(config.provider, "None"),
        "endpoint": config.endpoint or "",
        "model": config.model or "",
    }


def demo_path() -> Path:
    """Where ``qpilot fetch-demo`` keeps the demo study."""
    return default_cache_dir() / VERMEULEN_FILENAME


# ---------- the model ----------


def _same_endpoint(a: str | None, b: str | None) -> bool:
    def norm(url: str | None) -> str:
        url = (url or "").strip().rstrip("/")
        return url[: -len("/v1")] if url.endswith("/v1") else url

    return bool(norm(a)) and norm(a) == norm(b)


def _api_key_for(provider: str, endpoint: str | None) -> str | None:
    """``QPILOT_API_KEY``, only for the configuration it was set for (see the module docstring)."""
    key = os.environ.get("QPILOT_API_KEY") or None
    configured = (os.environ.get("QPILOT_MODEL_PROVIDER") or "").strip().lower() or None
    if provider == "anthropic":
        return key if configured in (None, "anthropic") else None
    if provider == "openai_compatible" and configured == "openai_compatible":
        return key if _same_endpoint(endpoint, os.environ.get("QPILOT_MODEL_ENDPOINT")) else None
    return None


def build_client(provider_label: str, endpoint: str, model: str) -> tuple[ModelClient, str | None]:
    """A model client for the page's choice, and the reason it could not be built (if any)."""
    provider = PROVIDERS.get(provider_label, "none")
    if provider == "none":
        return ModelClient(NoneBackend()), None
    endpoint_value = (endpoint or "").strip() or None if provider == "openai_compatible" else None
    config = ModelConfig(
        provider=provider,
        endpoint=endpoint_value,
        model=(model or "").strip() or None,
        api_key=_api_key_for(provider, endpoint_value),
    )
    backend = AnthropicBackend if provider == "anthropic" else OpenAICompatibleBackend
    try:
        return ModelClient(backend(config, timeout=MODEL_TIMEOUT_S)), None
    except ModelUnavailable as err:
        return ModelClient(NoneBackend()), str(err)


def _load_profile() -> Profile:
    try:
        return load_profile()
    except Exception:  # a broken profile must not stop the app; the default is shown instead
        return Profile()


# ---------- small helpers ----------


def _notice(text: str) -> str:
    return f'<p class="qp-notice">{esc(text)}</p>' if text else ""


def _error(err: Exception) -> str:
    """A core error as a sentence, first letter capitalised."""
    text = str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err)
    return text[:1].upper() + text[1:]


def _genorm_figure(card: DecisionCard) -> go.Figure | None:
    """Bar chart of geNorm M per candidate with the stability cut-off, for the reference card."""
    evidence = card.evidence
    if card.kind != "reference_set" or "genorm_M" not in evidence:
        return None
    order = list(evidence.get("genorm_order") or evidence["genorm_M"])
    values = [evidence["genorm_M"][gene] for gene in order]
    figure = go.Figure(go.Bar(x=order, y=values, marker_color="#64748b"))
    if "cutoff_M" in evidence:
        figure.add_hline(
            y=evidence["cutoff_M"],
            line_dash="dash",
            line_color="#16a34a",
            annotation_text="usual stability cut-off",
        )
    figure.update_layout(
        title="Control-gene stability (geNorm M, lower is more stable)",
        height=280,
        margin={"l": 40, "r": 10, "t": 40, "b": 40},
        yaxis_title="M",
    )
    return figure


def undo_target(entries: list[DecisionEntry], card_id: str) -> str | None:
    """The option Undo restores: one step back through the card's history, or ``None``.

    Replays the card's applied entries as a stack: an entry whose reason starts with ``Undo:``
    pops the step it undid, a repeated choice is not a new step.
    """
    stack: list[str] = []
    for entry in entries:
        if entry.card_id != card_id or entry.status not in ("applied", "auto"):
            continue
        if entry.reason.startswith(UNDO_PREFIX):
            if stack:
                stack.pop()
            continue
        if not stack or stack[-1] != entry.option:
            stack.append(entry.option)
    return stack[-2] if len(stack) >= 2 else None


def _snapshot(store: StudyStore, study_id: str):
    """Head, cards and pending requests read together under the workspace lock.

    The store writes the log line before it replaces ``cards.json``; reading both under its lock
    means the page never pairs a new head with an old card. (A ``snapshot`` method in the core
    would replace this use of the store's lock.)
    """
    with store._locked(store.workspace(study_id)):
        return store.chain_head(study_id), store.cards(study_id), store.pending(study_id)


class SuggestOnlyStore(StudyStore):
    """The store as the model sees it in *Suggest* mode: it may ask, never apply.

    Every decision by an actor other than a person becomes a request for a person, on any card.
    (The core already does this for choices that can change a conclusion.)
    """

    def append_decision(self, study_id, card_id, option, reason, actor, expected_head):
        """Turn an agent's decision into a request; a person's decision passes through."""
        if actor == "human":
            return super().append_decision(study_id, card_id, option, reason, actor, expected_head)
        card = self.card(study_id, card_id)
        cleaned = check_request(card, option, reason)
        outcome = self.request_human(study_id, card_id, option, cleaned, actor, expected_head)
        if outcome.status == "pending_human" and not needs_human(card):
            outcome = outcome.model_copy(update={"reason": SUGGEST_ONLY_REASON})
        return outcome


# ---------- the page ----------


def build_app(
    store: StudyStore, default_rdml: Path | None = None, export_root: Path | None = None
) -> gr.Blocks:
    """Build the page over ``store``.

    Args:
        store: The study store (shared with ``qpilot serve`` through ``QPILOT_STUDIES_DIR``).
        default_rdml: Analysed when Analyse is pressed with no file uploaded (the demo study).
        export_root: Folder for exported records; a private temporary folder by default.
    """
    profile = _load_profile()
    exports = Path(export_root) if export_root else Path(tempfile.mkdtemp(prefix="qpilot-exports-"))
    exports.mkdir(parents=True, exist_ok=True)

    # ---------- reading the store ----------

    def card_outputs(
        session: dict[str, Any],
        notice: str = "",
        *,
        clear_reason: bool = False,
        warn_if_moved: bool = False,
    ) -> tuple:
        """Everything that shows one card (11 outputs, see ``card_outs`` below)."""
        reason = gr.update(value="") if clear_reason else gr.update()
        hide_download = gr.update(visible=False)
        sid = session.get("study_id")
        if not sid:
            return (
                session,
                "",
                "",
                gr.update(choices=[], value=None),
                reason,
                _notice(notice),
                gr.update(visible=False),
                gr.update(value="Undo", interactive=False),
                gr.update(visible=False),
                gr.update(choices=[], value=None),
                hide_download,
            )
        head, cards, pending = _snapshot(store, sid)
        cards = cards_in_order(cards)
        if not cards:
            return card_outputs(new_session(), "This study has no decision cards.")
        if warn_if_moved and session.get("head") and head != session["head"]:
            notice = f"{notice} {MOVED_NOTICE}".strip()
        result = store.get(sid)
        by_id = {c.id: c for c in cards}
        card = by_id.get(session.get("card_id")) or next_card(cards) or cards[0]
        session = {**session, "card_id": card.id, "head": head}
        asked = [p.option for p in pending if p.card_id == card.id]
        view = card_view(
            card,
            result.facts,
            allowed_names=names_from_result(result),
            pending_option=asked[-1] if asked else None,
        )
        figure = _genorm_figure(card)
        target = undo_target(store.entries(sid), card.id)
        labels = {o.id: o.label for o in card.options}
        undo = (
            gr.update(value=f"Undo: back to {labels.get(target, target)}", interactive=True)
            if target
            else gr.update(value="Undo", interactive=False)
        )
        picker = [(f"{c.rank}. {c.kind.replace('_', ' ')} ({c.status.replace('_', ' ')})", c.id)
                  for c in cards]  # fmt: skip
        return (
            session,
            view.html,
            esc(decision_counter(cards)),
            gr.update(choices=[(o.label, o.id) for o in card.options], value=None),
            reason,
            _notice(notice),
            gr.update(value=figure, visible=figure is not None),
            undo,
            gr.update(visible=card.status == "pending_human"),
            gr.update(choices=picker, value=card.id),
            hide_download,
        )

    def study_ledger(sid: str):
        """The study's Evidence Ledger, or ``None`` and why.

        The kept ``evidence.json`` when it is this study's, else one rebuilt read-only from the
        input file and kept (a cache; a ledger never changes a conclusion).
        """
        from qpilot.qpcr.evidence import (
            LEDGER_VERSION,
            EvidenceError,
            EvidenceLedger,
            evidence_store,
        )

        try:
            data = store.get_artifact(sid, EVIDENCE_FILE)
            kept = EvidenceLedger.model_validate(data) if data else None
        except Exception:  # an unreadable kept ledger is rebuilt
            kept = None
        if kept is not None and kept.version == LEDGER_VERSION and kept.study_id == sid:
            return kept, ""
        try:
            ledger = evidence_store(store, sid)
        except EvidenceError as err:
            return None, str(err)
        except Exception as err:  # the panel says so; the page stays up
            return None, f"it could not be built ({type(err).__name__})"
        try:
            store.put_artifact(sid, EVIDENCE_FILE, ledger.model_dump(mode="json"))
        except Exception:  # keeping it only saves time next open
            pass
        return ledger, ""

    def review_html(sid: str, ledger=None, note: str = "") -> str:
        """The Run Review of the study, with every sign-off the decision log holds."""
        try:
            reviews = store.reviews(sid)
            if ledger is not None:
                review = run_review(store, sid, reviews=reviews, ledger=ledger)
            else:
                design = store.design(sid)
                headline = tuple(design.headline) if design is not None else HEADLINE_GENES
                review = build_review(store.get(sid), headline=headline, ledger_note=note,
                                      reviews=reviews)  # fmt: skip
            return f'<div class="qp-review">{review_body(render_html(review))}</div>'
        except Exception as err:  # shown, not raised
            return _notice(f"The Run Review could not be shown: {_error(err)}")

    def study_outputs(session: dict[str, Any]) -> tuple:
        sid = session["study_id"]
        result = store.get(sid)
        ledger, note = study_ledger(sid)
        genes = [g for g in HEADLINE_GENES if g in result.contrasts] or list(result.contrasts)[:4]
        confidence = "".join(
            f"<h4>{esc(g)}</h4>{confidence_badge(result.confidence[g], g, result.facts)}"
            for g in genes
            if g in result.confidence
        )
        return (
            study_summary(result).html,
            meter_html(result, genes),
            confidence,
            results_table(result),
            evidence_view(ledger, note),
            review_html(sid, ledger, note),
        )

    def keep_study_outputs() -> tuple:
        return tuple(gr.update() for _ in study_outs)

    def _open(session: dict[str, Any], study_id: str, note: str = "") -> tuple:
        cards = store.cards(study_id)
        waiting = next_card(cards)
        if waiting is None:
            flipping = [c for c in cards_in_order(cards) if c.impact.get("flips")]
            first = flipping[0] if flipping else cards_in_order(cards)[0]
            note = (
                f"{note} Every choice in this study is already decided; the record keeps them all."
                " For a clean run of the demo, start the app with `qpilot app --fresh-demo`."
            ).strip()
            session = {**session, "study_id": study_id, "card_id": first.id}
        else:
            session = {**session, "study_id": study_id, "card_id": waiting.id}
        # Read before the Run Review is drawn: a write in between makes a sign-off stale, never
        # the other way round.
        session = {**session, "review_head": store.chain_head(study_id)}
        return (*card_outputs(session, note, clear_reason=True), *study_outputs(session))

    # ---------- handlers ----------

    def on_load(session):
        return card_outputs(session or new_session())

    def on_analyse(session, upload):
        """Open the uploaded file, or the demo study; analysis runs once per file."""
        path = Path(upload) if upload else default_rdml
        if path is None or not path.exists():
            studies = store.list_studies()  # e.g. a study an agent opened through `qpilot serve`
            if not studies:
                notice = "No study yet: run `qpilot fetch-demo`, or upload an RDML file."
                return (*card_outputs(session, notice), *keep_study_outputs())
            chosen = DEMO_STUDY_ID if DEMO_STUDY_ID in studies else studies[0]
            note = "" if chosen == DEMO_STUDY_ID else f"Opened study {chosen} (no file given)."
            return _open(session, chosen, note)
        try:
            sid = store.ensure_study(path)
        except Exception as err:  # any analysis failure is shown on the page, not raised
            notice = (
                f"Could not analyse {path.name}: {err}. qPilot's analysis is set up for the "
                "demo study's design; other designs are on the roadmap."
            )
            return (*card_outputs(session, notice, warn_if_moved=True), *keep_study_outputs())
        return _open(session, sid)

    def on_pick(session, card_id):
        if not session.get("study_id") or not card_id or card_id == session.get("card_id"):
            return tuple(gr.update() for _ in card_outs)  # no-op: keep the person's choice
        return card_outputs({**session, "card_id": card_id}, clear_reason=True)

    def _after(session, outcome: DecisionOutcome, done: str) -> tuple:
        if outcome.status == "stale":
            return card_outputs(session, STALE_NOTICE)
        if outcome.status == "applied":
            upcoming = next_card(store.cards(session["study_id"]))
            session = {**session, "card_id": upcoming.id if upcoming else session["card_id"]}
            follow = "" if upcoming else " Every choice is decided; export the record below."
            return card_outputs(session, done + follow, clear_reason=True)
        return card_outputs(session, outcome.reason or outcome.status, clear_reason=True)

    def on_decide(session, option, reason):
        if not session.get("study_id"):
            return card_outputs(session, "Analyse a study first.")
        if not option:
            return card_outputs(session, "Pick an option first.", warn_if_moved=True)
        text = (reason or "").strip()
        if text.startswith(UNDO_PREFIX):  # only the Undo button may write an undo
            text = text[len(UNDO_PREFIX) :].strip()
        try:
            outcome = apply_decision(store, session["study_id"], session["card_id"], option,
                                     text, "human", session["head"])  # fmt: skip
        except (DecisionError, KeyError) as err:
            return card_outputs(session, _error(err), warn_if_moved=True)
        labels = {o.id: o.label for o in outcome.card.options} if outcome.card else {}
        return _after(session, outcome, f"Decided: {labels.get(option, option)}.")

    def on_undo(session, reason):
        sid, card_id = session.get("study_id"), session.get("card_id")
        if not sid or not card_id:
            return card_outputs(session)
        target = undo_target(store.entries(sid), card_id)
        if target is None:
            return card_outputs(session, "Nothing to undo on this card.", warn_if_moved=True)
        text = (reason or "").strip()
        if not text:
            return card_outputs(session, "Type a reason for the undo first.", warn_if_moved=True)
        text = f"{UNDO_PREFIX} {text}"[:MAX_REASON]
        try:
            outcome = apply_decision(store, sid, card_id, target, text, "human", session["head"])
        except (DecisionError, KeyError) as err:
            return card_outputs(session, _error(err), warn_if_moved=True)
        if outcome.status == "applied":
            labels = {o.id: o.label for o in outcome.card.options} if outcome.card else {}
            note = f"Undone: back to {labels.get(target, target)}, written as a new entry."
            return card_outputs(session, note, clear_reason=True)
        return _after(session, outcome, "")

    def on_reject(session, reason):
        sid, card_id = session.get("study_id"), session.get("card_id")
        if not sid or not card_id:
            return card_outputs(session)
        try:
            outcome = reject_request(store, sid, card_id, reason or "", session["head"])
        except (DecisionError, KeyError) as err:
            return card_outputs(session, _error(err), warn_if_moved=True)
        if outcome.status == "stale":
            return card_outputs(session, STALE_NOTICE)
        return card_outputs(session, "The agent's request was turned down.", clear_reason=True)

    def on_sign_off(session, outcome, comment, reviewer):
        """A person signs off the Run Review: one review entry in the decision log.

        Only this click writes a review, always as ``human``; the chain head read when the
        review was drawn is sent, so a decision made since makes the sign-off stale.
        """
        keep = gr.update()
        sid = session.get("study_id")
        if not sid:
            return session, keep, _notice("Analyse a study first."), keep, keep
        if not outcome:
            return session, keep, _notice("Pick accept, repeat or discuss first."), keep, keep
        try:
            entry = store.append_review(
                sid,
                outcome,
                comment or "",
                reviewer or "",
                actor="human",
                expected_head=session.get("review_head"),
            )
        except StaleReview:
            session = {**session, "review_head": store.chain_head(sid)}
            ledger, note = study_ledger(sid)
            return (session, review_html(sid, ledger, note), _notice(REVIEW_STALE_NOTICE),
                    keep, keep)  # fmt: skip
        except (DecisionError, StudyNotFound, KeyError) as err:
            return session, keep, _notice(_error(err)), keep, keep
        update = {"review_head": entry.hash}
        if session.get("head") == entry.prev_hash:  # nothing else moved: the card view is current
            update["head"] = entry.hash
        session = {**session, **update}
        ledger, note = study_ledger(sid)
        done = f"Signed off ({outcome}); the decision log keeps it with your name and comment."
        return (session, review_html(sid, ledger, note), _notice(done), gr.update(value=""),
                review_head_line(entry.hash))  # fmt: skip

    def on_autonomy(settings, level):
        return {**settings, "autonomy": level or "suggest"}

    def on_model(settings, provider, endpoint, model):
        payload_log.clear()  # the panel must not show another model's payload
        settings = {
            **settings,
            "provider": provider or "None",
            "endpoint": endpoint or "",
            "model": model or "",
        }
        return settings, '<span class="qp-dot"></span>not checked'

    def on_connect(settings):
        client, error = build_client(settings["provider"], settings["endpoint"], settings["model"])
        if error:
            return f'<span class="qp-dot off"></span>{esc(error)}'
        if not client.available:
            return '<span class="qp-dot"></span>no model: answers come from templates'
        if client.ping():
            return f'<span class="qp-dot on"></span>connected ({esc(client.provider)})'
        return f'<span class="qp-dot off"></span>no answer from {esc(client.provider)}'

    def on_seen():
        payload = payload_log.last_payload()
        if payload is None:
            return gr.update(value="No model call yet.", visible=True)
        return gr.update(value=json.dumps(payload, indent=2, ensure_ascii=False), visible=True)

    def on_explain(session, settings):
        sid = session.get("study_id")
        if not sid:
            return ""
        client, error = build_client(settings["provider"], settings["endpoint"], settings["model"])
        result, cards = store.get(sid), store.cards(sid)
        card = next((c for c in cards if c.id == session.get("card_id")), cards[0])
        shots = build_fewshots(store.entries(sid), cards, profile.max_fewshots)
        explained = explain_card(
            card, result.facts, profile=profile, client=client,
            allowed_names=names_from_result(result), fewshots=shots,
        )  # fmt: skip
        if client.available:
            store.append_ai_call(sid, log_line(explained, client))
        source = f"model ({client.provider})" if not explained.fallback else "template"
        why = explained.error or error
        note = f" The model was not used: {why}." if explained.fallback and why else ""
        try:
            body = to_html(explained.tokens, result.facts)
        except KeyError:
            body = esc(explained.plain)
        return f"<p><b>Explanation, from the {esc(source)}.</b>{esc(note)}</p><p>{body}</p>"

    def on_ask(session, settings, question):
        sid = session.get("study_id")
        if not sid:
            return (_notice("Analyse a study first."), *card_outputs(session))
        client, error = build_client(settings["provider"], settings["endpoint"], settings["model"])
        acting = (
            store if settings.get("autonomy") == "decide_and_tell" else SuggestOnlyStore(store.root)
        )
        before = store.chain_head(sid)
        try:
            answer = ask(question or "", acting, sid, client=client, profile=profile)
        except Exception as err:  # a failed answer must not take the page down
            return (_notice(f"No answer: {_error(err)}"), *card_outputs(session))
        facts = {**store.get(sid).facts, **answer.facts}
        try:
            body = to_html(answer.answer, facts) if answer.validated else esc(answer.plain)
        except KeyError:
            body = esc(answer.plain)
        notes = []
        if answer.status == "pending_human":
            notes.append("The request waits for you on the card, with a button to turn it down.")
            asked = next((c["args"].get("card_id") for c in reversed(answer.tool_calls)
                          if c.get("tool") == "qpcr_decide"), None)  # fmt: skip
            if asked:
                session = {**session, "card_id": asked}
        if answer.fallback and (answer.error or error):
            notes.append(f"Template answer; the model was not used: {answer.error or error}.")
        extra = "".join(f"<p>{esc(n)}</p>" for n in notes)
        moved = session.get("head") and before != session.get("head")
        # Ask may have written to the log, so the card is re-read; a change made elsewhere before
        # the question is still flagged.
        card = card_outputs(session, MOVED_NOTICE if moved else "")
        return (f"<p>{body}</p>{extra}", *card)

    def on_check(session, settings):
        sid = session.get("study_id")
        if not sid:
            return "Analyse a study first."
        client, error = build_client(settings["provider"], settings["endpoint"], settings["model"])
        if error:
            return f"Model not available: {error}"
        result, cards = store.get(sid), store.cards(sid)
        items = build_items(result, cards, n_per_type=HARNESS_ITEMS_PER_TYPE)
        key = SCORECARD_KEYS.get(client.provider, client.provider)
        report = run_harness(items, client, store, sid, profile=profile, profile_name=key)
        saved = store.scorecard(sid)
        saved[report.profile] = report.model_dump()
        store.put_scorecard(sid, saved)
        table = markdown([Report.model_validate(r) for r in saved.values()])
        return (
            f"{table}\nComputed now on {len(items)} questions for {key}. *Fallbacks* counts "
            "answers where the model was not usable and a template answered instead."
        )

    def on_export(session):
        sid = session.get("study_id")
        if not sid:
            return gr.update(visible=False), _notice("Analyse a study first.")
        folder = Path(tempfile.mkdtemp(prefix="record-", dir=exports))
        try:
            info = write_record(store, sid, folder / "record")
        except RecordError as err:
            shutil.rmtree(folder, ignore_errors=True)
            return gr.update(visible=False), _notice(f"Export failed: {_error(err)}")
        archive = zip_record(info.record_dir, folder / f"qpilot-record-{sid}.zip")
        shutil.rmtree(info.record_dir, ignore_errors=True)  # keep only the zip
        cards = store.cards(sid)
        open_flips = [
            c for c in cards if c.impact.get("flips") and c.status in ("open", "pending_human")
        ]
        warnings = []
        if open_flips:
            warnings.append(
                f"{len(open_flips)} choice(s) that can change a conclusion are still open; "
                "the record says so."
            )
        if info.chain_head != session.get("head"):
            warnings.append("Something was decided after this page last refreshed.")
        status = (
            f"Record {info.record_id[:12]}: {info.n_files} files"
            f"{', input file included' if info.input_included else ''}. "
            f"Check it with: qpilot verify {archive.name}. {' '.join(warnings)}"
        ).strip()
        return gr.update(value=str(archive), visible=True), _notice(status)

    # ---------- layout ----------

    with gr.Blocks(title="qPilot", analytics_enabled=False) as page:
        session = gr.State(new_session())
        initial = default_settings()
        settings = gr.State(initial)
        gr.HTML(
            "<h2>qPilot: robust qPCR analysis with the choices shown</h2>"
            '<ul class="qp-policy">' + "".join(f"<li>{line}</li>" for line in policy_lines())
            + "</ul>"
        )  # fmt: skip
        with gr.Row():
            autonomy = gr.Radio(AUTONOMY_CHOICES, value="suggest", label="Autonomy", scale=2)
            gr.Button("Teach me (roadmap)", interactive=False, scale=1)
            provider = gr.Radio(list(PROVIDERS), value=initial["provider"], label="Model", scale=2)
            endpoint = gr.Textbox(value=initial["endpoint"], label="Endpoint (Local)",
                                  placeholder="http://127.0.0.1:11434", scale=2)  # fmt: skip
            model_name = gr.Textbox(value=initial["model"], label="Model name", scale=2)
        with gr.Row():
            connect = gr.Button("Check connection", scale=1)
            model_status = gr.HTML('<span class="qp-dot"></span>not checked')
            seen_button = gr.Button("What the model sees", scale=1)
        seen = gr.Code(language="json", label="Last payload sent to the model", visible=False)
        with gr.Row():
            upload = gr.File(label="RDML file (leave empty for the demo study)",
                             file_types=[".rdml", ".xml"], height=120, scale=3)  # fmt: skip
            analyse = gr.Button("Analyse", variant="primary", scale=1)
        with gr.Row():
            with gr.Column(scale=2):
                evidence = gr.HTML()
                summary = gr.HTML()
                meter = gr.HTML()
                confidence = gr.HTML()
            with gr.Column(scale=3):
                counter = gr.HTML()
                picker = gr.Dropdown(choices=[], label="Card", interactive=True)
                card = gr.HTML()
                figure = gr.Plot(visible=False, show_label=False)
                options = gr.Radio(choices=[], label="Your choice")
                reason = gr.Textbox(label="Reason (required, kept in the record)",
                                    max_length=MAX_REASON, lines=2)  # fmt: skip
                with gr.Row():
                    decide = gr.Button("Decide", variant="primary")
                    undo = gr.Button("Undo", interactive=False)
                    reject = gr.Button("Turn down the agent's request", visible=False)
                    explain = gr.Button("Explain with the model")
                notice = gr.HTML()
                explanation = gr.HTML()
        results = gr.Dataframe(label="All genes", interactive=False, wrap=True)
        with gr.Row():
            question = gr.Textbox(
                label="Ask your data",
                placeholder="Is ODC1 robust? What happens to NM23A with HMBS alone?",
                scale=4,
            )
            ask_button = gr.Button("Ask", scale=1)
        answer = gr.HTML()
        with gr.Row():
            check = gr.Button("Check model")
            export = gr.Button("Export Analysis Record")
            download = gr.DownloadButton("Download the record (.zip)", visible=False)
        scorecard = gr.Markdown()
        export_status = gr.HTML()
        with gr.Accordion("Run Review", open=False):
            review = gr.HTML()
            review_outcome = gr.Radio(REVIEW_OUTCOME_CHOICES, label="Your sign-off")
            review_comment = gr.Textbox(label="Comment (required, kept in the decision log)",
                                        max_length=MAX_REASON, lines=2)  # fmt: skip
            reviewer = gr.Textbox(label="Your name (kept in the decision log)",
                                  max_length=MAX_REVIEWER)  # fmt: skip
            sign_off = gr.Button("Sign off", variant="primary")
            review_notice = gr.HTML()
            review_head = gr.HTML()
        gr.HTML(
            '<div class="qp-footer">'
            + "<br>".join(footer_lines(__version__, VERMEULEN_COMMIT))
            + "</div>"
        )

        card_outs = [session, card, counter, options, reason, notice, figure, undo, reject,
                     picker, download]  # fmt: skip
        study_outs = [summary, meter, confidence, results, evidence, review]
        page.load(on_load, [session], card_outs)
        analyse.click(on_analyse, [session, upload], card_outs + study_outs, concurrency_limit=2)
        picker.select(on_pick, [session, picker], card_outs)
        decide.click(on_decide, [session, options, reason], card_outs)
        undo.click(on_undo, [session, reason], card_outs)
        reject.click(on_reject, [session, reason], card_outs)
        autonomy.change(on_autonomy, [settings, autonomy], [settings])
        for field in (provider, endpoint, model_name):
            field.change(on_model, [settings, provider, endpoint, model_name],
                         [settings, model_status])  # fmt: skip
        connect.click(on_connect, [settings], [model_status])
        seen_button.click(on_seen, None, [seen])
        explain.click(on_explain, [session, settings], [explanation])
        ask_button.click(on_ask, [session, settings, question], [answer, *card_outs])
        check.click(on_check, [session, settings], [scorecard], concurrency_limit=1)
        export.click(on_export, [session], [download, export_status])
        sign_off.click(on_sign_off, [session, review_outcome, review_comment, reviewer],
                       [session, review, review_notice, review_comment, review_head])  # fmt: skip
    page.qpilot_export_root = exports  # for launch_options and tests
    return page


def launch_options(store: StudyStore, export_root: Path) -> dict[str, Any]:
    """``launch`` arguments: the hardening above plus the only folder files are served from."""
    blocked = {str(store.root), str(default_cache_dir())}
    return {
        **LAUNCH_OPTIONS,
        "allowed_paths": [str(export_root)],
        "blocked_paths": sorted(blocked),
        "app_kwargs": {
            "middleware": [Middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)]
        },
        "css": CSS,
        "theme": gr.themes.Default(),
    }


def archive_demo(store: StudyStore) -> Path | None:
    """Move the demo study's workspace aside (never deleted) so the next run starts clean."""
    if DEMO_STUDY_ID not in store.list_studies():
        return None
    workspace = store.workspace(DEMO_STUDY_ID)
    archive = store.root.parent / "studies-archive"
    archive.mkdir(parents=True, exist_ok=True)
    n = 1
    while (archive / f"{workspace.name}-{n}").exists():
        n += 1
    target = archive / f"{workspace.name}-{n}"
    shutil.move(str(workspace), str(target))
    return target


def main(port: int | None = None, fresh_demo: bool = False) -> None:
    """Open the demo study once (so Analyse is instant), then serve the page on 127.0.0.1."""
    store = StudyStore()
    if fresh_demo:
        moved = archive_demo(store)
        if moved:
            print(f"Earlier demo decisions moved to {moved}")
    rdml = demo_path()
    if rdml.exists():
        store.ensure_study(rdml)  # runs the analysis once if the workspace is missing
    page = build_app(store, rdml if rdml.exists() else None)
    page.launch(server_port=port, **launch_options(store, page.qpilot_export_root))


if __name__ == "__main__":
    main()
