"""``qsim app``: a local results screen for qPCR scientists, in plain lab language.

It serves one page from 127.0.0.1 only. The page loads no web assets and nothing leaves the
machine (Ask uses the local Ollama model when it is running). It reads the engine's files in
``results/``:

* ``explain.json``: verdict, call, fold change and the choices that change each gene;
* ``genes.csv``: per-gene holds, margins and samples that carry the call;
* ``issues.json``: the investigation queue;
* ``summary.json``: the study, the verdict rules and the run's provenance.

It calls the engine live for the what-if panel (:func:`qsim.compare.whatif`) and the Ask box
(:class:`qsim.ask.Asker`). The page never types a number: every figure is read from those files
or returned by the engine. The sentences around the figures are fixed wording, and statistics
jargon stays off the screen.
"""

from __future__ import annotations

import json
import math
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd

from qsim.compare import whatif
from qsim.data import load_study
from qsim.decisions import PLAIN
from qsim.engine import Engine
from qsim.issues import HEADLINE
from qsim.study_space import space_for
from qsim.verdict import ORDER

HOST = "127.0.0.1"
PAGE = Path(__file__).with_name("app_page.html")
RAW_FILES = ("explain.json", "genes.csv", "issues.json", "summary.json", "one_sample_flips.csv")

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
    "defensible_holds": "Share of reasonable analyses with the same call",
    "defensible_flipped_by_one": "A single reasonable choice that changes the call",
    "defensible_interaction_only": "Changes only when two choices change together",
    "all_holds": "Share of all analyses, shortcuts included, with the same call",
    "all_flipped_by_one": "A single choice, shortcuts included, that changes the call",
    "fold_margin_log2": "Distance from the fold-change line (log2 units)",
    "p_margin_decades": "How far the p-value is below the line (powers of ten)",
    "samples_whose_removal_flips": "Single samples whose removal changes the call",
    "drop_k_to_flip": "Fewest samples whose removal changes the call",
    "share_forks_significant_same_direction": "Share of analyses where the difference is clear",
    "p_global": "p-value across reasonable analyses, all genes tested together",
    "q_global_bh": "The same, corrected for testing many genes",
    "verdict": "Verdict",
}


def _per100(share: float) -> int:
    return int(round(100 * float(share)))


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


