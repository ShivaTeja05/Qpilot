"""The Design page's own editing: a person sets the design items nobody proposed.

The rules propose groups only from a sample sheet's group column and reference genes only from
what the file or the sheet declares, and a model is optional. So a person must be able to finish
the design on the page, for any plate, with no model: say which targets are reference genes
(or left out), which samples are which type, in which group and biological unit, and which two
groups are compared. Each of those is still a proposal in the session's hash-chained inbox,
made by the person (``made_by.kind == "person"``, which only ``actor="human"`` may propose) and
accepted by the person **in the same act**, with one reason, through
:meth:`~qpilot.core.proposals.ProposalStore.decide_together`: all of it is written, or nothing.

Nothing here weakens a rule:

* the engine checks every item exactly as it checks a rule's or a model's proposal
  (:func:`qpilot.qpcr.design_checks.check_proposal`), and the page shows each check before the
  person records anything (:func:`plan`); a contradicted item is recorded only when the person
  says so (``accept_contradicted``), with the reason;
* the hard bans hold (:func:`qpilot.qpcr.design_checks.hard_ban`): a declared or confirmed
  control is never given another role and never joins a group; an item they refuse is refused
  in words and nothing is written;
* a waiting proposal on the same item is settled by the same act: accepted when it says what
  the person set (so who proposed it stays on record), rejected (with the person's reason) when
  it says something else, so the inbox never holds a stale question the person already
  answered;
* blind: nothing here reads or returns a Cq, a quantity computed from one, or any result. The
  editor's view (:func:`state`) carries names, declared types, well positions, counts, and the
  design so far (groups included); the page never shows it next to a number.

The sample-sheet template (:func:`template_csv`) is a CSV pre-filled with the plate's sample and
target names (and whatever the design already says), in the columns the sheet reader and the
design rules recognise, so a lab can fill it in Excel and attach it (:func:`attach_sheet`).
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from qpilot.schemas_studio import (
    CONTROL_ROLES,
    Evidence,
    MadeBy,
    Proposal,
    ProposalCheck,
    ProposalOutcome,
)

if TYPE_CHECKING:
    from qpilot.studio_service import Studio

PERSON = MadeBy(kind="person")
TARGET_ROLE_KIND = "design.target_role"
ROLE_KIND = "design.well_role"
GROUP_KIND = "design.group"
UNIT_KIND = "design.bio_unit"
SERIES_KIND = "design.dilution_series"
COMPARISON_KIND = "design.comparison"
PURPOSE_KIND = "design.purpose"
#: The design items a person sets on the page (the comparison is written last, see set_design).
SET_KINDS = (
    PURPOSE_KIND,
    TARGET_ROLE_KIND,
    ROLE_KIND,
    SERIES_KIND,
    GROUP_KIND,
    UNIT_KIND,
    COMPARISON_KIND,
)
PURPOSES = ("compare", "quantify")
#: What a study can be for, in the person's words (value, label, what it means).
PURPOSE_WORDS: tuple[tuple[str, str, str], ...] = (
    (
        "compare",
        "Compare groups",
        "how a gene differs between groups of samples, normalised to reference genes",
    ),
    (
        "quantify",
        "Quantify samples",
        "how much of each target every sample holds, read from a standard curve (a viral "
        "load, copies of a construct, a library); no groups compared, no reference gene needed",
    ),
)
TARGET_ROLES = ("ref", "toi", "ignore")
#: Optional keys of a comparison a person sets: the further comparisons and their correction
#: (``qpilot.qpcr.designs.comparison_plan`` reads them; the engine checks them).
COMPARISON_EXTRAS = ("comparisons", "pattern", "control", "correction", "pair_by")
SAMPLE_ROLES = ("unkn", "std", "ntc", "nrt", "nac", "pos", "ntp", "opt")
MAX_ITEMS = 2_000  # one act: every sample of a 384-well plate several times over
NAME = re.compile(r"^[\w()\-. ]{1,64}\Z")  # the engine's safe names (qpilot.qpcr.curves)
NAME_WORDS = "letters, digits, spaces and _ - . ( ), at most 64 characters"
PERSON_REASON = "set by a person on the Design page, with the reason recorded"
Action = Literal["new", "accept", "keep", "unchanged", "refused"]

#: Sample types in the person's words (value, label, what it means), in the page's order.
SAMPLE_TYPE_WORDS: tuple[tuple[str, str, str], ...] = (
    ("unkn", "Study sample", "measured and compared; it can join a group"),
    ("std", "Standard", "a known quantity (copies or a relative dilution) on a standard curve"),
    ("ntc", "No-template control (NTC)", "water instead of template; should not amplify"),
    ("nrt", "No-RT control", "RNA without reverse transcription; checks for genomic DNA"),
    ("nac", "No-amplification control", "no polymerase or no primers; should not amplify"),
    ("pos", "Positive control", "a sample known to carry the target"),
    ("ntp", "No-target-present control", "a real sample known to lack the target"),
    (
        "opt",
        "Calibrator",
        "a calibrator measured on the plate (inter-run or optical); kept out of the groups, "
        "and qPilot does not correct between plates with it",
    ),
)
TARGET_ROLE_WORDS: tuple[tuple[str, str, str], ...] = (
    ("ref", "Reference gene", "the other genes are normalised to it (housekeeping gene)"),
    ("toi", "Gene of interest", "compared between the groups"),
    ("ignore", "Leave out", "not part of this study: none of its wells is used"),
)
TEMPLATE_TYPE = {  # sample type -> the word the sheet reader maps back to it
    "unkn": "Unknown",
    "std": "Standard",
    "ntc": "NTC",
    "nrt": "NRT",
    "nac": "NAC",
    "pos": "Positive control",
    "ntp": "NTP",
    "opt": "OPT",
}
TEMPLATE_ROLE = {"ref": "Reference", "toi": "Target", "ignore": "Ignore"}
TEMPLATE_HEADER = (
    "Sample",
    "Group",
    "Biological unit",
    "Sample type",
    "Quantity",
    "Plate wells",
    "",
    "Target",
    "Target role",
)


class DesignEditError(ValueError):
    """An edit that cannot be recorded (in words a scientist reads)."""


@dataclass(frozen=True)
class DesignItem:
    """One design item a person sets: a proposal kind, its subject and its payload."""

    kind: str
    subject: str
    payload: Mapping[str, Any]


@dataclass
class PlannedItem:
    """What recording one item would do, with the engine's check, before anything is written.

    ``action``: ``new`` (the person's own proposal, accepted), ``accept`` (a waiting proposal
    that says the same is accepted instead), ``keep`` (the design already says so; only waiting
    proposals that say otherwise are rejected), ``unchanged`` (already so, nothing waiting:
    nothing is written) or ``refused`` (``refusal`` says why; nothing is written).
    """

    item: DesignItem
    action: Action
    words: str
    check: ProposalCheck | None = None
    refusal: str | None = None
    accept_id: str | None = None
    rejects: list[str] = field(default_factory=list)
    proposal: Proposal | None = None
    also_accept: list[str] = field(default_factory=list)  # waiting proposals that agree with it


@dataclass
class DesignPlan:
    """The plan of one act on the inbox at ``head``."""

    head: str
    items: list[PlannedItem]

    def count(self, action: str) -> int:
        """How many items take this action."""
        return sum(1 for p in self.items if p.action == action)

    @property
    def refused(self) -> list[PlannedItem]:
        """The items that cannot be recorded."""
        return [p for p in self.items if p.action == "refused"]

    @property
    def contradicted(self) -> list[PlannedItem]:
        """The items the engine's check contradicts (recorded only when the person says so)."""
        return [
            p
            for p in self.items
            if p.action in ("new", "accept") and p.check and p.check.status == "contradicted"
        ]


