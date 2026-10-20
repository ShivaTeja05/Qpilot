"""CLI for qPilot Studio: ``qpilot studio`` opens the one page; ``studio demo --check`` checks it.

Studio is now part of ``qpilot app``: ``qpilot studio [--port N] [--no-open]`` serves the same one
page (Studio, the results, the audit, Prism and the record) on 127.0.0.1 with the same launch key
and hardening (see :mod:`qpilot.web.server`), and says so.

``qpilot studio demo --check [--studies DIR]`` walks the cached demo through every stage with no
browser and no model (the rules propose alone, so every number is deterministic): the design and
curve proposals with their engine checks, a scripted person's accepts and rejects (each with its
reason printed), the blind stages, the analysis, Send to Prism, one value excluded in the table
sent back, and the re-analysis. It prints each stage and the checked numbers and exits non-zero
when any of them differs from the measured ones (``docs/studio-measured.md``). It writes only
into a temporary folder (removed afterwards), or the studies into ``--studies DIR`` (a new or
empty folder), never into the user's study store.
"""

from __future__ import annotations

import argparse
import math
import shutil
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qpilot.cli._types import Command

#: The numbers the check expects, as measured on the demo (``docs/studio-measured.md``).
EXPECTED: dict[str, Any] = {
    "samples": 427,
    "design_proposals": 131,  # the rules alone, no model
    "consistent_listed": 121,  # after the preset is accepted
    "contradicted_left": 9,
    "well_roles_contradicted": 7,  # the conc-64 level of each competimer series never amplified
    "dilution_series_consistent_min": 6,  # comp 00-40 (+ the standards)
    "comp_50_r2": 0.707,
    "std_series_r2": 0.694,  # the declared standards on the ALUsq plate
    "curve_judge_disagreements": 166,
    "curve_judge_well_calls": 110,  # ALUsq's early curves, LinRegPCR fitted every one
    "curve_judge_target": "ALUsq(Eurogentec)",
    "odc1_fc": 3.590,
    "grid_cells": 744,
    "genes": 58,
    "route_linear_welch_differ": 14,
    "route_linear_student_differ": 21,
    "route_ddcq_differ": 4,
    "excluded_unit": "1496",
    "odc1_fc_after": 3.319,
    "conclusions_changed": 0,
}
REASONS = {
    "preset": "the file is the pinned Vermeulen dataset; the preset is its published design",
    "consistent": "checked the listed proposals; the engine finds nothing against them",
    "design_rejects": "contradicted by the engine check",
    "well_calls": "LinRegPCR fitted a complete early curve in each of these wells",
    "rule": "LinRegPCR's call is the engine's default; the cut-offs stay as choices",
    "cards": "the recommended option, as pre-registered for the demo",
    "project": "the default template and the headline genes",
    "exclusion": "failed RNA extraction",
}


class Checks:
    """Each checked number, printed as it is checked; ``failed`` counts the misses."""

    def __init__(self, out: Callable[[str], None]) -> None:
        self.out = out
        self.n = 0
        self.failed = 0

    def __call__(self, label: str, ok: bool, got: Any = "", want: Any = "") -> bool:
        """Print one check; count it as failed when ``ok`` is false."""
        self.n += 1
        if ok:
            self.out(f"  ok    {label}{f': {got}' if got != '' else ''}")
        else:
            self.failed += 1
            self.out(f"  FAIL  {label}: got {got!r}, expected {want!r}")
        return ok


def _hidden(studio: Any, sid: str) -> bool:
    """True when the service refuses both the analysis and the Prism preview (blind)."""
    from qpilot.studio_service import StudioError

    for read in (studio.study, studio.preview_prism):
        try:
            read(sid)
        except StudioError:
            continue
        return False
    return not studio.results_visible(sid)


def demo_check(studies: str | Path | None = None, out: Callable[[str], None] = print) -> int:
    """Walk the demo through Studio with a scripted person; 0 when every number matches."""
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.record import verify, write_record
    from qpilot.core.store import StudyStore
    from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir
    from qpilot.studio_service import Studio

    rdml = default_cache_dir() / VERMEULEN_FILENAME
    if not rdml.exists():
        out("qpilot studio demo --check: the demo dataset is not cached; run `qpilot fetch-demo`")
        return 2
    if studies is not None:
        folder = Path(studies)
        if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
            out(f"qpilot studio demo --check: --studies must be a new or empty folder: {folder}")
            return 2
    scratch = Path(tempfile.mkdtemp(prefix="qpilot-studio-check-"))
    try:
        store = StudyStore(Path(studies) if studies is not None else scratch / "studies")
        studio = Studio(store, client=ModelClient(backend=NoneBackend()))
        out(
            "qPilot Studio demo check: the rules propose alone (no model); a scripted person "
            f"decides; study store {store.root}"
        )
        check = Checks(out)
        try:
            _walk(studio, rdml, scratch, check, out, verify, write_record)
        except Exception as err:  # a walk that stops is a failed check, reported, not a crash
            check(f"the walk stopped early ({type(err).__name__})", False, str(err), "no error")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if check.failed:
        out(f"{check.failed} of {check.n} checks FAILED.")
        return 1
    out(f"All {check.n} checks passed.")
    return 0


