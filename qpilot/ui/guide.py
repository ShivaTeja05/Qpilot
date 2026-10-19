"""The "Next step" box: in plain words, what a person does next on every screen of Studio.

A pure function of what the page already read from the Studio service (the stages, the shown
stage's inbox, whether results are visible, the Decision Cards still open). It names buttons by
their exact labels, says what each move does before it is made, and never shows a result: in the
blind stages it reads only counts of proposals by their engine check.

Every string here is fixed copy or a plain count; stage blockers come from the service and are
escaped.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from qpilot.app_state import esc

STAGE_NAMES = {
    "design": "Design (blind)",
    "curves": "Curves (blind)",
    "choices": "Choices",
    "prism": "Prism draft",
    "roundtrip": "Round trip",
}
AI_MAKERS = ("model", "agent")
WHERE_THINGS_ARE = (
    "Results appear on the right only after the Design and the Curves stages are confirmed, so "
    "both are decided on the evidence, never on the answer they give."
)


@dataclass(frozen=True)
class InboxCounts:
    """What waits in the shown stage, counted by the engine's check (no result in it)."""

    pending: int = 0
    contradicted: int = 0
    contradicted_ai: int = 0
    cannot_check: int = 0
    consistent: int = 0
    preset: bool = False  # a built-in design is among the waiting proposals
    decided: int = 0
    confirm_waiting: bool = False  # "Confirm this stage…" was pressed; "Yes, confirm" waits


def count_inbox(
    pending: Iterable[Any], decided: Sequence[Any] = (), confirms: Sequence[Any] = ()
) -> InboxCounts:
    """Count the waiting proposals of a stage (``stage.confirm`` proposals go in ``confirms``)."""
    items = [p for p in pending if p.kind != "stage.confirm"]
    status = [p.check.status for p in items]
    return InboxCounts(
        pending=len(items),
        contradicted=status.count("contradicted"),
        contradicted_ai=sum(
            1 for p in items if p.check.status == "contradicted" and p.made_by.kind in AI_MAKERS
        ),
        cannot_check=status.count("cannot_check"),
        consistent=status.count("consistent"),
        preset=any(p.kind == "design.preset" for p in items),
        decided=len(decided),
        confirm_waiting=bool(confirms),
    )


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _stage_dict(stage: Any) -> dict[str, Any]:
    return stage.as_dict() if hasattr(stage, "as_dict") else dict(stage)


def _box(title: str, steps: Sequence[str], note: str = "", tone: str = "next") -> str:
    """The box: a heading, the moves in order (already escaped HTML), an optional note."""
    items = "".join(f"<li>{s}</li>" for s in steps)
    body = f'<ol class="qs-steps">{items}</ol>' if len(steps) > 1 else f"<p>{steps[0]}</p>"
    extra = f'<p class="qs-hint">{note}</p>' if note else ""
    return (
        f'<section class="qs-guide {tone}" aria-label="Next step">'
        f"<h4>{title}</h4>{body}{extra}</section>"
    )


def _b(label: str) -> str:
    """A button's label as the page shows it."""
    return f"<b>{esc(label)}</b>"


def _inbox_moves(counts: InboxCounts, stage: str) -> list[str]:
    """The moves that settle a stage's waiting proposals, most important first."""
    moves = []
    if counts.preset:
        moves.append(
            f"Start with the built-in design (the first card): accepting it sets the groups, the "
            f"comparison and the reference genes in one step. {_b('Accept')} it, or "
            f"{_b('Reject')} it with a reason if this is not that study."
        )
    if counts.contradicted:
        rules = counts.contradicted - counts.contradicted_ai
        text = (
            f"{_plural(counts.contradicted, 'proposal')} the engine's check contradicts (red "
            "edge): read why, then reject with a reason, or accept with a reason if you know "
            "better."
        )
        if counts.contradicted_ai:
            text += (
                f" The {_plural(counts.contradicted_ai, 'one')} made by a model or an agent can "
                f"be rejected together with {_b('Reject all contradicted AI calls…')}"
                + (f"; the other {rules} one by one." if rules else ".")
            )
        moves.append(text)
    if counts.cannot_check:
        moves.append(
            f"{_plural(counts.cannot_check, 'proposal')} no engine check applies to (grey edge): "
            "decide each on its evidence."
        )
    if counts.consistent:
        moves.append(
            f"{_plural(counts.consistent, 'proposal')} the engine finds nothing against (green "
            f"edge): {_b('Accept all consistent…')} lists exactly which, and accepts them only "
            "when you press the button under the list."
        )
    moves.append(
        f"When nothing waits, press {_b('Confirm this stage…')}: it shows what you are "
        "confirming before anything is recorded."
    )
    return moves