@dataclass
class DesignSetResult:
    """What one act recorded: the new head and the outcome of every proposal it settled."""

    head: str
    recorded: int
    rejected: int
    unchanged: int
    outcomes: list[ProposalOutcome] = field(default_factory=list)


# ---- reading the design so far -----------------------------------------------------------------


def _payload_key(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)


def latest(accepted: Iterable[Proposal]) -> dict[tuple[str, str], dict[str, Any]]:
    """(kind, subject) -> the effective payload a person accepted last for it."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for p in accepted:
        if p.kind.startswith("design."):
            out[(p.kind, p.subject)] = p.effective_payload()
    return out


@dataclass
class DesignSoFar:
    """The design items a person accepted so far, per sample and per target (decision order)."""

    roles: dict[str, str] = field(default_factory=dict)
    quantities: dict[str, float] = field(default_factory=dict)
    series: dict[str, str] = field(default_factory=dict)  # sample -> the series it is in
    groups: dict[str, str | None] = field(default_factory=dict)
    units: dict[str, str | None] = field(default_factory=dict)
    target_roles: dict[str, str] = field(default_factory=dict)
    comparison: dict[str, str] | None = None
    preset: str | None = None
    #: What the study is for (``design.purpose``): ``compare`` (the default) or ``quantify``.
    purpose: str = "compare"
    #: A person's several comparisons (the accepted comparison's plan keys), when it has them.
    plan: dict[str, Any] | None = None
    #: Accepted pairings (``design.pair``): sample -> pair key, and the pairing's name.
    pairs: dict[str, str] = field(default_factory=dict)
    pair_by: str | None = None


def so_far(accepted: Iterable[Proposal]) -> DesignSoFar:
    """Read the accepted design proposals in the order a person decided them (later wins)."""
    out = DesignSoFar()
    for p in accepted:
        d = p.effective_payload()
        if p.kind == ROLE_KIND and "/" not in p.subject:
            out.roles[p.subject] = str(d.get("role"))
            if d.get("role") != "std":
                out.quantities.pop(p.subject, None)
        elif p.kind == SERIES_KIND and isinstance(d.get("samples"), Mapping):
            for sample, quantity in d["samples"].items():
                out.roles[str(sample)] = "std"
                out.series[str(sample)] = p.subject
                try:
                    out.quantities[str(sample)] = float(quantity)
                except (TypeError, ValueError):
                    pass
        elif p.kind == GROUP_KIND:
            out.groups[p.subject] = None if d.get("group") is None else str(d.get("group"))
        elif p.kind == UNIT_KIND:
            unit = d.get("biological_unit")
            out.units[p.subject] = None if unit is None else str(unit)
        elif p.kind == TARGET_ROLE_KIND:
            out.target_roles[p.subject] = str(d.get("role"))
        elif p.kind == COMPARISON_KIND:
            out.comparison = {"group_a": str(d.get("group_a")), "group_b": str(d.get("group_b"))}
            extras = {k: d[k] for k in COMPARISON_EXTRAS if d.get(k) is not None}
            out.plan = extras or None
        elif p.kind == "design.pair":
            if d.get("pair"):
                out.pairs[p.subject] = str(d.get("pair"))
                out.pair_by = str(d.get("by") or out.pair_by or "pair")
            else:
                out.pairs.pop(p.subject, None)
        elif p.kind == "design.preset":
            out.preset = str(d.get("preset"))
        elif p.kind == PURPOSE_KIND:
            out.purpose = "quantify" if d.get("purpose") == "quantify" else "compare"
    return out


def declared_role(facts: Any, sample: str) -> str:
    """The type the file declares for a sample (for every target), ``unkn`` when it says none."""
    for kind, target in facts.sample_types.get(sample) or ():
        if not target:
            return str(kind)
    return "unkn"


# ---- planning an act -----------------------------------------------------------------------------


def _sentence(text: str) -> str:
    text = str(text).strip()
    if text.lower().startswith("refused: "):
        text = text[len("refused: ") :]
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def _words(item: DesignItem) -> str:
    from qpilot.studio_state import describe

    probe = Proposal(
        study_id="0" * 12,
        kind=item.kind,  # type: ignore[arg-type]
        subject=item.subject,
        payload=dict(item.payload),
        made_by=PERSON,
    )
    return describe(probe)


def _known(facts: Any) -> tuple[set[str], set[str], set[str]]:
    samples = {s.sample for s in facts.summary.samples}
    targets = {t.target for t in facts.summary.targets}
    experiments = {r.experiment_id for r in facts.summary.runs}
    return samples, targets, experiments


def _name(value: Any, what: str) -> str | None:
    """A group or unit name as the engine keeps it, or a DesignEditError in words."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DesignEditError(f"a {what} needs a name (or none, to clear it)")
    text = value.strip()
    if not NAME.match(text):
        raise DesignEditError(f"a {what} name uses {NAME_WORDS}; “{text[:40]}” does not")
    return text


