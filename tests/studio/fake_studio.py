"""A stand-in for :class:`qpilot.studio_service.Studio` that records every call and its actor.

The dashboard tests drive the page's handlers against this fake: it answers like the service
(the same method names, signatures and return types; ``study`` and ``preview_prism`` refuse
while the blind stages are open), plants hostile text in everything a file, a sheet, a model or
an agent could control, and refuses any method or store attribute the service does not have.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from qpilot.schemas import DecisionCard, DecisionOutcome, StudyResult
from qpilot.schemas_studio import (
    Evidence,
    InspectRun,
    InspectSample,
    InspectSummary,
    InspectTarget,
    MadeBy,
    Proposal,
    ProposalCheck,
    ProposalOutcome,
    QuarantineEntry,
    SheetCell,
    text_id_for,
)
from qpilot.studio_service import STAGES, StageStatus, StudioError

EVIL = '<script>alert("x")</script><img src=x onerror=alert(1)>'
SID = "5e55105e5510"
STUDY = "study1"
TEXT_ID = text_id_for("rdml:sample.id", EVIL)
SHEET_ID = text_id_for("sheet:samples.xlsx!Sheet1!B2", EVIL)
WELL = f"run{EVIL}/A1"

#: Methods that decide (a person only) and methods that propose or open (a click only).
DECIDING = frozenset(
    {
        "accept",
        "edit",
        "reject",
        "accept_all_consistent",
        "reject_many",
        "decide",
        "send_to_prism",
        "launch_prism",
    }
)
PROPOSING = frozenset(
    {
        "open",
        "propose_design",
        "propose_comparison",
        "propose_curves",
        "propose_confirm",
        "propose_prism",
        "round_trip",
    }
)


def _proposal(pid: str, kind: str, subject: str, payload: dict, **update: Any) -> Proposal:
    base = Proposal(
        id=pid,
        study_id=SID,
        kind=kind,
        subject=subject,
        payload=payload,
        evidence=[
            Evidence(kind="text", ref=TEXT_ID, note=EVIL),
            Evidence(kind="cell", ref="samples.xlsx!Sheet1!B2", note=EVIL),
            Evidence(kind="sample", ref=EVIL, note=EVIL),
        ],
        check=ProposalCheck(
            status="consistent",
            rule_ids=[f"D-{EVIL}"],
            details={
                "r2": 0.98,
                "label": EVIL,
                "wells": [EVIL, "A2"],
                "checks": {
                    "D-REP": {
                        "status": "consistent",
                        "note": EVIL,
                        "details": {"over_tolerance": [{"sample": EVIL}]},
                    }
                },
            },
            note=EVIL,
        ),
        level="Low",
        reasons=[EVIL],
        made_by=MadeBy(kind="rule"),
        created_at="2026-10-17T00:00:00Z",
    )
    return base.model_copy(update=update)


def proposals() -> list[Proposal]:
    """One inbox with a proposal of every kind the dashboard shows, all carrying hostile text."""
    contradicted = ProposalCheck(
        status="contradicted", rule_ids=["D-CURVE"], note=EVIL, details={"note": EVIL}
    )
    model = MadeBy(kind="model", provider="openai_compatible", model=EVIL, prompt_sha256="f" * 64)
    judge = MadeBy(kind="model", provider="qpilot-curve-judge", model=EVIL)
    agent = MadeBy(kind="agent", agent=EVIL)
    consequence = {
        "gene": "ODC1",
        "biological_unit": EVIL,
        "fc_before": 3.59,
        "fc_after": 3.319,
        "p_before": 2.3e-8,
        "p_after": 2.1e-8,
        "conclusion_before": "up",
        "conclusion_after": "up",
        "n_units_before": [60, 287],
        "n_units_after": [59, 287],
        "n_conclusions_changed": 1,
        "n_genes": 58,
        "changed_genes": [EVIL],
    }
    return [
        _proposal(
            "p_d0",
            "design.preset",
            "design",
            {"preset": EVIL},
            status="accepted",
            decided_by="human",
            reason=EVIL,
        ),
        _proposal("p_d1", "design.group", EVIL, {"group": EVIL}, alternatives=[{"group": EVIL}]),
        _proposal(
            "p_d2",
            "design.well_role",
            "S2",
            {"role": "std"},
            check=contradicted,
            made_by=model,
            alternatives=[{"role": "unkn"}],
        ),
        _proposal(
            "p_d3",
            "design.target_role",
            "GAPDH",
            {"role": "ref"},
            made_by=agent,
            check=ProposalCheck(status="cannot_check", note=EVIL),
        ),
        _proposal(
            "p_d4",
            "design.dilution_series",
            EVIL,
            {"experiment_id": EVIL, "samples": {EVIL: 1.0, "S9": 10.0}},
        ),
        _proposal(
            "p_d5",
            "stage.confirm",
            "design",
            {"stage": "design", "design_hash": "ab" * 32, "covers": ["p_d0"]},
        ),
        _proposal(
            "p_c1",
            "curve.well_call",
            WELL,
            {"amplified": True},
            check=contradicted,
            made_by=judge,
            consequence={"matters": True},
            evidence=[
                Evidence(kind="well", ref=WELL, note=EVIL),
                Evidence(kind="curve", ref=WELL, note=EVIL),
            ],
        ),
        _proposal("p_c2", "curve.call_rule", "amp_call", {"rule": "linregpcr"}),
        _proposal(
            "p_p0",
            "prism.project",
            "prism",
            {"template_id": "two_groups_log2", "genes": ["ODC1"], "study_id": STUDY},
            status="accepted",
            decided_by="human",
        ),
        _proposal(
            "p_p1",
            "prism.project",
            "prism",
            {"template_id": "two_groups_log2", "genes": ["ODC1", EVIL], "study_id": STUDY},
        ),
        _proposal(
            "p_r1",
            "prism.exclusion_reason",
            f"ODC1/{EVIL}",
            {"gene": "ODC1", "sample": EVIL, "action": "exclude", "question": EVIL, "well_rep": 0},
            check=ProposalCheck(status="cannot_check", note=EVIL, details={"x": EVIL}),
            consequence=consequence,
        ),
        _proposal(
            "p_r2",
            "prism.value_edit",
            f"ODC1/{EVIL}",
            {"gene": "ODC1", "sample": EVIL, "action": "restore", "question": EVIL},
            check=contradicted,
            consequence={"exported": 1.5, "returned": 9.0},
        ),
    ]


def _stage_of(p: Proposal) -> str:
    if p.kind == "stage.confirm":
        return p.subject
    if p.kind.startswith("design."):
        return "design"
    if p.kind.startswith("curve."):
        return "curves"
    return "prism" if p.kind == "prism.project" else "roundtrip"


class FakeStore:
    """The store as the dashboard may use it: reads of an analysed study, nothing else."""

    def __init__(self, result: StudyResult, cards: list[DecisionCard], root: Path, calls: list):
        self.root = root
        self._result, self._cards, self._calls = result, cards, calls

    def get(self, study_id: str) -> StudyResult:
        self._calls.append(("store.get", None))
        return self._result

    def snapshot(self, study_id: str):
        self._calls.append(("store.snapshot", None))
        return "dhead", list(self._cards), []

    def __getattr__(self, name: str):
        raise AttributeError(f"the dashboard may not use store.{name}")


class FakeStudio:
    """Answers like :class:`Studio`; ``phase`` is the first stage not yet confirmed."""

    def __init__(
        self, result: StudyResult, cards: list[DecisionCard], root: Path, phase: str = "design"
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.phase = phase
        self.root = Path(root)
        self.store = FakeStore(result, cards, self.root / "studies", self.calls)
        self._proposals = proposals()
        self._cards = cards

    def __getattr__(self, name: str):
        raise AttributeError(f"Studio has no method {name!r} the dashboard could use")

    def _log(self, name: str, actor: Any = None) -> None:
        self.calls.append((name, actor))

    @property
    def visible(self) -> bool:
        return STAGES.index(self.phase) > STAGES.index("curves")

    # ---- reading ----

    def model_status(self) -> dict[str, Any]:
        self._log("model_status")
        return {
            "provider": "openai_compatible",
            "model": EVIL,
            "available": True,
            "local": False,
            "sample_names": EVIL,
        }

    def stages(self, session_id: str) -> list[StageStatus]:
        self._log("stages")
        at = STAGES.index(self.phase)
        out = []
        for index, stage in enumerate(STAGES):
            waiting = sum(
                1 for p in self._proposals if p.status == "proposed" and _stage_of(p) == stage
            )
            out.append(StageStatus(stage, index <= at, index < at, waiting, [EVIL]))
        return out

    def results_visible(self, session_id: str) -> bool:
        self._log("results_visible")
        return self.visible

    def inbox(self, session_id: str, stage: str | None = None, status: str | None = None):
        self._log("inbox")
        return [
            p
            for p in self._proposals
            if (stage is None or _stage_of(p) == stage) and (status is None or p.status == status)
        ]

    def head(self, session_id: str) -> str:
        self._log("head")
        return "phead"

    def quarantined(self, session_id: str) -> list[QuarantineEntry]:
        self._log("quarantined")
        return [
            QuarantineEntry(
                text_id=TEXT_ID, origin=f"rdml:{EVIL}", value=EVIL, flags=["instruction_like"]
            ),
            QuarantineEntry(text_id=SHEET_ID, origin="sheet:samples.xlsx!Sheet1!B2", value=EVIL),
        ]

    def summary(self, session_id: str) -> InspectSummary:
        self._log("summary")
        return InspectSummary(
            input_sha256="5e" * 32,
            n_samples=2,
            declared_types={EVIL: 1, "unkn": 1},
            experiments={EVIL: 1},
            runs=[InspectRun(experiment_id=EVIL, run_id=EVIL, n_wells=2)],
            samples=[InspectSample(sample=EVIL, text_id=TEXT_ID, declared_type="unkn", n_wells=2)],
            targets=[
                InspectTarget(
                    target=EVIL, text_id=TEXT_ID, declared_type="toi", n_wells=2, n_with_cq=2
                )
            ],
            sheet=[SheetCell(cell="Sheet1!B2", text_id=SHEET_ID, row=2, column=2)],
        )

    def consistent_ids(self, session_id: str, stage: str) -> list[str]:
        self._log("consistent_ids")
        return [
            p.id
            for p in self.inbox(session_id, stage, "proposed")
            if p.check.status == "consistent" and p.kind != "stage.confirm"
        ]

    def matters(self, session_id: str, proposal: Proposal) -> bool | None:
        self._log("matters")
        return True

    def curve(self, session_id: str, well_key: str) -> dict[str, list[float]]:
        self._log("curve")
        return {"cycle": [1, 2, 3, 4], "fluorescence": [1.0, 1.1, 2.5, float("nan")]}

    def study(self, session_id: str) -> str:
        self._log("study")
        if not self.visible:
            raise StudioError("confirm the design and the curves first: results stay hidden")
        return STUDY

    def preview_prism(self, session_id: str, rows: int | None = 5) -> dict[str, Any]:
        self._log("preview_prism")
        if not self.visible:
            raise StudioError("confirm the design and the curves first: results stay hidden")
        head = ["Sample,MYCN-high,rest", f'"{EVIL}",1.5,', "u2,2.5,", "u3,,0.5", "u4,,-0.25"]
        return {
            "writes_nothing": True,
            "bundle": {
                "study_id": STUDY,
                "template_id": "two_groups_log2",
                "test": EVIL,
                "tables": [{"gene": "ODC1", "columns": ["Sample", "MYCN-high", EVIL], "n_rows": 4}],
                "info": {"caption": EVIL, "refs": EVIL, "groups": EVIL},
            },
            "would_write": [EVIL],
            "template": {
                "id": "two_groups_log2",
                "file": EVIL,
                "available": False,
                "layout": "column",
                "test": EVIL,
                "graph": EVIL,
            },
            "tables": {
                "ODC1": {
                    "columns": ["Sample", "MYCN-high", "rest"],
                    "n_rows": 4,
                    "head": head if rows is None or rows > 5 else head[:3],
                }
            },
            "choices": [{"card_id": EVIL, "option": EVIL, "actor": None}],
            "not_affiliated": "Works with GraphPad Prism. Not affiliated.",
        }

    # ---- proposing (the system) ----

    def open(self, rdml_path, sheet_path=None) -> str:
        self._log("open")
        return SID

    def propose_design(self, session_id: str, sentence: str = "") -> dict[str, Any]:
        self._log("propose_design")
        return {
            "proposed": ["p_d1"],
            "refused": [{"reason": EVIL}],
            "notes": [EVIL],
            "fallback": True,
        }

    def propose_comparison(self, session_id: str) -> ProposalOutcome | None:
        self._log("propose_comparison")
        return ProposalOutcome(status="refused", head="phead", reason=EVIL)

    def propose_curves(self, session_id: str) -> dict[str, Any]:
        self._log("propose_curves")
        return {
            "proposed": ["p_c1"],
            "refused": [],
            "notes": [EVIL],
            "disagreements": 3,
            "targets_that_matter": 1,
        }

    def propose_confirm(self, session_id: str, stage: str) -> ProposalOutcome:
        self._log("propose_confirm")
        return ProposalOutcome(status="proposed", head="phead", proposal=self._proposals[5])

    def propose_prism(self, session_id: str, genes=None, template_id: str = "") -> ProposalOutcome:
        self._log("propose_prism")
        return ProposalOutcome(status="proposed", head="phead", proposal=self._proposals[9])

    def round_trip(self, session_id: str, bundle_dir, sent_back_dir) -> dict[str, Any]:
        self._log("round_trip")
        return {
            "items": [{"kind": "missing", "gene": "ODC1", "row": EVIL}],
            "notes": [EVIL],
            "inbox": {"proposed": ["p_r1"], "refused": [], "notes": []},
        }

    # ---- deciding (a person) ----

    def _outcome(self, status: str, pid: str) -> ProposalOutcome:
        found = next((p for p in self._proposals if p.id == pid), None)
        return ProposalOutcome(status=status, head="phead2", proposal=found)

    def accept(self, session_id, proposal_id, actor, reason="", expected_head=None):
        self._log("accept", actor)
        return self._outcome("accepted", proposal_id)

    def edit(self, session_id, proposal_id, actor, edits, reason, expected_head=None):
        self._log("edit", actor)
        return self._outcome("edited", proposal_id)

    def reject(self, session_id, proposal_id, actor, reason, expected_head=None):
        self._log("reject", actor)
        return self._outcome("rejected", proposal_id)

    def accept_all_consistent(self, session_id, stage, actor, ids, reason=""):
        self._log("accept_all_consistent", actor)
        return [self._outcome("accepted", pid) for pid in ids]

    def reject_many(self, session_id, ids, actor, reason):
        self._log("reject_many", actor)
        return [self._outcome("rejected", pid) for pid in ids]

    def decide(self, session_id, card_id, option, reason, actor, expected_head=None):
        self._log("decide", actor)
        card = next(c for c in self._cards if c.id == card_id)
        return DecisionOutcome(status="applied", chain_head="dhead2", card=card)

    def send_to_prism(self, session_id, out_dir, actor, *, share=False):
        self._log("send_to_prism", actor)
        folder = Path(out_dir)
        (folder / "qpilot_bundle.json").write_text(json.dumps({"study_id": STUDY}))
        (folder / "sent_back").mkdir(exist_ok=True)
        bundle = SimpleNamespace(study_id=STUDY, bundle_sha256="ab" * 32, tables=[])
        return SimpleNamespace(
            bundle=bundle,
            out_dir=folder,
            files={"ODC1.csv": folder},
            notes=[EVIL],
            launch=SimpleNamespace(command_line=EVIL),
        )

    def launch_prism(self, result, actor, wait_s: float = 0.0) -> dict[str, Any]:
        self._log("launch_prism", actor)
        return {"launched": False, "note": EVIL, "bundle_dir": str(result.out_dir)}