class Screen:
    """Everything the page shows, built from the engine's files and live engine calls."""

    def __init__(self, results: str | Path = "results", rdml: str | None = None, asker=None):
        self.dir = Path(results)
        self.explain: dict = json.loads((self.dir / "explain.json").read_text())
        self.genes = pd.read_csv(self.dir / "genes.csv").set_index("gene")
        self.issues: list[dict] = json.loads((self.dir / "issues.json").read_text())
        self.summary: dict = json.loads((self.dir / "summary.json").read_text())
        flips = self.dir / "one_sample_flips.csv"
        self.sample_flips = pd.read_csv(flips, dtype={"sample": str}) if flips.exists() else None
        study = load_study(rdml)
        self.engine = Engine(study, space_for(study)[0])
        self.space = self.engine.space
        self.rules = self.summary["verdicts"]["rules"]
        self.line = 2**self.engine.rule.min_log2fc
        self.alpha = self.engine.rule.alpha
        marker = study.marker.split("(")[0]
        cut = self.space.decision("cut")
        self.group = f"{marker}-high"
        self.group_def = cut.options[cut.index(self.space.baseline["cut"])].label
        self.n_samples = self.summary["study"]["samples"]
        self._asker = asker
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
                f"Same call in at least {_per100(r['solid_holds'])} of 100 reasonable analyses, "
                f"no {r['drop_k_searched']} or fewer samples change it, and the difference is "
                f"clear in at least {_per100(r['solid_significant'])} of 100."
            ),
            "holds with caveats": (
                f"Same call in at least {_per100(r['solid_holds'])} of 100 reasonable analyses, "
                f"but {r['drop_k_searched']} or fewer samples change it, or the difference is "
                "not always clear."
            ),
            "depends on your choices": (
                f"Same call in {_per100(r['fragile_holds'])} to {_per100(r['solid_holds'])} of "
                "100 reasonable analyses: the rest depend on the choices made."
            ),
            "fragile": (
                f"Same call in fewer than {_per100(r['fragile_holds'])} of 100 reasonable "
                f"analyses, or {r['fragile_drop_k']} or fewer samples change it, or it sits "
                f"within {_per100(2 ** r['fragile_margin_log2'] - 1)} % of the {line} line."
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
        return {
            "study": {
                "samples": study["samples"],
                "genes": study["genes_compared"],
                "plates": study["plates"],
                "group": self.group,
                "group_def": self.group_def,
                "analyses": self.summary["ledger"]["total_cells"],
                "reasonable": self.explain[genes[0]]["analyses_defensible"],
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
                    "verdict": self.explain[g]["verdict"],
                    "label": VERDICT_LABEL[self.explain[g]["verdict"]],
                    "headline": g in HEADLINE,
                }
                for g in genes
            ],
            "headline": [g for g in HEADLINE if g in self.explain],
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
        holds, sig = _per100(e["holds_defensible"]), _per100(e["share_significant"])
        dk = e["drop_k"]
        margin = e["fold_margin_log2"]
        margin_pct = _per100(2 ** abs(margin) - 1)
        data_issues = self._data_issues(gene)
        flip_decisions = sorted({d for f in e["flips"] for d in f["decisions"]})

        # 1. the result and the verdict sentence
        verdict = e["verdict"]
        if verdict == "solid":
            why = (
                f"Same call in {holds} of 100 reasonable analyses, and no "
                f"{rules['drop_k_searched']} or fewer samples change it."
            )
        elif verdict == "holds with caveats":
            why = f"Same call in {holds} of 100 reasonable analyses, but " + (
                f"removing {dk} samples changes it."
                if dk
                else f"the difference is clear in only {sig} of 100 of them."
            )
        elif verdict == "depends on your choices":
            why = (
                f"Same call in {holds} of 100 reasonable analyses; the others turn on "
                f"{_join([PLAIN[d] for d in flip_decisions]) if flip_decisions else 'your choices'}."
            )
        elif verdict == "fragile":
            reasons = []
            if e["holds_defensible"] < rules["fragile_holds"]:
                reasons.append(f"same call in only {holds} of 100 reasonable analyses")
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
                f"{holds} of 100 reasonable analyses agree there is no call."
            )
        result = {
            "headline": f"{gene} is {_fold(e['fold'])} in {self.group} samples than in the rest.",
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
            "lines": [
                f"{e['analyses_defensible']} reasonable analyses were run: every combination "
                "of choices a careful lab could defend.",
                f"The difference itself is clear (p below {self.alpha:g}) in {sig} of 100 of them.",
                "Across every option tried, common shortcuts and other group cut-offs included "
                f"({self.summary['ledger']['total_cells']:,} analyses), the same answer comes "
                f"out in {all_holds} of 100.",
            ],
        }

        # 3. what changes it
        changes = [
            {
                "choice": " and ".join(f["choices"]),
                "fold": _fold(f["fold"]),
                "call": self.call_words(f["call"]),
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
                    "Some reasonable analyses would call it, so do not report it as unchanged "
                    "without saying so."
                )
        for i in data_issues[:3]:
            todo.append(f"{i['title']}: {i['action']}")

        return {
            "gene": gene,
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
            {"sample": r.sample, "plate": r.plate, "well": r.well, "call": self.call_words(r.call)}
            for r in rows.itertuples()
        ]

    # ---- live engine calls ------------------------------------------------------------
    def run_whatif(self, changes: dict[str, str], extra: list[str] | None = None) -> dict:
        for d, o in changes.items():
            self.space.decision(d).index(o)  # KeyError on an unknown decision or option
        changes = {d: o for d, o in changes.items() if self.space.baseline[d] != o}
        with self._engine_lock:
            table = whatif(self.engine, changes).set_index("gene")
        genes = [g for g in HEADLINE if g in table.index]
        genes += [g for g in extra or [] if g in table.index and g not in genes]
        changed = table[table["call"] != table["base_call"]]
        labels = [
            self.space.decision(d).options[self.space.decision(d).index(o)].label
            for d, o in changes.items()
        ]
        return {
            "changes": labels,
            "rows": [
                {
                    "gene": g,
                    "headline": g in HEADLINE,
                    "base": _fold(table.loc[g, "base_fold"]),
                    "base_call": SHORT_CALL[table.loc[g, "base_call"]],
                    "new": _fold(table.loc[g, "fold"]),
                    "new_call": SHORT_CALL[table.loc[g, "call"]],
                    "changed": bool(table.loc[g, "call"] != table.loc[g, "base_call"]),
                }
                for g in genes
            ],
            "n_changed": len(changed),
            "n_genes": len(table),
            "changed_genes": list(changed.index),
        }

    @property
    def asker(self):
        """The Ask engine; the first use pings the local model, which can take a minute."""
        with self._asker_lock:
            if self._asker is None:
                from qsim.ask import Asker

                self._asker = Asker(self.dir, rdml=self._rdml)
            if self._asker._engine is None:
                self._asker._engine = self.engine
        return self._asker

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
                {"meaning": meaning.get(fid, fid), "value": value}
                for fid, value in ans.facts.items()
            ],
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
        )


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
<p class=muted>Read directly from the engine's files in results/. Nothing on this page is typed by hand.</p>
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