def normalise(item: DesignItem, facts: Any) -> DesignItem:
    """The item with a clean payload, or :class:`DesignEditError` saying what is wrong."""
    samples, targets, experiments = _known(facts)
    kind, subject, payload = item.kind, str(item.subject), dict(item.payload)
    if kind not in SET_KINDS:
        raise DesignEditError(f"{kind} is not a design item a person sets on this page")
    if kind == PURPOSE_KIND:
        purpose = payload.get("purpose")
        if purpose not in PURPOSES:
            raise DesignEditError("a study compares groups or quantifies samples")
        return DesignItem(kind, "purpose", {"purpose": purpose})
    if kind == TARGET_ROLE_KIND:
        if subject not in targets:
            raise DesignEditError(f"there is no target {subject!r} in this file")
        role = payload.get("role")
        if role not in TARGET_ROLES:
            raise DesignEditError("a target is a reference gene, a gene of interest, or left out")
        return DesignItem(kind, subject, {"role": role})
    if kind == COMPARISON_KIND:
        a = _name(payload.get("group_a"), "group")
        b = _name(payload.get("group_b"), "group")
        if a is None or b is None:
            raise DesignEditError("a comparison names two groups")
        if a == b:
            raise DesignEditError("a group cannot be compared with itself")
        label = payload.get("label") or ""
        out: dict[str, Any] = {"group_a": a, "group_b": b}
        if isinstance(label, str) and label.strip():
            out["label"] = label.strip()[:120]
        for key in COMPARISON_EXTRAS:  # several comparisons (agent compare's plan), as given
            if payload.get(key) is not None:
                out[key] = payload[key]
        return DesignItem(kind, "comparison", out)
    if kind == SERIES_KIND:
        name = _name(subject, "standard series")
        members = payload.get("samples")
        if not isinstance(members, Mapping) or not members:
            raise DesignEditError("a standard series lists its samples, each with its quantity")
        clean: dict[str, float] = {}
        for sample, quantity in members.items():
            if str(sample) not in samples:
                raise DesignEditError(f"there is no sample {sample!r} in this file")
            try:
                value = float(quantity)
            except (TypeError, ValueError):
                raise DesignEditError(
                    f"the quantity of standard {sample} is not a number"
                ) from None
            if not value > 0 or value != value or value == float("inf"):
                raise DesignEditError(
                    f"the quantity of standard {sample} must be a positive number (copies, or a "
                    "relative dilution such as 1, 0.1, 0.01)"
                )
            clean[str(sample)] = value
        experiment = payload.get("experiment_id")
        if experiment is None and len(experiments) == 1:
            experiment = next(iter(experiments))
        if experiment not in experiments:
            raise DesignEditError("say which experiment (plate set) the standards belong to")
        return DesignItem(kind, name or subject, {"experiment_id": experiment, "samples": clean})
    if subject not in samples:
        raise DesignEditError(f"there is no sample {subject!r} in this file")
    if kind == ROLE_KIND:
        role = payload.get("role")
        if role not in SAMPLE_ROLES:
            raise DesignEditError(f"{role!r} is not a sample type")
        return DesignItem(kind, subject, {"role": role})
    if kind == GROUP_KIND:
        return DesignItem(kind, subject, {"group": _name(payload.get("group"), "group")})
    unit = _name(payload.get("biological_unit"), "biological unit")
    return DesignItem(kind, subject, {"biological_unit": unit})


