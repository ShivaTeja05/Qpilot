"""The audit's results screen, in plain lab language: the views the one page serves.

:class:`Screen` reads the engine's files of an audit (``results/``):

* ``explain.json``: verdict, call, fold change and the choices that change each gene;
* ``genes.csv``: per-gene holds, margins and samples that carry the call;
* ``issues.json``: the investigation queue;
* ``summary.json``: the study, the verdict rules and the run's provenance;
* ``decisions.csv``: how much each choice moves the calls.

``one_sample_flips.csv`` and ``validation_untergasser.json`` are optional: the screen leaves out
what they feed when a run has not made them (a quick run of a lab's own plate, for example).

It calls the engine live for the what-if views (:func:`qsim.compare.whatif`, :class:`LabViews`)
and for Ask (:class:`qsim.ask.Asker`). Every figure is read from those files or returned by the
engine; the sentences around the figures are fixed wording, and statistics jargon stays out.

qPilot's one page serves these views (``qpilot/web/routers/audit.py``, ``qsim app`` and
``qpilot app --audit``); the screen's own stdlib server and HTML page were removed with the old
pages.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from qsim.app_lab import LabViews
from qsim.compare import whatif
from qsim.data import BENCHMARK_NAME, load_study
from qsim.decisions import PLAIN
from qsim.engine import Engine
from qsim.issues import HEADLINE
from qsim.moves import MAX_MOVES
from qsim.plates import REQUIRED
from qsim.study_space import space_for
from qsim.verdict import ORDER

RAW_FILES = (
    "explain.json",
    "genes.csv",
    "issues.json",
    "summary.json",
    "one_sample_flips.csv",
    "decisions.csv",
    "validation_untergasser.json",
)

VERDICT_LABEL = {
    "solid": "Solid",
    "holds with caveats": "Holds with caveats",
    "depends on your choices": "Depends on your choices",
    "fragile": "Fragile",
    "check data first": "Check data first",
    "no call": "No change called",
}
SHORT_CALL = {"up": "called up", "down": "called down", "none": "no call"}
TIER_WORD = {
    "prespecified": "your planned analysis",
    "defensible": "reasonable alternative",
    "common_practice": "common shortcut",
}
ISSUE_KIND = {
    "decision": "an analysis choice",
    "reference_group_effect": "a reference gene",
    "well_outlier": "one well",
    "sample_outlier": "one sample",
    "spatial": "a plate pattern",
    "efficiency": "an assay's efficiency",
    "ntc": "a no-template control",
}
TOOL_WORDS = {
    "gene": "the gene look-up",
    "whatif": "a live what-if run of the engine",
    "decision": "the choice summary",
    "issues": "the issue queue",
    "overview": "the study overview",
}
ROUTED_WORDS = {
    "rules": "fixed reading rules",
    "model": "the local model",
    "keywords": "keyword matching (no model)",
}
# genes.csv columns, in plain words, for the evidence page (columns not listed are not shown)
EVIDENCE_LABELS = {
    "all_baseline_call": "Call with the planned analysis",
    "all_baseline_fold": "Fold change with the planned analysis (group ÷ rest)",
    "defensible_holds": "Share of the audit's reasonable analyses with the same call",
    "defensible_flipped_by_one": "A single reasonable choice that changes the call",
    "defensible_interaction_only": "Changes only when two choices change together",
    "all_holds": "Share of all analyses, shortcuts included, with the same call",
    "all_flipped_by_one": "A single choice, shortcuts included, that changes the call",
    "fold_margin_log2": "Distance from the fold-change line (log2 units)",
    "p_margin_decades": "How far the p-value is below the line (powers of ten)",
    "samples_whose_removal_flips": "Single samples whose removal changes the call",
    "drop_k_to_flip": "Fewest samples whose removal changes the call",
    "moves_to_flip": "Fewest reasonable moves (a choice changed or a sample left out) that change the call",
    "moves_path": "The quickest such path",
    "share_forks_significant_same_direction": "Share of analyses where the difference is clear",
    "p_global": "p-value across the audit's reasonable analyses, all genes tested together",
    "q_global_bh": "The same, corrected for testing many genes",
    "verdict": "Verdict",
}


#: The audit's own set of analyses, always named (qPilot's choice grid is another set).
REASONABLE = "the audit's reasonable analyses"
REASONABLE_WHAT = (
    "every combination of choices a careful lab could defend: no common shortcuts (such as a "
    "single or paired control gene), and the groups and the correction for many genes as planned"
)


def _per100(share: float) -> int:
    return int(round(100 * float(share)))


def _k(share: float, n: int) -> int:
    """How many of ``n`` analyses a share of them is."""
    return int(round(float(share) * n))


def _fold(fold: float) -> str:
    return f"{fold:.2f}× higher" if fold >= 1 else f"{1 / fold:.2f}× lower"


def _range(lo: float, hi: float) -> str:
    if lo >= 1:
        return f"{lo:.2f}× to {hi:.2f}× higher"
    if hi < 1:
        return f"{1 / hi:.2f}× to {1 / lo:.2f}× lower"
    return f"{1 / lo:.2f}× lower to {hi:.2f}× higher"


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _join(words: list[str], last: str = "and") -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} {last} {words[-1]}"


class Screen(LabViews):
    """Everything the page shows, built from the engine's files and live engine calls."""

    def __init__(self, results: str | Path = "results", rdml: str | None = None, asker=None):
        self._read(results)
        source = self.summary.get("source") or {}
        if rdml is None and source.get("rdml") and Path(source["rdml"]).is_file():
            rdml = source["rdml"]  # the file this run was made from
        study = load_study(rdml)
        if study.input_sha256 != self.summary["input_sha256"]:
            raise ValueError(
                f"{self.dir} was made from a different file than "
                f"{rdml or 'the benchmark'}: pass the matching --rdml or --results."
            )
        self._bind(Engine(study, space_for(study)[0]), rdml, asker)

    @classmethod
    def from_prepared(cls, results: str | Path, prepared, asker=None) -> Screen:
        """The screen of a run made from a study prepared elsewhere, with that study's engine.

        qPilot's audit (``qpilot.integration.simulator``) builds the study from the design a
        person confirmed (well roles, excluded wells, the two named groups) and runs the
        simulator on it; re-reading the raw RDML here would describe other numbers. So the live
        views (what-if, analyses, effects, samples, lab) use ``prepared.engine`` as it is.

        Args:
            results: The run's results folder (``explain.json``, ``genes.csv``, ...).
            prepared: Anything with ``engine`` (the run's engine) and optionally ``scope``
                (``{"mode": "groups" | "marker_split", "groups": [high, rest]}``), as
                ``qpilot.integration.simulator.Prepared`` has.
            asker: An Ask engine to reuse (built on first use otherwise).

        Raises:
            FileNotFoundError: The folder has no complete run.
            ValueError: The run was made from another input file or for other genes.
        """
        screen = cls.__new__(cls)
        screen._read(results)
        engine = prepared.engine
        if engine.study.input_sha256 != screen.summary["input_sha256"]:
            raise ValueError(f"{screen.dir} was made from another input file than this study")
        unknown = sorted(set(screen.explain) - set(engine.items))
        if unknown:
            raise ValueError(f"{screen.dir} has genes this study does not compare: {unknown[:5]}")
        screen._bind(engine, None, asker)
        scope = getattr(prepared, "scope", None) or {}
        groups = scope.get("groups") or []
        if scope.get("mode") == "groups" and len(groups) == 2:
            high, rest = (str(g) for g in groups)
            screen.group, screen.rest, screen.rest_short = high, rest, rest
            screen.group_def = f"the {high} group of the confirmed design, compared with {rest}"
            screen.stage_text["Define the groups"] = (
                f"The confirmed design's two groups are compared: {high} and {rest}."
            )
        elif groups:
            screen.group = str(groups[0])
        return screen

    def _read(self, results: str | Path) -> None:
        """Read the run's files (everything the screen shows that is not computed live)."""
        self.dir = Path(results)
        missing = [f for f in REQUIRED if not (self.dir / f).exists()]
        if missing:
            raise FileNotFoundError(
                f"{self.dir} has no complete run ({', '.join(missing)} missing): run "
                f"`qsim run --out {self.dir}` first, or open a file with `qsim app --rdml`."
            )
        self.explain: dict = json.loads((self.dir / "explain.json").read_text())
        self.genes = pd.read_csv(self.dir / "genes.csv").set_index("gene")
        self.issues: list[dict] = json.loads((self.dir / "issues.json").read_text())
        self.summary: dict = json.loads((self.dir / "summary.json").read_text())
        flips = self.dir / "one_sample_flips.csv"
        self.sample_flips = pd.read_csv(flips, dtype={"sample": str}) if flips.exists() else None
        self.source = (self.summary.get("source") or {}).get("name") or BENCHMARK_NAME

    def _bind(self, engine: Engine, rdml: str | None, asker) -> None:
        """Use ``engine`` for the live views and set the words that depend on its study."""
        self.engine = engine
        self.space = self.engine.space
        self.rules = self.summary["verdicts"]["rules"]
        self.line = 2**self.engine.rule.min_log2fc
        self.alpha = self.engine.rule.alpha
        marker = engine.study.marker.split("(")[0]
        cut = self.space.decision("cut")
        self.group = f"{marker}-high"
        self.rest = "the rest"  # the other group, in a sentence ("than in the rest")
        self.rest_short = "rest"  # ... and in a count ("294 rest")
        self.group_def = cut.options[cut.index(self.space.baseline["cut"])].label
        self.stage_text: dict[str, str] = {}  # how-it-works stage text that differs here
        self.n_samples = self.summary["study"]["samples"]
        self._asker = asker
        self.ask_client = None  # the Ask engine's model client (None: qsim's default)
        self._rdml = rdml
        self._engine_lock = threading.Lock()
        self._ask_lock = threading.Lock()
        self._asker_lock = threading.Lock()

    # ---- words shared by several panels ----------------------------------------------
    def line_words(self) -> str:
        return f"{self.line:g}×"

    def call_words(self, call: str) -> str:
        return {
            "up": f"called up (higher in {self.group})",
            "down": f"called down (lower in {self.group})",
            "none": "no change called",
        }[call]

    def verdict_rules(self) -> dict[str, str]:
        r, line = self.rules, self.line_words()
        return {
            "solid": (
                f"Same call in at least {_per100(r['solid_holds'])} % of {REASONABLE}, "
                f"no {r['drop_k_searched']} or fewer samples change it, and the difference is "
                f"clear in at least {_per100(r['solid_significant'])} % of them."
            ),
            "holds with caveats": (
                f"Same call in at least {_per100(r['solid_holds'])} % of {REASONABLE}, "
                f"but {r['drop_k_searched']} or fewer samples change it, or the difference is "
                "not always clear."
            ),
            "depends on your choices": (
                f"Same call in {_per100(r['fragile_holds'])} % to {_per100(r['solid_holds'])} % "
                f"of {REASONABLE}: the rest depend on the choices made."
            ),
            "fragile": (
                f"Same call in fewer than {_per100(r['fragile_holds'])} % of {REASONABLE}, or "
                f"{r['fragile_drop_k']} or fewer samples change it, or it sits within "
                f"{_per100(2 ** r['fragile_margin_log2'] - 1)} % of the {line} line."
            ),
            "check data first": "A problem found in the data changes this call when it is fixed.",
            "no call": (
                f"Not called a change: a call needs at least {line} and a p-value below "
                f"{self.alpha:g}."
            ),
        }

    def _data_issues(self, gene: str) -> list[dict]:
        return [
            i for i in self.issues if i["kind"] != "decision" and gene in i.get("changed_calls", [])
        ]

    def issue_list(self) -> dict:
        """The whole investigation queue, in its order (the overview shows the first six)."""
        return {"issues": [self._issue_view(i) for i in self.issues], "n_issues": len(self.issues)}

    def _issue_view(self, issue: dict) -> dict:
        return {
            "id": issue["issue_id"],
            "title": issue["title"],
            "about": ISSUE_KIND.get(issue["kind"], issue["kind"].replace("_", " ")),
            "action": issue["action"],
            "changes": issue.get("changed_calls", []),
            "headline": issue.get("headline_changed", []),
            "causes": issue.get("consistent_with", []),
            "wells": issue.get("loci", {}).get("wells", []),
            "samples": issue.get("loci", {}).get("samples", []),
            "plate": issue.get("loci", {}).get("plate", ""),
        }

    # ---- the page's first load ---------------------------------------------------------
    def overview(self) -> dict:
        counts = {v: 0 for v in ORDER}
        for e in self.explain.values():
            counts[e["verdict"]] = counts.get(e["verdict"], 0) + 1
        rules = self.verdict_rules()
        order = {v: k for k, v in enumerate(ORDER)}
        genes = sorted(self.explain, key=lambda g: (order[self.explain[g]["verdict"]], g))
        study = self.summary["study"]
        refs = self.space.decision("refs")
        planned_refs = refs.options[refs.index(self.space.baseline["refs"])]
        return {
            "study": {
                "samples": study["samples"],
                "genes": study["genes_compared"],
                "plates": study["plates"],
                "group": self.group,
                "group_def": self.group_def,
                "rest": self.rest,
                "analyses": self.summary["ledger"]["total_cells"],
                "reasonable": self.explain[genes[0]]["analyses_defensible"],
                "references": [g.split("(")[0] for g in planned_refs.value],
            },
            "verdicts": [
                {
                    "key": v,
                    "label": VERDICT_LABEL[v],
                    "count": counts.get(v, 0),
                    "rule": rules[v],
                }
                for v in ORDER
            ],
            "genes": [
                {
                    "gene": g,
                    "fold": _fold(self.explain[g]["fold"]),
                    "call": self.explain[g]["call"],
                    "call_key": self.explain[g]["call"],
                    "verdict": self.explain[g]["verdict"],
                    "label": VERDICT_LABEL[self.explain[g]["verdict"]],
                    "headline": g in HEADLINE,
                }
                for g in genes
            ],
            "headline": [g for g in HEADLINE if g in self.explain],
            "source": {"name": self.source, "benchmark": self.source == BENCHMARK_NAME},
            "decisions": self.decisions(),
            "issues": [self._issue_view(i) for i in self.issues[:6]],
            "n_issues": len(self.issues),
            "model": self.model_status(),
            "provenance": {
                "run": self.summary.get("grid_hash", ""),
                "lock": self.summary.get("lock_sha256", "")[:12],
                "input": self.summary.get("input_sha256", "")[:12],
                "qsim": self.summary.get("qsim_version", ""),
                "files": [f for f in RAW_FILES if (self.dir / f).exists()],
            },
        }

    def decisions(self) -> list[dict]:
        out = []
        for d in self.space.decisions:
            out.append(
                {
                    "id": d.id,
                    "name": PLAIN[d.id][0].upper() + PLAIN[d.id][1:],
                    "question": d.question,
                    "changes_claim": d.role == "question",
                    "baseline": self.space.baseline[d.id],
                    "options": [
                        {"id": o.id, "label": o.label, "tier": TIER_WORD[o.tier]}
                        for o in sorted(d.options, key=lambda o: list(TIER_WORD).index(o.tier))
                    ],
                }
            )
        return out

    # ---- the gene card ----------------------------------------------------------------
    def gene_card(self, gene: str) -> dict:
        if gene not in self.explain:
            raise KeyError(gene)
        e, r = self.explain[gene], self.genes.loc[gene]
        rules, line = self.rules, self.line_words()
        holds = _per100(e["holds_defensible"])  # percent (the map's and the holds block's n)
        n_set = int(e["analyses_defensible"])
        same = f"{_k(e['holds_defensible'], n_set)} of {n_set}"  # "144 of 144"
        clear = f"{_k(e['share_significant'], n_set)} of {n_set}"
        dk = e["drop_k"]
        margin = e["fold_margin_log2"]
        margin_pct = _per100(2 ** abs(margin) - 1)
        data_issues = self._data_issues(gene)
        flip_decisions = sorted({d for f in e["flips"] for d in f["decisions"]})

        # 1. the result and the verdict sentence
        verdict = e["verdict"]
        if verdict == "solid":
            why = (
                f"Same call in {same} of {REASONABLE}, and no "
                f"{rules['drop_k_searched']} or fewer samples change it."
            )
        elif verdict == "holds with caveats":
            why = f"Same call in {same} of {REASONABLE}, but " + (
                f"removing {dk} samples changes it."
                if dk
                else f"the difference is clear in only {clear} of them."
            )
        elif verdict == "depends on your choices":
            why = (
                f"Same call in {same} of {REASONABLE}; the others turn on "
                f"{_join([PLAIN[d] for d in flip_decisions]) if flip_decisions else 'your choices'}."
            )
        elif verdict == "fragile":
            reasons = []
            if e["holds_defensible"] < rules["fragile_holds"]:
                reasons.append(f"same call in only {same} of {REASONABLE}")
            if dk is not None and dk <= rules["fragile_drop_k"]:
                reasons.append(f"removing {dk} sample{'s' if dk > 1 else ''} changes it")
            if margin < rules["fragile_margin_log2"]:
                reasons.append(f"it sits only {margin_pct} % beyond the {line} line")
            why = "Treat it as tentative: " + _join(reasons or ["it is close to the edge"]) + "."
        elif verdict == "check data first":
            why = (
                "A problem found in the data changes this call when it is fixed: "
                + ("; ".join(i["title"] for i in data_issues[:2]) or "see the issues below")
                + "."
            )
        else:
            why = (
                f"A call needs at least {line} and a p-value below {self.alpha:g}. "
                f"{same[0].upper() + same[1:]} of {REASONABLE} agree there is no call."
            )
        result = {
            "headline": f"{gene} is {_fold(e['fold'])} in {self.group} samples than in {self.rest}.",
            "lines": [
                (
                    f"With your planned analysis it is {self.call_words(e['call'])}."
                    if e["call"] != "none"
                    else "With your planned analysis no change is called."
                ),
                f"Likely range from this data: {_range(*e['ci'])}.",
                f"{self.group} means {self.group_def}.",
            ],
            "verdict_sentence": why,
        }

        # 2. how often the same answer comes out
        all_holds = _per100(r["all_holds"])
        holds_block = {
            "n": holds,
            "same": _k(e["holds_defensible"], n_set),
            "of": n_set,
            "lines": [
                f"The audit ran {n_set} reasonable analyses: {REASONABLE_WHAT}.",
                f"The same call comes out in {same} of them, and the difference itself is clear "
                f"(p below {self.alpha:g}) in {clear}.",
                "Across every option tried, common shortcuts and other group cut-offs included "
                f"({self.summary['ledger']['total_cells']:,} analyses), the same answer comes "
                f"out in {all_holds} % of them.",
            ],
        }

        # 3. what changes it
        changes = [
            {
                "choice": " and ".join(f["choices"]),
                "fold": _fold(f["fold"]),
                "call": self.call_words(f["call"]),
                "call_key": f["call"],
                "same_call": f["call"] == e["call"],
            }
            for f in e["flips"]
        ]
        shortcut = r.get("all_flipped_by_one")
        shortcut_line = None
        if not _missing(shortcut):
            names = [PLAIN.get(d, d) for d in str(shortcut).split(",")]
            shortcut_line = (
                "Across every option tried (common shortcuts and other group cut-offs "
                f"included), changing {_join(names, 'or')} on its own also changes it."
            )

        # 4. what it leans on
        singles = self._singles(gene)
        leans = []
        if not dk:
            leans.append(
                f"No {rules['drop_k_searched']} or fewer of the {self.n_samples} samples "
                "change the call."
            )
        elif not (dk == 1 and singles):
            leans.append(f"Removing {dk} of the {self.n_samples} samples would change the call.")
        if singles:
            leans.append(
                f"Removing any one of {len(singles)} single samples on its own changes it "
                "(listed below)."
            )
        mv = e.get("moves")
        if mv and mv["distance"]:
            n_moves = f"{mv['distance']} move{'s' if mv['distance'] > 1 else ''}"
            if not mv["exact"]:
                n_moves = f"at most {n_moves}"
            side = f"{'higher' if mv['call'] == 'up' else 'lower'} in {self.group}"
            if e["call"] == "none":
                effect = f"produce a call ({side})"
            elif mv["call"] == "none":
                effect = "lose the call"
            else:
                effect = f"turn it around ({side})"
            leans.append(f"The quickest way to {effect} takes {n_moves}: {'; '.join(mv['path'])}.")
        at = f"At {_fold(e['fold'])} it is"
        if margin >= self.engine.rule.min_log2fc:
            leans.append(f"{at} well past the {line} line a call needs.")
        elif margin >= 0:
            leans.append(f"{at} {margin_pct} % beyond the {line} line a call needs.")
        elif margin > -rules["fragile_margin_log2"]:
            leans.append(f"{at} just short of the {line} line a call needs ({margin_pct} %).")
        else:
            leans.append(f"{at} below the {line} line a call needs.")

        # 5. what to do
        todo = []
        if verdict == "solid":
            todo.append("Report it as it stands.")
        elif verdict == "holds with caveats":
            todo.append(
                "Report it, and say that it rests on a few samples. Before writing it up, check "
                "those samples' curves, RNA quality and labels."
            )
        elif verdict == "depends on your choices":
            todo.append(
                f"Fix {_join([PLAIN[d] for d in flip_decisions]) if flip_decisions else 'the choices'} "
                "before you look at results, write down why, and report the result under that "
                "choice."
            )
        elif verdict == "fragile":
            todo.append(
                "Do not report it as a firm change. Present it as tentative, or confirm it with "
                "more samples or a second method."
            )
        elif verdict == "check data first":
            todo.append("Resolve the data problem below, then read the verdict again.")
        else:
            todo.append("Nothing to report as a change.")
            if e["flips"]:
                todo.append(
                    f"Some of {REASONABLE} would call it, so do not report it as unchanged "
                    "without saying so."
                )
        for i in data_issues[:3]:
            todo.append(f"{i['title']}: {i['action']}")

        if margin >= self.engine.rule.min_log2fc:
            gap = "well past"
        elif margin >= 0:
            gap = f"{margin_pct} % beyond"
        else:
            gap = f"{margin_pct} % short"
        tiles = [
            {
                "label": "Fold change, planned analysis",
                "value": _fold(e["fold"]),
                "sub": f"likely {_range(*e['ci'])}",
            },
            {"label": "Same answer in", "value": same, "sub": REASONABLE},
            {
                "label": "p-value, planned analysis",
                "value": f"{e['p']:.2g}",
                "sub": f"a call needs below {self.alpha:g}",
            },
            {
                "label": "Fewest samples that change it",
                "value": str(dk) if dk else f"more than {rules['drop_k_searched']}",
                "sub": f"of {self.n_samples} samples",
            },
            *(
                [
                    {
                        "label": "Fewest moves that change it",
                        "value": (
                            (str(mv["distance"]) if mv["exact"] else f"at most {mv['distance']}")
                            if mv["distance"]
                            else f"none in {MAX_MOVES}"
                        ),
                        "sub": "reasonable choices or left-out samples, together",
                    }
                ]
                if mv
                else []
            ),
            {
                "label": f"Distance to the {line} line",
                "value": gap,
                "sub": "the size a call needs",
            },
            {
                "label": "Difference is clear in",
                "value": clear,
                "sub": f"{REASONABLE} (p below {self.alpha:g})",
            },
        ]

        return {
            "tiles": tiles,
            "gene": gene,
            "call_key": e["call"],
            "verdict": verdict,
            "label": VERDICT_LABEL[verdict],
            "headline_gene": gene in HEADLINE,
            "result": result,
            "holds": holds_block,
            "changes": changes,
            "no_changes": "No reasonable choice changes it." if not changes else None,
            "shortcut": shortcut_line,
            "leans": leans,
            "singles": singles,
            "todo": todo,
            "evidence": f"/evidence/{gene}",
        }

    def _singles(self, gene: str) -> list[dict]:
        if self.sample_flips is None:
            return []
        sf = self.sample_flips
        rows = sf[(sf["gene"] == gene) & sf["flips"]]
        return [
            {
                "sample": r.sample,
                "plate": r.plate,
                "well": r.well,
                "call": self.call_words(r.call),
                "call_key": r.call,
            }
            for r in rows.itertuples()
        ]

    # ---- live engine calls ------------------------------------------------------------
    def run_whatif(self, changes: dict[str, str], extra: list[str] | None = None) -> dict:
        for d, o in changes.items():
            self.space.decision(d).index(o)  # KeyError on an unknown decision or option
        changes = {d: o for d, o in changes.items() if self.space.baseline[d] != o}
        with self._engine_lock:
            table = whatif(self.engine, changes).set_index("gene")
        picked = [g for g in extra or [] if g in table.index]
        changed = table[table["call"] != table["base_call"]]
        labels = [
            self.space.decision(d).options[self.space.decision(d).index(o)].label
            for d, o in changes.items()
        ]
        rows = []
        for g in table.index:
            r = table.loc[g]
            rows.append(
                {
                    "gene": g,
                    "headline": g in HEADLINE,
                    "picked": g in picked,
                    "verdict": self.explain[g]["verdict"] if g in self.explain else "",
                    "base": _fold(r["base_fold"]),
                    "base_call": SHORT_CALL[r["base_call"]],
                    "base_call_key": r["base_call"],
                    "new": _fold(r["fold"]),
                    "new_call": SHORT_CALL[r["call"]],
                    "new_call_key": r["call"],
                    "base_log2": float(np.log2(r["base_fold"])),
                    "new_log2": float(np.log2(r["fold"])),
                    "changed": bool(r["call"] != r["base_call"]),
                }
            )
        return {
            "changes": labels,
            "rows": rows,
            "n_changed": len(changed),
            "n_genes": len(table),
            "changed_genes": list(changed.index),
            "line_log2": self.engine.rule.min_log2fc,
            "line": f"{self.line:g}×",
        }

    @property
    def asker(self):
        """The Ask engine; the first use pings the local model, which can take a minute."""
        with self._asker_lock:
            if self._asker is None:
                from qsim.ask import Asker

                self._asker = Asker(self.dir, client=self.ask_client, rdml=self._rdml)
            if self._asker._engine is None:
                # the screen's own engine, each call under the screen's engine lock: a slow
                # model answer never holds the lock, and no two calls run in the engine at once
                self._asker._engine = LockedEngine(self.engine, self._engine_lock)
        return self._asker

    def use_ask_client(self, client) -> None:
        """Answer Ask questions with this model client (the hosting page's own model)."""
        with self._asker_lock:
            self.ask_client = client
            if self._asker is not None:
                self._asker.client = client

    def model_status(self) -> dict:
        if self._asker is None or not self._asker_lock.acquire(blocking=False):
            return {"state": "checking"}
        try:
            client = self._asker.client
            return {"state": "ready", "available": client.available, "name": client.model}
        finally:
            self._asker_lock.release()

    def ask(self, question: str) -> dict:
        asker = self.asker
        with self._ask_lock:
            ans = asker.answer(question)
            _, meaning, _ = asker.facts_for(ans.tool, ans.args)
        written = (
            f"the local model ({ans.model}), with every number checked"
            if ans.written_by == "model"
            else "the engine's checked template"
        )
        shown_args = {k: v for k, v in ans.args.items() if v not in (None, [], {})}
        return {
            "question": question,
            "text": ans.text,
            "tool": ans.tool,
            "tool_words": TOOL_WORDS.get(ans.tool, ans.tool),
            "args": shown_args,
            "routed_by": ROUTED_WORDS.get(ans.routed_by, ans.routed_by)
            + (f" ({ans.model})" if ans.routed_by == "model" and ans.model else ""),
            "written_by": written,
            "facts": [
                {"id": fid, "meaning": meaning.get(fid, fid), "value": value}
                for fid, value in ans.facts.items()
            ],
            "routed_code": ans.routed_by,
            "written_code": ans.written_by,
            "model": ans.model,
            "problems": list(ans.problems),
        }

    # ---- the evidence page --------------------------------------------------------------
    def evidence_html(self, gene: str) -> str:
        if gene not in self.explain:
            raise KeyError(gene)
        e, r = self.explain[gene], self.genes.loc[gene]
        esc = _escape
        rows = []
        for col, label in EVIDENCE_LABELS.items():
            if col not in r.index:
                continue
            v = r[col]
            if _missing(v):
                v = "none"
            elif col in ("all_flipped_by_one", "defensible_flipped_by_one"):
                v = _join([PLAIN.get(d, d) for d in str(v).split(",")], "or")
            elif isinstance(v, float):
                v = f"{v:.4g}"
            rows.append(f"<tr><th>{esc(label)}</th><td>{esc(str(v))}</td></tr>")
        flips = (
            "".join(
                f"<tr><td>{esc(' and '.join(f['choices']))}</td><td>{esc(_fold(f['fold']))}</td>"
                f"<td>{esc(self.call_words(f['call']))}</td></tr>"
                for f in e["flips"]
            )
            or "<tr><td colspan=3>No reasonable choice changes the call.</td></tr>"
        )
        issues = []
        for i in self.issues:
            on_gene = i.get("loci", {}).get("gene") == gene
            if gene not in i.get("changed_calls", []) and not on_gene:
                continue
            v = self._issue_view(i)
            where = ", ".join(x for x in [v["plate"], " ".join(v["wells"][:12])] if x)
            issues.append(
                f"<li><b>{esc(v['title'])}</b> <span class=muted>(about {esc(v['about'])}"
                f"{'; ' + esc(where) if where else ''})</span><br>"
                f"Possible causes: {esc('; '.join(v['causes']))}<br>What to do: {esc(v['action'])}"
                f"<br><span class=muted>Changes the call of: "
                f"{esc(', '.join(v['changes']) or 'no gene')}</span></li>"
            )
            if len(issues) >= 12:
                break
        singles = ""
        if self.sample_flips is not None:
            sf = self.sample_flips[(self.sample_flips["gene"] == gene) & self.sample_flips["flips"]]
            singles = "".join(
                f"<tr><td>{esc(s.sample)}</td><td>{esc(s.plate)}</td><td>{esc(s.well)}</td>"
                f"<td>{esc(str(s.group))}</td><td>{esc(self.call_words(s.call))}</td></tr>"
                for s in sf.itertuples()
            )
        files = " · ".join(
            f'<a href="/files/{f}">{f}</a>' for f in RAW_FILES if (self.dir / f).exists()
        )
        prov = self.summary
        return _EVIDENCE.format(
            gene=esc(gene),
            verdict=esc(VERDICT_LABEL[e["verdict"]]),
            fold=esc(_fold(e["fold"])),
            call=esc(self.call_words(e["call"])),
            rng=esc(_range(*e["ci"])),
            p=esc(f"{e['p']:.3g}"),
            n=e["analyses_defensible"],
            rows="".join(rows),
            flips=flips,
            issues="".join(issues) or "<li>No issue in the queue changes this gene.</li>",
            singles=singles or "<tr><td colspan=5>No single sample changes the call.</td></tr>",
            files=files,
            run=esc(prov.get("grid_hash", "")),
            lock=esc(prov.get("lock_sha256", "")[:12]),
            input=esc(prov.get("input_sha256", "")[:12]),
            rules=esc(self.verdict_rules()[e["verdict"]]),
            source=esc(self.source),
        )