def _walk(studio, rdml, scratch, check, out, verify, write_record) -> None:  # noqa: PLR0915
    e = EXPECTED

    def person(action: str, reason: str) -> None:
        out(f"  person {action} — reason: “{reason}”")

    # ---- 1. design (blind) ----
    out("1 Design (blind)")
    sid = studio.open(rdml)
    summary = studio.summary(sid)
    check(
        "samples declared in the file",
        summary.n_samples == e["samples"],
        summary.n_samples,
        e["samples"],
    )
    report = studio.propose_design(sid)
    inbox = studio.inbox(sid, "design", "proposed")
    check(
        "design proposals (the rules alone)",
        len(report["proposed"]) == e["design_proposals"],
        len(report["proposed"]),
        e["design_proposals"],
    )
    kinds = Counter((p.kind, p.check.status) for p in inbox)
    check(
        "the demo preset is proposed (no engine check exists for it)",
        kinds[("design.preset", "cannot_check")] == 1,
        kinds[("design.preset", "cannot_check")],
        1,
    )
    consistent = kinds[("design.dilution_series", "consistent")]
    check(
        "dilution series consistent with their R²",
        consistent >= e["dilution_series_consistent_min"],
        consistent,
        f">= {e['dilution_series_consistent_min']}",
    )
    comp50 = next(
        (p for p in inbox if p.kind == "design.dilution_series" and p.subject == "comp_50"), None
    )
    r2 = comp50.check.details.get("r2") if comp50 else None
    check(
        "comp_50 series contradicted (R² 0.707)",
        comp50 is not None
        and comp50.check.status == "contradicted"
        and r2 is not None
        and round(r2, 3) == e["comp_50_r2"],
        r2,
        e["comp_50_r2"],
    )
    std = next(
        (p for p in inbox if p.kind == "design.dilution_series" and p.subject == "STD"), None
    )
    std_r2 = std.check.details.get("r2") if std else None
    check(
        "the standards' series on the ALUsq plate contradicted (R² 0.694)",
        std is not None
        and std.check.status == "contradicted"
        and std_r2 is not None
        and round(std_r2, 3) == e["std_series_r2"],
        std_r2,
        e["std_series_r2"],
    )
    roles = kinds[("design.well_role", "contradicted")]
    check(
        "standards at conc 64 contradicted (never amplified)",
        roles == e["well_roles_contradicted"],
        roles,
        e["well_roles_contradicted"],
    )
    check("results hidden before the design is confirmed", _hidden(studio, sid), True, True)
    preset = next(p for p in inbox if p.kind == "design.preset")
    person("accepts the demo preset", REASONS["preset"])
    studio.accept(sid, preset.id, "human", REASONS["preset"])
    ids = studio.consistent_ids(sid, "design")
    shown = studio.inbox(sid, "design", "proposed")
    listed = [p for p in shown if p.id in set(ids)]
    check(
        "“Accept all consistent” lists only consistent proposals",
        all(p.check.status == "consistent" for p in listed)
        and len(listed) == len(ids) == e["consistent_listed"],
        len(ids),
        e["consistent_listed"],
    )
    person(f"accepts the {len(ids)} listed consistent proposals", REASONS["consistent"])
    bulk = studio.accept_all_consistent(sid, "design", "human", ids, REASONS["consistent"])
    check(
        "one accept per listed proposal",
        sum(o.status == "accepted" for o in bulk) == len(ids),
        sum(o.status == "accepted" for o in bulk),
        len(ids),
    )
    left = studio.inbox(sid, "design", "proposed")
    check(
        "what is left is what the engine contradicts",
        all(p.check.status == "contradicted" for p in left) and len(left) == e["contradicted_left"],
        len(left),
        e["contradicted_left"],
    )
    person(f"rejects the {len(left)} contradicted proposals", REASONS["design_rejects"])
    studio.reject_many(sid, [p.id for p in left], "human", REASONS["design_rejects"])
    confirm = studio.propose_confirm(sid, "design").proposal
    person(
        f"confirms the design stage ({len(confirm.payload['covers'])} accepted proposals)",
        "checked",
    )
    studio.accept(sid, confirm.id, "human", "checked")

    # ---- 2. curves (blind) ----
    out("2 Curves (blind)")
    report = studio.propose_curves(sid)
    curves = studio.inbox(sid, "curves", "proposed")
    calls = [p for p in curves if p.kind == "curve.well_call"]
    check(
        "study wells where the Curve Judge disagrees with LinRegPCR",
        report["disagreements"] == e["curve_judge_disagreements"],
        report["disagreements"],
        e["curve_judge_disagreements"],
    )
    out(f"  {report['targets_that_matter']} target(s) where that could change a conclusion")
    check(
        "Curve Judge well calls proposed",
        len(calls) == e["curve_judge_well_calls"],
        len(calls),
        e["curve_judge_well_calls"],
    )
    targets = sorted({p.evidence[0].note for p in calls})
    check(
        "all on the ALUsq reference gene",
        targets == [f"target {e['curve_judge_target']}"],
        targets,
        [f"target {e['curve_judge_target']}"],
    )
    check(
        "each contradicted by LinRegPCR (D-CURVE)",
        all(p.check.status == "contradicted" and p.check.rule_ids == ["D-CURVE"] for p in calls),
        True,
        True,
    )
    check(
        "each says only that it matters (no gene, no number)",
        all(p.consequence == {"matters": True} for p in calls),
        True,
        True,
    )
    check("results hidden before the curves are confirmed", _hidden(studio, sid), True, True)
    person(f"rejects the {len(calls)} Curve Judge calls", REASONS["well_calls"])
    studio.reject_many(sid, [p.id for p in calls], "human", REASONS["well_calls"])
    rule = next(p for p in curves if p.kind == "curve.call_rule")
    person("accepts the call rule (LinRegPCR)", REASONS["rule"])
    studio.accept(sid, rule.id, "human", REASONS["rule"])
    person("confirms the curves stage", "checked")
    studio.accept(sid, studio.propose_confirm(sid, "curves").proposal.id, "human", "checked")

    # ---- 3. choices ----
    out("3 Choices (results visible from here)")
    study = studio.study(sid)
    result = studio.store.get(study)
    odc1 = result.contrasts["ODC1"]
    out(f"  analysis {study}")
    check(
        "ODC1 fold change, up",
        math.isclose(odc1.fc, e["odc1_fc"], abs_tol=5e-4) and odc1.conclusion == "up",
        f"{odc1.fc:.3f}× {odc1.conclusion}",
        f"{e['odc1_fc']:.3f}× up",
    )
    cells = result.robustness["ODC1"].n_cells
    check("analyses in the grid", cells == e["grid_cells"], cells, e["grid_cells"])
    genes = result.facts["f_n_genes"].value
    for route, words in (
        ("linear_welch", "the usual Excel→Prism route (linear, Welch) changes conclusions"),
        ("linear_student", "the same with Student's t test"),
        ("ddcq", "ΔΔCq at an assumed efficiency of 2.0"),
    ):
        differ = result.facts[f"f_n_differ_route_{route}"].value
        want = e[f"route_{route}_differ"]
        check(
            words,
            (differ, genes) == (want, e["genes"]),
            f"{differ} of {genes}",
            f"{want} of {e['genes']}",
        )
    for card in studio.store.cards(study):
        if card.status != "auto_decided":
            person(f"decides {card.id}: {card.recommended}", REASONS["cards"])
            head = studio.store.chain_head(study)
            studio.decide(sid, card.id, card.recommended, REASONS["cards"], "human", head)
    person("confirms the choices stage", "checked")
    studio.accept(sid, studio.propose_confirm(sid, "choices").proposal.id, "human", "checked")

    # ---- 4. the Prism draft ----
    out("4 Prism draft")
    project = studio.propose_prism(sid).proposal
    person(
        f"accepts the Prism project (genes {', '.join(project.payload.get('genes', []))})",
        REASONS["project"],
    )
    studio.accept(sid, project.id, "human", REASONS["project"])
    bundle = scratch / "bundle"
    export = studio.send_to_prism(sid, bundle, "human")
    out(
        f"  sent to Prism: {len(export.files)} files, "
        f"bundle sha256 {export.bundle.bundle_sha256[:16]}…"
    )

    # ---- 5. the round trip ----
    out("5 Round trip (scripted: ODC1's sample 1496 emptied in the table sent back)")
    sent_back = scratch / "sent_back"
    sent_back.mkdir()
    for table in export.bundle.tables:
        shutil.copy(bundle / table.csv, sent_back / Path(table.csv).name)
    odc1_csv = sent_back / "ODC1.csv"
    unit = e["excluded_unit"]
    lines = odc1_csv.read_text().split("\n")
    lines = [
        ",".join([ln.split(",")[0], "", ""]) if ln.startswith(f"{unit},") else ln for ln in lines
    ]
    odc1_csv.write_text("\n".join(lines))
    trip = studio.round_trip(sid, bundle, sent_back)
    items = [(i["kind"], i["gene"], i["row"]) for i in trip["items"]]
    check(
        "one difference found",
        items == [("missing", "ODC1", unit)],
        items,
        [("missing", "ODC1", unit)],
    )
    exclusion = next(iter(studio.inbox(sid, "roundtrip", "proposed")))
    c = exclusion.consequence or {}
    check(
        "ODC1 fold change before → after the exclusion, still up",
        round(c.get("fc_before", 0), 3) == e["odc1_fc"]
        and round(c.get("fc_after", 0), 3) == e["odc1_fc_after"]
        and c.get("conclusion_after") == "up",
        f"{c.get('fc_before', 0):.3f}× → {c.get('fc_after', 0):.3f}× {c.get('conclusion_after')}",
        f"{e['odc1_fc']:.3f}× → {e['odc1_fc_after']:.3f}× up",
    )
    check(
        "conclusions that change",
        (c.get("n_conclusions_changed"), c.get("n_genes"))
        == (e["conclusions_changed"], e["genes"]),
        f"{c.get('n_conclusions_changed')} of {c.get('n_genes')}",
        f"{e['conclusions_changed']} of {e['genes']}",
    )
    person("accepts the exclusion", REASONS["exclusion"])
    studio.accept(sid, exclusion.id, "human", REASONS["exclusion"])
    stages = {s.stage: s for s in studio.stages(sid)}
    new = studio.study(sid)
    after = studio.store.get(new).contrasts["ODC1"]
    check(
        "a new analysis, ODC1 still up",
        new != study and round(after.fc, 3) == e["odc1_fc_after"] and after.conclusion == "up",
        f"{new}: {after.fc:.3f}× {after.conclusion}",
        f"a new id: {e['odc1_fc_after']:.3f}× up",
    )
    check(
        "design and curves stay confirmed; the choices re-open",
        stages["design"].confirmed
        and stages["curves"].confirmed
        and not stages["choices"].confirmed,
        True,
        True,
    )
    info = write_record(studio.store, new, scratch / "record")
    report = verify(info.record_dir)
    check(
        "the new analysis's record verifies (proposals included)",
        report.ok and (Path(info.record_dir) / "proposals.jsonl").exists(),
        report.ok,
        True,
    )