def _current(
    item: DesignItem, latest_values: Mapping[tuple[str, str], dict[str, Any]], facts: Any
) -> dict[str, Any] | None:
    """What the design says for this item now (a person's last decision, else the default).

    A target has no default: until a person says what it is, the editor shows it undecided, so
    choosing "gene of interest" is always recorded.
    """
    found = latest_values.get((item.kind, item.subject))
    if found is not None:
        return found
    if item.kind == PURPOSE_KIND:
        return {"purpose": "compare"}
    if item.kind == ROLE_KIND:
        return {"role": declared_role(facts, item.subject)}
    if item.kind == GROUP_KIND:
        return {"group": None}
    if item.kind == UNIT_KIND:
        return {"biological_unit": None}
    return None


def _same(a: Mapping[str, Any] | None, b: Mapping[str, Any]) -> bool:
    if a is None:
        return False
    keys = set(b)
    return _payload_key({k: a.get(k) for k in keys}) == _payload_key(dict(b))


def _ordered(items: Sequence[DesignItem]) -> list[DesignItem]:
    """One item per (kind, subject), the last given winning, in the order the kinds apply."""
    last: dict[tuple[str, str], DesignItem] = {}
    for item in items:
        last.pop((item.kind, str(item.subject)), None)
        last[(item.kind, str(item.subject))] = item
    rank = {kind: i for i, kind in enumerate(SET_KINDS)}
    return sorted(last.values(), key=lambda i: rank.get(i.kind, len(SET_KINDS)))


def _candidate(sid: str, item: DesignItem) -> Proposal:
    evidence_kind = "target" if item.kind == TARGET_ROLE_KIND else "sample"
    if item.kind in (SERIES_KIND,):
        refs = list(item.payload["samples"])[:50]
    elif item.kind in (COMPARISON_KIND, PURPOSE_KIND):
        refs = []
    else:
        refs = [item.subject]
    evidence = [Evidence(kind=evidence_kind, ref=r, note="set by a person") for r in refs]  # type: ignore[arg-type]
    return Proposal(
        study_id=sid,
        kind=item.kind,  # type: ignore[arg-type]
        subject=item.subject,
        payload=dict(item.payload),
        evidence=evidence,
        level="High",
        reasons=[PERSON_REASON],
        made_by=PERSON,
    )