class LockedEngine:
    """An engine whose every method call holds ``lock`` (attributes are read as they are)."""

    def __init__(self, engine: Engine, lock) -> None:
        self._engine = engine
        self._lock = lock

    def __getattr__(self, name: str):
        value = getattr(self._engine, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            with self._lock:
                return value(*args, **kwargs)

        return call


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_EVIDENCE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Evidence: {gene}</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#1d232b;--muted:#5b6673;--line:#dde2e8;--link:#0b5cad}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171b;--card:#1d2127;--ink:#e6e9ed;--muted:#9aa5b1;--line:#323840;--link:#7db7f0}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
main{{max-width:900px;margin:0 auto;padding:24px 16px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin:16px 0}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:0 0 10px}}
table{{border-collapse:collapse;width:100%}} th,td{{text-align:left;padding:6px 8px;border-top:1px solid var(--line);vertical-align:top}}
th{{font-weight:500;color:var(--muted);width:55%}} .muted{{color:var(--muted)}} a{{color:var(--link)}}
li{{margin:0 0 10px}} code{{font-size:13px}}
</style></head><body><main>
<p><a href="/#gene={gene}">← back to the results screen</a></p>
<h1>Evidence for {gene}</h1>
<p class=muted>Read directly from the engine's files for {source}. Nothing on this page is typed by hand.</p>
<section><h2>The result</h2><table>
<tr><th>Verdict</th><td>{verdict}</td></tr>
<tr><th>Rule behind this verdict</th><td>{rules}</td></tr>
<tr><th>Fold change with the planned analysis</th><td>{fold}</td></tr>
<tr><th>Call</th><td>{call}</td></tr>
<tr><th>Likely range from this data</th><td>{rng}</td></tr>
<tr><th>p-value with the planned analysis</th><td>{p}</td></tr>
<tr><th>Reasonable analyses run</th><td>{n}</td></tr>
</table></section>
<section><h2>Choices that change the call (explain.json)</h2><table>
<tr><th>Choice</th><th>Fold change</th><th>Call</th></tr>{flips}</table></section>
<section><h2>Per-gene record (genes.csv)</h2><table>{rows}</table></section>
<section><h2>Single samples that change the call (one_sample_flips.csv)</h2><table>
<tr><th>Sample</th><th>Plate</th><th>Well</th><th>Group</th><th>Call without it</th></tr>{singles}</table></section>
<section><h2>Issues in the queue that touch {gene} (issues.json)</h2><ul>{issues}</ul></section>
<section><h2>Raw files and provenance</h2><p>{files}</p>
<p class=muted>Run <code>{run}</code> · locked choices <code>{lock}</code> · input data <code>{input}</code></p></section>
</main></body></html>"""