def make_handler(screen: Screen) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "qsim-app"

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200) -> None:
            self._send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            path = unquote(urlparse(self.path).path)
            try:
                if path in ("/", "/index.html"):
                    self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                elif path == "/api/model":
                    self._json(screen.model_status())
                elif path == "/api/overview":
                    self._json(screen.overview())
                elif path.startswith("/api/gene/"):
                    self._json(screen.gene_card(path.removeprefix("/api/gene/")))
                elif path.startswith("/evidence/"):
                    html = screen.evidence_html(path.removeprefix("/evidence/"))
                    self._send(200, html.encode(), "text/html; charset=utf-8")
                elif path.startswith("/files/") and path.removeprefix("/files/") in RAW_FILES:
                    name = path.removeprefix("/files/")
                    ctype = "application/json" if name.endswith(".json") else "text/csv"
                    self._send(200, (screen.dir / name).read_bytes(), f"{ctype}; charset=utf-8")
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except KeyError as err:
                self._json({"error": f"unknown: {err}"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", "0") or 0)
            try:
                body = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
            except json.JSONDecodeError:
                self._json({"error": "bad JSON"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                if path == "/api/whatif":
                    self._json(screen.run_whatif(body.get("changes") or {}, body.get("genes")))
                elif path == "/api/ask":
                    question = str(body.get("question", "")).strip()[:500]
                    if not question:
                        self._json({"error": "empty question"}, HTTPStatus.BAD_REQUEST)
                    else:
                        self._json(screen.ask(question))
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except KeyError as err:
                self._json({"error": str(err)}, HTTPStatus.BAD_REQUEST)

    return Handler


def serve(
    results: str | Path = "results",
    rdml: str | None = None,
    port: int = 8765,
    no_model: bool = False,
    open_browser: bool = False,
) -> None:
    asker = None
    if no_model:
        from qpilot.ai.client import ModelClient
        from qpilot.ai.config import ModelConfig

        from qsim.ask import Asker

        asker = Asker(results, client=ModelClient(config=ModelConfig()), rdml=rdml)
    print("loading the study and the engine's results ...", flush=True)
    screen = Screen(results, rdml=rdml, asker=asker)

    def warm() -> None:  # the page is usable while the local model loads
        client = screen.asker.client
        print(
            "Ask reads questions with "
            + (f"the local model {client.model}" if client.available else "keyword matching"),
            flush=True,
        )

    threading.Thread(target=warm, daemon=True).start()
    httpd = ThreadingHTTPServer((HOST, port), make_handler(screen))
    url = f"http://{HOST}:{httpd.server_address[1]}/"
    print(f"qPilot results screen on {url} (this machine only; Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