def plan(studio: Studio, sid: str, items: Sequence[DesignItem]) -> DesignPlan:
    """What recording ``items`` would do now, with the engine's check of each; writes nothing.

    Items are checked against the design as a person accepted it, plus the items of this act
    that apply before them (a comparison sees the groups set in the same act).
    """
    from qpilot.qpcr.design_checks import check_with_facts, hard_ban, register_declared

    if len(items) > MAX_ITEMS:
        raise DesignEditError(f"one change sets at most {MAX_ITEMS:,} items")
    view = studio.store.proposals(sid).view()
    facts = studio.facts(sid)
    register_declared(sid, facts)  # what check_proposal does before each check, done once
    values = latest(view.accepted)
    waiting: dict[tuple[str, str], list[Proposal]] = defaultdict(list)
    for p in view.proposals:
        if p.status == "proposed" and p.kind in SET_KINDS:
            waiting[(p.kind, p.subject)].append(p)
    context = list(view.accepted)  # what the engine sees as accepted, item after item
    everyone = list(view.proposals)
    out: list[PlannedItem] = []
    for raw in _ordered(items):
        try:
            item = normalise(raw, facts)
        except DesignEditError as err:
            out.append(PlannedItem(raw, "refused", _safe_words(raw), refusal=_sentence(str(err))))
            continue
        words = _words(item)
        slot = waiting.get((item.kind, item.subject), [])
        agrees = next((p for p in slot if _same(p.effective_payload(), item.payload)), None)
        others = [p.id for p in slot if p is not agrees]
        also_accept: list[str] = []
        if item.kind == SERIES_KIND:  # the person's standards settle what waits on them
            members = set(item.payload["samples"])
            for (kind, subject), found in waiting.items():
                for p in found:
                    if p is agrees or p.id in others:
                        continue
                    d = p.effective_payload()
                    if kind == SERIES_KIND and members & set(d.get("samples") or {}):
                        others.append(p.id)
                    elif kind == ROLE_KIND and subject in members:
                        (also_accept if d.get("role") == "std" else others).append(p.id)
        if agrees is not None:
            refusal = hard_ban(agrees, [p for p in everyone if p.id != agrees.id])
            planned = PlannedItem(
                item,
                "accept",
                words,
                agrees.check,
                accept_id=agrees.id,
                rejects=others,
                also_accept=also_accept,
            )
            accepted_now = agrees.model_copy(update={"status": "accepted"})
        elif _same(_current(item, values, facts), item.payload):
            action: Action = "keep" if others or also_accept else "unchanged"
            out.append(PlannedItem(item, action, words, rejects=others, also_accept=also_accept))
            continue
        else:
            candidate = _candidate(sid, item)
            refusal = hard_ban(candidate, everyone)
            check = None
            if refusal is None:  # check_proposal's own path, on the facts read once
                check = check_with_facts(candidate, facts, accepted=context)
            planned = PlannedItem(
                item,
                "new",
                words,
                check,
                rejects=others,
                proposal=candidate.model_copy(),
                also_accept=also_accept,
            )
            accepted_now = candidate.model_copy(update={"status": "accepted"})
        if refusal:
            out.append(PlannedItem(item, "refused", words, refusal=_sentence(refusal)))
            continue
        out.append(planned)
        context.append(accepted_now)
        everyone.append(accepted_now)
    return DesignPlan(head=view.head, items=out)


def _safe_words(item: DesignItem) -> str:
    try:
        return _words(item)
    except Exception:  # a malformed item is named by its kind and subject
        return f"{item.kind} for {str(item.subject)[:60]}"


# ---- recording an act ----------------------------------------------------------------------------


def _inbox_with_checks(studio: Studio, sid: str, checks: Mapping[str, ProposalCheck]) -> Any:
    """The session's inbox, its engine check answering from this act's plan where it can.

    The plan's checks are the engine's own (the same function, on the same accepted design);
    re-using them makes the stored check the one the person saw, and spares a re-read of the
    chain for every item. A proposal the plan did not check is checked afresh.
    """
    from qpilot.core.proposals import ProposalStore
    from qpilot.core.store import plugin_checks
    from qpilot.qpcr.design_checks import check_proposal

    inbox = studio.store.proposals(sid)  # wires the hard bans' input resolver
    guard, _ = plugin_checks()
    rdml, sheet = studio.source(sid), studio.sheet(sid)

    def checker(proposal: Proposal) -> ProposalCheck:
        key = _check_key(proposal)
        if key in checks:
            return checks[key]
        accepted = ProposalStore.at(inbox.workspace, inbox.root).accepted()
        return check_proposal(
            proposal, studio.store, sid, rdml_path=rdml, accepted=accepted, sheet_path=sheet
        )

    return ProposalStore.at(inbox.workspace, inbox.root, guard, checker=checker)


def _check_key(proposal: Proposal) -> str:
    return f"{proposal.kind}\x00{proposal.subject}\x00{_payload_key(proposal.payload)}"


def refusal_words(planned: Sequence[PlannedItem], limit: int = 5) -> str:
    """The refused items of a plan, in one sentence."""
    shown = "; ".join(f"{p.words} ({p.refusal})" for p in planned[:limit])
    more = f" and {len(planned) - limit} more" if len(planned) > limit else ""
    return shown + more