def _arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "action",
        nargs="?",
        choices=["demo"],
        help="demo: with --check, the scripted end-to-end check on the cached demo",
    )
    parser.add_argument(
        "--port", type=int, default=None, help="port (default: first free from 7860)"
    )
    parser.add_argument(
        "--no-open", action="store_true", help="print the link but do not open a browser"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="(with demo) run the check: no browser, no model; exits 1 if a number differs",
    )
    parser.add_argument(
        "--studies",
        default=None,
        help="(with demo --check) a new or empty folder for the studies (default: temporary)",
    )


def _run(args: argparse.Namespace) -> int:
    if args.action == "demo":
        if not args.check:
            print("qpilot studio demo: add --check to run the end-to-end check", file=sys.stderr)
            return 2
        return demo_check(args.studies)
    if args.check or args.studies:
        print("qpilot studio: --check and --studies go with `qpilot studio demo`", file=sys.stderr)
        return 2
    from qpilot.web.server import main as serve_page

    print(MOVED, flush=True)
    serve_page(port=args.port, open_browser=not args.no_open)
    return 0


MOVED = (
    "qPilot Studio is now part of `qpilot app`: one page for Studio, the results, the robustness "
    "audit, Prism and the Analysis Record. Opening it."
)

COMMANDS: list[Command] = [
    (
        "studio",
        "open qPilot's one page (Studio is now part of `qpilot app`); `studio demo --check` "
        "checks Studio end to end",
        _arguments,
        _run,
    ),
]