def next_step_html(
    *,
    opened: bool,
    stages: Sequence[Any] = (),
    stage: str | None = None,
    counts: InboxCounts | None = None,
    results_visible: bool = False,
    open_cards: int | None = None,
    project: str | None = None,
) -> str:
    """The "Next step" box for what the page shows now (escaped HTML).

    Args:
        opened: A file is open in this tab.
        stages: The service's stage statuses (``StageStatus`` or their ``as_dict()``).
        stage: The stage whose inbox the page shows.
        counts: That inbox, counted (:func:`count_inbox`).
        results_visible: Both blind stages are confirmed (the right-hand pane shows results).
        open_cards: Decision Cards still waiting for a person (once results are visible).
        project: The Prism project of this analysis: ``None`` (none drafted), ``"waiting"`` or
            ``"accepted"``.
    """
    if not opened:
        return _box(
            "Start here",
            [
                f"Drop your instrument's RDML export in the first box (and, if you have one, a "
                f"sample sheet), then press {_b('Open')}. Leave the box empty and press "
                f"{_b('Open')} to look at the public demo study first.",
            ],
            "Opening only reads the file: nothing is analysed and nothing is proposed until "
            "you press a button. Research use only.",
            tone="start",
        )
    counts = counts or InboxCounts()
    by = {str(s["stage"]): s for s in map(_stage_dict, stages)}
    status = by.get(stage or "", {})
    name = STAGE_NAMES.get(stage or "", stage or "")
    current = next((n for n, s in by.items() if s.get("open") and not s.get("confirmed")), None)
    if status.get("confirmed") and stage != "roundtrip":
        later = (
            f" The work is now in the {_b(STAGE_NAMES.get(current, current))} stage: pick it above."
            if current and current != stage
            else ""
        )
        return _box(
            f"The {esc(name)} stage is confirmed",
            [f"You are looking back at what was decided.{later}"],
            tone="done",
        )
    if counts.confirm_waiting:
        return _box(
            f"Confirm the {esc(name)} stage?",
            [
                f"Check the list below, then press {_b(f'Yes, confirm the {name} stage')}; or "
                f"{_b('Not yet')}, with a reason, to keep the stage open."
            ],
        )
    blockers = [esc(b) for b in status.get("blockers") or [] if stage != "roundtrip"]
    if stage in ("design", "curves"):
        return _blind_step(stage, counts, blockers)
    if stage == "choices":
        return _choices_step(counts, results_visible, open_cards)
    if stage == "prism":
        return _prism_step(counts, project)
    return _roundtrip_step(counts, by)


def _blind_step(stage: str, counts: InboxCounts, blockers: Sequence[str]) -> str:
    if counts.pending == 0 and counts.decided == 0:
        if stage == "design":
            return _box(
                "Next: propose the design",
                [
                    f"Press {_b('Propose the design')}. qPilot's rules (and a language model, "
                    "when one is set up) read the file's sample names, its sample types and your "
                    "sample sheet, and propose each sample's role, the groups, the biological "
                    "units and the reference genes. Nothing is applied until you accept it.",
                ],
                WHERE_THINGS_ARE,
            )
        return _box(
            "Next: check the curves",
            [
                f"Press {_b('Check the curves')}. LinRegPCR and the Curve Judge read every "
                "amplification curve; where they disagree on a well that could change a "
                "conclusion, you get one card for that well.",
            ],
            "On a large file this takes a while; the page says when it is done. "
            + WHERE_THINGS_ARE,
        )
    if counts.pending:
        return _box(
            f"{_plural(counts.pending, 'proposal')} wait for you",
            _inbox_moves(counts, stage),
            WHERE_THINGS_ARE,
        )
    steps = [
        f"Every proposal of this stage is decided. Press {_b('Confirm this stage…')}: it shows "
        "what you are confirming before anything is recorded."
    ]
    if blockers:
        steps.append("Before it can be confirmed: " + "; ".join(blockers) + ".")
    return _box("Next: confirm this stage", steps)


def _choices_step(counts: InboxCounts, results_visible: bool, open_cards: int | None) -> str:
    if not results_visible:
        return _box(
            "Results are hidden again",
            ["A blind stage is open again: confirm the Design and the Curves stages first."],
        )
    if open_cards:
        return _box(
            f"{_plural(open_cards, 'Decision Card')} wait for you (on the right)",
            [
                "The results are on the right. Each Decision Card is a choice that can change a "
                "conclusion (which reference genes, which cut-off, …): read its options table, "
                f"pick {_b('Your choice')}, type a reason, press {_b('Decide')}.",
                f"Then press {_b('Confirm this stage…')} here.",
            ],
            "Cards you leave open are exported at their recommended option, and the record says "
            "so.",
        )
    return _box(
        "Next: confirm the Choices",
        [
            f"Every Decision Card is decided. Press {_b('Confirm this stage…')}: it shows the "
            "decisions you are confirming first."
        ],
    )


def _prism_step(counts: InboxCounts, project: str | None) -> str:
    if counts.pending:
        return _box(
            "Check the Prism project",
            [
                f"The drafted Prism project is the card below: check the tables, the test, the "
                f"graph and the caption, then {_b('Accept')} it (or edit it first)."
            ],
        )
    if project == "accepted":
        return _box(
            "Next: send it to Prism",
            [
                f"Press {_b('Send to Prism')} on the right. qPilot writes the bundle (one table "
                "per gene, the scripts and where every number came from) and starts Prism when "
                "it is installed; otherwise it offers the bundle as a zip."
            ],
        )
    return _box(
        "Next: draft the Prism project",
        [
            f"Press {_b('Draft the Prism project')} on the right, then accept it here.",
        ],
        "Not using Prism? The analysis and its decisions are complete once the Choices stage "
        "is confirmed.",
    )


def _roundtrip_step(counts: InboxCounts, by: Mapping[str, Mapping[str, Any]]) -> str:
    if counts.pending:
        return _box(
            f"{_plural(counts.pending, 'question')} from Prism",
            [
                "Each card is a change made in Prism since the export, with what it changes. "
                f"An exclusion needs a reason before {_b('Accept: exclude this value')}; a "
                "changed value asks whether to restore qPilot's value."
            ],
        )
    if not by.get("prism", {}).get("confirmed"):
        return _box("Nothing to read back yet", ["Send the project to Prism first."])
    return _box(
        "After you edit in Prism",
        [
            "Run send_back.pzc from the bundle in Prism: it writes every table to the bundle's "
            f"sent_back folder. Then press {_b('Read what changed in Prism')} on the right.",
        ],
    )


__all__ = ["InboxCounts", "count_inbox", "next_step_html"]