def set_design(
    studio: Studio,
    sid: str,
    items: Sequence[DesignItem],
    actor: str,
    reason: str,
    *,
    expected_head: str | None = None,
    accept_contradicted: bool = False,
) -> DesignSetResult:
    """A person records design items: each made and accepted (or a waiting one settled) at once.

    Two writes at most, each all or nothing: every item but the comparison, then the comparison
    (its n-guard check needs the groups). Nothing is written when an item is refused, when the
    engine contradicts one and ``accept_contradicted`` is not set, or when the inbox changed
    since ``expected_head`` (``stale``).

    Raises:
        DesignEditError: Refused or contradicted items, in words (nothing written by this
            phase; when the comparison is refused the other items are already recorded, and the
            message says so).
    """
    from qpilot.core.proposals import ProposalError, clean_reason

    if type(actor) is not str or actor != "human":
        raise DesignEditError("only a person sets the design on the page")
    try:
        reason = clean_reason(reason, required=True)
    except ProposalError as err:
        raise DesignEditError(str(err)) from err
    phases = [
        [i for i in items if i.kind != COMPARISON_KIND],
        [i for i in items if i.kind == COMPARISON_KIND],
    ]
    head = expected_head
    recorded = rejected = unchanged = 0
    outcomes: list[ProposalOutcome] = []
    for index, phase in enumerate(phases):
        if not phase:
            continue
        done_before = " The other changes are already recorded." if index and outcomes else ""
        planned = plan(studio, sid, phase)
        if planned.refused:
            raise DesignEditError(
                "Nothing was recorded: "
                + refusal_words(planned.refused)
                + ". Remove these changes, then record the others."
                + done_before
            )
        if planned.contradicted and not accept_contradicted:
            words = "; ".join(p.words for p in planned.contradicted[:5])
            raise DesignEditError(
                "Nothing was recorded: the engine's check contradicts "
                f"{len(planned.contradicted)} of these changes ({words}). Read why, then record "
                "them anyway with your reason, or change them." + done_before
            )
        unchanged += planned.count("unchanged")
        new = [(p.proposal, "accept") for p in planned.items if p.action == "new" and p.proposal]
        pending: list[tuple[str, str]] = []
        for p in planned.items:
            if p.action == "accept" and p.accept_id:
                pending.append((p.accept_id, "accept"))
            pending.extend((pid, "accept") for pid in p.also_accept)
            pending.extend((pid, "reject") for pid in p.rejects)
        if not new and not pending:
            continue
        checks = {
            _check_key(p.proposal): p.check
            for p in planned.items
            if p.action == "new" and p.proposal and p.check
        }
        inbox = _inbox_with_checks(studio, sid, checks)
        result = inbox.decide_together(
            new, pending, "human", reason, proposer="human", expected_head=head
        )
        if result and result[0].status in ("stale", "refused"):
            return DesignSetResult(
                head=result[0].head,
                recorded=recorded,
                rejected=rejected,
                unchanged=unchanged,
                outcomes=[*outcomes, result[0]],
            )
        outcomes.extend(result)
        recorded += sum(1 for o in result if o.status in ("accepted", "edited"))
        rejected += sum(1 for o in result if o.status == "rejected")
        head = result[-1].head if result else head
    return DesignSetResult(
        head=head or studio.head(sid),
        recorded=recorded,
        rejected=rejected,
        unchanged=unchanged,
        outcomes=outcomes,
    )


# ---- the editor's view ---------------------------------------------------------------------------


@dataclass
class SampleRow:
    """One sample as the editor shows it (no number but counts)."""

    sample: str
    text_id: str | None
    declared_type: str
    n_wells: int
    wells: list[str]
    targets: list[str]
    experiments: list[str]
    role: str
    quantity: float | None
    series: str | None
    group: str | None
    unit: str | None
    locked: str | None  # why the type cannot change (a declared control)
    waiting: list[str]  # kinds of the proposals about it that wait for a decision


@dataclass
class TargetRow:
    """One target as the editor shows it."""

    target: str
    text_id: str | None
    declared_type: str
    n_wells: int
    runs: list[str]
    role: str | None  # what a person decided (None: not decided yet)
    waiting: list[str]


@dataclass
class Need:
    """One thing the design still needs, and the part of the page that gives it."""

    code: str
    words: str
    where: Literal["targets", "samples", "comparison", "inbox", "engine"]


@dataclass
class EditorState:
    """The editor's whole view at one head of the inbox."""

    head: str
    samples: list[SampleRow]
    targets: list[TargetRow]
    groups: dict[str, int]  # group -> study samples in it
    units: dict[str, int]  # unit -> samples in it
    comparison: dict[str, str] | None
    preset: str | None
    experiments: list[str]
    needs: list[Need]
    waiting: int
    plan: dict[str, Any] | None = None
    pair_by: str | None = None
    n_paired: int = 0
    #: What the study is for: ``compare`` (groups; the default) or ``quantify`` (samples).
    purpose: str = "compare"
    #: Standard samples on the plate and those with a quantity (names and types only: blind).
    n_standards: int = 0
    n_standards_with_quantity: int = 0


def state(studio: Studio, sid: str) -> EditorState:
    """Everything the editor shows, read at one head of the inbox.

    Names, declared types, wells, the design so far, what is still missing. Blind: no Cq and no
    result.
    """
    view = studio.store.proposals(sid).view()
    facts = studio.facts(sid)
    summary = facts.summary
    design = so_far(view.accepted)
    waiting_by_subject: dict[str, list[str]] = defaultdict(list)
    n_waiting = 0
    for p in view.proposals:
        if p.status != "proposed" or not p.kind.startswith("design."):
            continue
        n_waiting += 1
        if p.kind == SERIES_KIND and isinstance(p.payload.get("samples"), Mapping):
            for s in p.payload["samples"]:
                waiting_by_subject[str(s)].append(p.kind)
        else:
            waiting_by_subject[p.subject].append(p.kind)
    wells = facts.wells
    keys: dict[str, list[str]] = defaultdict(list)
    for run_id, well, sample in (
        wells[["run_id", "well", "sample"]].drop_duplicates().itertuples(index=False, name=None)
    ):
        keys[str(sample)].append(f"{run_id}/{well}")
    samples = []
    for s in summary.samples:
        declared = declared_role(facts, s.sample)
        role = design.roles.get(s.sample, declared)
        locked = None
        if declared in CONTROL_ROLES or role in CONTROL_ROLES:
            locked = (
                "a control (no template, no RT or no amplification) in the file or by a "
                "decision; a control keeps its type and joins no group"
            )
        samples.append(
            SampleRow(
                sample=s.sample,
                text_id=s.text_id,
                declared_type=s.declared_type,
                n_wells=s.n_wells,
                wells=keys.get(s.sample, [])[:400],
                targets=list(s.targets),
                experiments=list(s.experiments),
                role=role,
                quantity=design.quantities.get(s.sample) if role == "std" else None,
                series=design.series.get(s.sample) if role == "std" else None,
                group=design.groups.get(s.sample),
                unit=design.units.get(s.sample),
                locked=locked,
                waiting=sorted(set(waiting_by_subject.get(s.sample, []))),
            )
        )
    runs_of: dict[str, set[str]] = defaultdict(set)
    for target, run_id in (
        wells[["target", "run_id"]].drop_duplicates().itertuples(index=False, name=None)
    ):
        runs_of[str(target)].add(str(run_id))
    targets = [
        TargetRow(
            target=t.target,
            text_id=t.text_id,
            declared_type=t.declared_type,
            n_wells=t.n_wells,
            runs=sorted(runs_of.get(t.target, ())),
            role=design.target_roles.get(t.target),
            waiting=sorted(set(waiting_by_subject.get(t.target, []))),
        )
        for t in summary.targets
    ]
    studied = {r.sample for r in samples if r.role == "unkn"}
    groups = Counter(g for s, g in design.groups.items() if g is not None and s in studied)
    units = Counter(u for u in design.units.values() if u is not None)
    needs = _needs(studio, sid, view, design, targets, groups, n_waiting)
    standards = [r for r in samples if r.role == "std"]
    declared_q = {s for s, entries in facts.sample_quantities.items() if entries}
    return EditorState(
        head=view.head,
        samples=samples,
        targets=targets,
        groups=dict(sorted(groups.items())),
        units=dict(sorted(units.items())),
        comparison=design.comparison,
        preset=design.preset,
        experiments=sorted({r.experiment_id for r in summary.runs}),
        needs=needs,
        waiting=n_waiting,
        plan=design.plan,
        pair_by=design.pair_by if design.pairs else None,
        n_paired=sum(1 for s in design.pairs if s in studied),
        purpose=design.purpose,
        n_standards=len(standards),
        n_standards_with_quantity=sum(
            1 for r in standards if r.quantity is not None or r.sample in declared_q
        ),
    )


def _needs(
    studio: Studio,
    sid: str,
    view: Any,
    design: DesignSoFar,
    targets: Sequence[TargetRow],
    groups: Mapping[str, int],
    n_waiting: int,
) -> list[Need]:
    """What the design still needs, each with the control on the page that gives it.

    A study that quantifies samples needs no reference gene, no groups and no comparison
    (said once, as not applicable); it needs standards with quantities instead.
    """
    if design.purpose == "quantify":
        needs: list[Need] = []
    elif design.preset is not None:
        needs = []
    else:
        roles = {t.target: t.role for t in targets}
        needs = []
        if not any(r == "ref" for r in roles.values()):
            needs.append(
                Need(
                    "reference",
                    "No reference gene yet: mark at least one target as a reference gene "
                    "(housekeeping gene)",
                    "targets",
                )
            )
        used = [t for t, r in roles.items() if r != "ignore"]
        if used and all(roles.get(t) == "ref" for t in used):
            needs.append(
                Need(
                    "gene",
                    "No gene of interest: every target in use is a reference gene; mark the "
                    "genes you compare as genes of interest",
                    "targets",
                )
            )
        if len([g for g, n in groups.items() if n]) < 2:
            needs.append(
                Need(
                    "groups",
                    "Fewer than two groups: put the study samples in their groups (select "
                    "wells or samples, or paste a sample-to-group list)",
                    "samples",
                )
            )
        elif design.comparison is None:
            needs.append(
                Need(
                    "comparison",
                    "No comparison yet: choose which group is compared with which (the "
                    "reference group is the baseline)",
                    "comparison",
                )
            )
    if n_waiting:
        needs.append(
            Need(
                "waiting",
                f"{n_waiting} proposal{'s' * (n_waiting != 1)} still wait for a decision: "
                "decide them in the inbox, or set the item yourself (your choice settles a "
                "waiting proposal on the same item)",
                "inbox",
            )
        )
    assembly = studio.assemble(sid, view.accepted)
    for blocker in assembly.blockers:
        if blocker.startswith(("no comparison yet", "no reference genes yet")):
            continue  # said above, with the control that gives it
        if blocker.startswith(STANDARDS_BLOCKERS):
            needs.append(Need("standards", _sentence(blocker), "samples"))
            continue
        needs.append(Need("engine", _sentence(blocker), "engine"))
    return needs


#: The blockers of a quantification design (``qpcr.quantify_study.standards_needed``).
STANDARDS_BLOCKERS = ("no standards yet", "no standards with a quantity yet", "the standards are")


# ---- the sample-sheet template and attaching a sheet -------------------------------------------


def _cell(text: Any) -> str:
    """A CSV cell that a spreadsheet opens as text, never as a formula."""
    value = "" if text is None else str(text)
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def template_csv(studio: Studio, sid: str) -> str:
    """A sample sheet pre-filled with this plate's samples and targets, in recognised columns.

    One row per sample (its name as in the file, the design so far, its wells), and beside it
    the list of targets with their roles. The sheet reader takes the samples from the
    ``Sample`` column and the target roles from the ``Target``/``Target role`` columns, rows
    without a sample included.
    """
    current = state(studio, sid)
    quotes = {q.text_id: q.value for q in studio.quarantined(sid)}
    samples = sorted(current.samples, key=lambda r: _well_order(r.wells))
    targets = current.targets
    several_runs = len({w.split("/", 1)[0] for r in samples for w in r.wells}) > 1
    rows: list[list[str]] = [list(TEMPLATE_HEADER)]
    for i in range(max(len(samples), len(targets))):
        row = [""] * len(TEMPLATE_HEADER)
        if i < len(samples):
            s = samples[i]
            wells = [w if several_runs else w.split("/", 1)[1] for w in s.wells[:24]]
            row[0] = quotes.get(s.text_id or "", s.sample)
            row[1] = s.group or ""
            row[2] = s.unit or ""
            row[3] = TEMPLATE_TYPE.get(s.role, "")
            row[4] = f"{s.quantity:g}" if s.quantity is not None else ""
            row[5] = " ".join(wells) + (" …" if len(s.wells) > 24 else "")
        if i < len(targets):
            t = targets[i]
            row[7] = quotes.get(t.text_id or "", t.target)
            row[8] = TEMPLATE_ROLE.get(t.role or "", "")
        rows.append([_cell(v) for v in row])
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    return buffer.getvalue()


def _well_order(wells: Sequence[str]) -> tuple[str, int, int]:
    if not wells:
        return ("~", 0, 0)
    run, _, well = wells[0].partition("/")
    match = re.match(r"^([A-Z]+)(\d+)$", well)
    if not match:
        return (run, 0, 0)
    letters, digits = match.groups()
    row = 0
    for ch in letters:
        row = row * 26 + ord(ch) - 64
    return (run, row, int(digits))  # in reading order, as the plate map shows it


def attach_sheet(studio: Studio, sid: str, sheet_path: str | Path, actor: str) -> str:
    """Bind a sample sheet to this session (a person's open of the same file with the sheet).

    The input file stays as it was; the sheet's cells are quarantined like any text; nothing
    is proposed or decided here (the caller asks the rules to propose again).

    Raises:
        DesignEditError: Not a person, or the session's own file is gone.
        SheetError: The sheet cannot be read (size caps, not a spreadsheet).
    """
    if type(actor) is not str or actor != "human":
        raise DesignEditError("only a person attaches a sample sheet")
    source = studio.source(sid)
    opened = studio.open(source, sheet_path, actor="human")
    if opened != sid:  # the same file always opens the same session
        raise DesignEditError("the sheet was attached to another file's session")
    return opened


__all__ = [
    "PERSON",
    "SAMPLE_TYPE_WORDS",
    "SET_KINDS",
    "TARGET_ROLE_WORDS",
    "DesignEditError",
    "DesignItem",
    "DesignPlan",
    "DesignSetResult",
    "EditorState",
    "Need",
    "PlannedItem",
    "SampleRow",
    "TargetRow",
    "attach_sheet",
    "latest",
    "normalise",
    "plan",
    "set_design",
    "so_far",
    "state",
    "template_csv",
]
