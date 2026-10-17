"""Ask the simulator a question in plain words, answered by a local model with checked numbers.

The model is never trusted with a number. It works in two steps, the same design as qPilot's
"Ask your data":

1. **Route.** The model reads the question and replies with JSON naming one tool and its
   arguments: ``gene``, ``whatif``, ``decision``, ``issues`` or ``overview``. Names are checked
   against the study (genes, decisions, options). If the reply is unusable, a keyword router
   decides instead.
2. **Write.** The tool runs on the engine's results. Every number becomes a fact with an id, and
   the model writes 2-4 sentences that cite numbers only as ``{{fact_id}}`` tokens. qPilot's
   validator rejects any digit that is not a token. After one failed retry, a deterministic
   template answers instead, and the answer says so.

The default model is a local one: Ollama's OpenAI-compatible endpoint on this machine
(``qwen2.5:7b``). Set ``QPILOT_MODEL_*`` to use another, or pass ``--no-model`` for templates.
Nothing leaves the machine with the default.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from qpilot.ai.client import ModelClient, ModelUnavailable, OpenAICompatibleBackend
from qpilot.ai.config import ModelConfig
from qpilot.core.validator import render_tokens, validate
from qpilot.schemas import Fact

from qsim.compare import whatif
from qsim.data import load_study
from qsim.decisions import PLAIN, qpcr_space
from qsim.engine import Engine
from qsim.issues import HEADLINE
from qsim.study_space import space_for

LOCAL_DEFAULT = ModelConfig(
    provider="openai_compatible", endpoint="http://localhost:11434", model="qwen2.5:7b"
)
LOCAL_TIMEOUT_S = 180.0  # a 7B model on a laptop can take a minute when the machine is busy
TOOLS = ("gene", "whatif", "decision", "issues", "overview")
METHOD_PHRASES = ("2-fold", "p < 0.05", "95 %", "qPCR", "ddCq", "ΔΔCq")
KEYWORDS = {
    "refs": ("reference", "housekeeping", "normalis", "normaliz", "refs", "control gene"),
    "cut": ("cut-off", "cutoff", " cut ", "top 10", "top 20", "group definition"),
    "efficiency": ("efficiency", "100 %", "100%", "per well", "per-well"),
    "nondetect": ("non-detect", "nondetect", "undetermined", "cq 40", "cq40", "never amplified"),
    "test": ("test", "mann", "whitney", "student", "welch"),
    "multiplicity": ("multiple", "fdr", "benjamini", "holm", "correction"),
    "flagged": ("flagged", "outlier well", "exclude"),
}

ROUTE_SYSTEM = """You route a scientist's question about one qPCR study to ONE tool.
Reply with JSON only, no prose: {"tool": "<name>", "args": {...}}.
Tools:
- gene: {"gene": "<gene>"} - is this gene's result robust, what changes it, what it leans on.
- whatif: {"changes": {"<decision>": "<option>", ...}, "genes": ["<gene>", ...]} - recompute with other choices.
- decision: {"decision": "<decision>"} - how much one analysis choice matters across all genes.
- issues: {"n": 3} - what to check first in the data.
- overview: {} - how robust the study is overall.
Use only the names listed below."""

WHATIF_WORDS = (
    "what if",
    "if we",
    "if i",
    "instead",
    "switch",
    "suppose",
    "only ",
    " alone",
    "just ",
)
OPTION_WORDS = {
    "nondetect": [
        ("cap_min", ("cap", "lowest")),
        ("cq40", ("cq 40", "cq40", "cq of 40", "40 cycles")),
    ],
    "efficiency": [
        ("assume_100", ("100 %", "100%", "ddcq", "ΔΔcq", "assume")),
        ("per_well", ("per well", "per-well", "each well")),
    ],
    "cut": [
        ("top10", ("top 10", "top10", "10 %", "10%")),
        ("top20", ("top 20", "top20", "20 %", "20%")),
        ("top15", ("top 15", "top15")),
    ],
    "test": [
        ("mann_whitney", ("mann", "whitney", "rank test", "non-parametric", "nonparametric")),
        ("student", ("student",)),
        ("welch", ("welch",)),
    ],
    "multiplicity": [("bh", ("benjamini", "fdr", " bh")), ("holm", ("holm", "bonferroni"))],
    "flagged": [
        ("drop_eff_low", ("below 10 copies", "low copy", "low-copy")),
        ("drop_eff", ("flagged", "outlier well", "efficiency outlier")),
    ],
}
EXAMPLE_ROUTES = """Examples:
Q: Is BIRC5 robust? -> {"tool": "gene", "args": {"gene": "BIRC5"}}
Q: What if we normalise to HMBS alone and use the top 20 % cut? -> {"tool": "whatif", "args": {"changes": {"refs": "HMBS", "cut": "top20"}, "genes": []}}
Q: Does the multiple-testing correction matter? -> {"tool": "decision", "args": {"decision": "multiplicity"}}
Q: What should I look at first? -> {"tool": "issues", "args": {"n": 3}}"""

WRITE_SYSTEM = """You explain qPCR analysis results to a lab scientist in plain words (2-4 sentences).
Rules you must follow:
- Use ONLY the facts provided. Cite every number, fold change, percentage, count or option name that contains a number by writing its token exactly, like {{f_fold}}.
- Never type a digit yourself and never spell out a number. Gene names may be written as they are.
- No statistics jargon (no "fragility", "multiverse", "SE"). Say "reasonable analyses", "samples", "reference genes".
- Tokens already include their unit (× or %): never add a % or × after a token.
- Do not add claims that are not in the facts, and do not change what a fact means.
Example of the style: "NM23A is {{f_fold}} {{f_direction}} in MYCN-high tumours, but the call is {{f_verdict}}: it holds in {{f_holds}} of {{f_n_analyses}} reasonable analyses."
"""


@dataclass
class Answer:
    question: str
    tool: str
    args: dict
    text: str
    routed_by: str
    written_by: str
    model: str | None
    facts: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


class Asker:
    def __init__(
        self,
        results: str | Path = "results",
        client: ModelClient | None = None,
        rdml: str | None = None,
    ) -> None:
        self.dir = Path(results)
        self.explain = json.loads((self.dir / "explain.json").read_text())
        self.summary = json.loads((self.dir / "summary.json").read_text())
        self.decisions = pd.read_csv(self.dir / "decisions.csv").set_index("decision")
        self.issues = json.loads((self.dir / "issues.json").read_text())
        self.client = client if client is not None else default_client()
        self._rdml = rdml
        self._engine: Engine | None = None
        self.genes = list(self.explain)

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            study = load_study(self._rdml)
            self._engine = Engine(study, space_for(study)[0])
        return self._engine

    def names(self) -> list[str]:
        space = qpcr_space(
            tuple(self.summary["study"]["references"]), tuple(self.summary["study"]["references"])
        )
        out = list(self.genes) + list(space.names) + list(METHOD_PHRASES)
        for d in space.decisions:
            out += d.ids
        return out

    # ---- step 1: route ---------------------------------------------------------------
    def route(self, question: str) -> tuple[str, dict, str]:
        changes = self.parse_changes(question)
        if changes and any(w in question.lower() for w in WHATIF_WORDS):
            return "whatif", {"changes": changes, "genes": self._genes_in(question)}, "rules"
        if self.client.available:
            space_desc = self._space_desc()
            prompt = (
                f"Genes: {', '.join(self.genes)}\nDecisions and options:\n{space_desc}\n\n"
                f"{EXAMPLE_ROUTES}\n\nQuestion: {question}"
            )
            try:
                raw = self.client.complete(
                    ROUTE_SYSTEM, [{"role": "user", "content": prompt}], max_tokens=200
                )
                tool, args = self._parse_route(raw)
                if tool:
                    return tool, args, "model"
            except ModelUnavailable:
                pass
        tool, args = self._keyword_route(question)
        return tool, args, "keywords"

    def _space_desc(self) -> str:
        space = qpcr_space(
            tuple(self.summary["study"]["references"]), tuple(self.summary["study"]["references"])
        )
        lines = []
        for d in space.decisions:
            ids = (
                d.ids
                if d.id != "refs"
                else [o.id for o in d.options if o.tier != "common_practice"][:6]
                + ["HMBS", "SDHA", "...any subset joined by +"]
            )
            lines.append(f"- {d.id}: {', '.join(ids)}")
        return "\n".join(lines)

    def _parse_route(self, raw: str) -> tuple[str | None, dict]:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return None, {}
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None, {}
        tool, args = obj.get("tool"), obj.get("args") or {}
        if tool not in TOOLS or not isinstance(args, dict):
            return None, {}
        space = qpcr_space(
            tuple(self.summary["study"]["references"]), tuple(self.summary["study"]["references"])
        )
        if tool == "gene" and args.get("gene") not in self.genes:
            return None, {}
        if tool == "decision" and args.get("decision") not in space.names:
            return None, {}
        if tool == "whatif":
            changes = {
                d: self._normalise(space, d, str(v)) for d, v in (args.get("changes") or {}).items()
            }
            if not changes or any(v is None for v in changes.values()):
                return None, {}
            try:
                space.to_index(changes)
            except KeyError:
                return None, {}
            args["changes"] = changes
            args["genes"] = [g for g in args.get("genes") or [] if g in self.genes]
        return tool, args

    def _space(self):
        refs = tuple(self.summary["study"]["references"])
        return qpcr_space(refs, refs)

    def _normalise(self, space, decision: str, value: str) -> str | None:
        """Map a model's option name onto a real option id (case, prefixes, gene subsets)."""
        if decision not in space.names:
            return None
        ids = space.decision(decision).ids
        if value in ids:
            return value
        low = {i.lower(): i for i in ids}
        if value.lower() in low:
            return low[value.lower()]
        if decision == "refs":
            return self._refs_option(space, re.split(r"[+,& ]+", value))
        starts = [
            i
            for i in ids
            if i.lower().startswith(value.lower()) or value.lower().startswith(i.lower())
        ]
        return starts[0] if len(starts) == 1 else None

    def _refs_option(self, space, words: list[str]) -> str | None:
        options = space.decision("refs").options
        short = [g.split("(")[0] for g in options[-1].value]
        picked = [s for s in short if any(w.lower().startswith(s.lower()[:4]) for w in words if w)]
        if not picked:
            return None
        target = "+".join(s for s in short if s in picked)
        return target if target in [o.id for o in options] else None

    def parse_changes(self, question: str) -> dict[str, str]:
        """Rule-based reading of choices named in a question ("only HMBS", "top 20 %", "cap")."""
        q = question.lower()
        space = self._space()
        out: dict[str, str] = {}
        refs_words = re.findall(
            r"(?:only|just|alone|with|use|using|normali[sz]e to)\s+([a-z0-9+ ,&]+?)(?:\s+(?:as|alone|and|for|$)|[?.,]|$)",
            q,
        )
        short = [g.split("(")[0].lower() for g in space.decision("refs").options[-1].value]
        mentioned = [s for s in short if re.search(rf"(?<!\w){re.escape(s)}", q)]
        if mentioned and (
            "reference" in q or "normali" in q or "only" in q or "alone" in q or refs_words
        ):
            option = self._refs_option(space, mentioned)
            if option:
                out["refs"] = option
        for decision, rules in OPTION_WORDS.items():
            for option, words in rules:
                if any(w in q for w in words):
                    out[decision] = option
                    break
        return out

    def _genes_in(self, question: str) -> list[str]:
        q = question.lower()
        return [g for g in self.genes if re.search(rf"(?<!\w){re.escape(g.lower())}(?!\w)", q)]

    def _keyword_route(self, question: str) -> tuple[str, dict]:
        q = question.lower()
        gene = next(
            (
                g
                for g in sorted(self.genes, key=len, reverse=True)
                if re.search(rf"(?<!\w){re.escape(g.lower())}(?!\w)", q)
            ),
            None,
        )
        decision = next((d for d, words in KEYWORDS.items() if any(w in q for w in words)), None)
        if any(w in q for w in ("check", "inspect", "problem", "wrong", "issue")) and not gene:
            return "issues", {"n": 3}
        if gene:
            return "gene", {"gene": gene}
        if decision:
            return "decision", {"decision": decision}
        return "overview", {}

    # ---- step 2: facts and writing ----------------------------------------------------
    def facts_for(self, tool: str, args: dict) -> tuple[dict[str, Fact], dict[str, str], str]:
        return getattr(self, f"_facts_{tool}")(args)

    def _facts_gene(self, args: dict):
        gene = args["gene"]
        e = dict(self.explain[gene])
        focus = args.get("focus")
        if focus:
            e["flips"] = sorted(e["flips"], key=lambda f: focus not in f["decisions"])
        facts, meaning = {}, {}

        def add(fid, value, desc, fmt="{}", unit=""):
            facts[fid] = Fact(id=fid, value=value, fmt=fmt, unit=unit)
            meaning[fid] = desc

        add(
            "f_fold",
            e["fold"] if e["fold"] >= 1 else 1 / e["fold"],
            "fold change at baseline",
            "{:.2f}",
            "×",
        )
        add(
            "f_direction",
            "higher" if e["fold"] >= 1 else "lower",
            "direction in the MYCN-high group",
        )
        add(
            "f_call",
            {"up": "called up", "down": "called down", "none": "not called"}[e["call"]],
            "baseline call",
        )
        add("f_verdict", e["verdict"], "verdict (rule-based)")
        add(
            "f_holds",
            round(100 * e["holds_defensible"]),
            "share of reasonable analyses with the same call",
            "{}",
            " %",
        )
        add("f_n_analyses", e["analyses_defensible"], "number of reasonable analyses", "{:,}")
        add(
            "f_significant",
            round(100 * e["share_significant"]),
            "share of analyses where the difference itself is significant",
            "{}",
            " %",
        )
        add(
            "f_dropk",
            e["drop_k"] if e["drop_k"] else "more than five",
            "fewest samples whose removal changes the call",
        )
        for k, flip in enumerate(e["flips"][:3], start=1):
            choice = " and ".join(flip["choices"])
            add(
                f"f_flip{k}_choice",
                choice,
                f"a choice (or pair of choices) that changes the call #{k}",
            )
            fold = flip["fold"] if flip["fold"] >= 1 else 1 / flip["fold"]
            add(f"f_flip{k}_fold", fold, f"fold change under that choice #{k}", "{:.2f}", "×")
            add(
                f"f_flip{k}_call",
                {"up": "called up", "down": "called down", "none": "no longer called"}[
                    flip["call"]
                ],
                f"call under that choice #{k}",
            )
        if focus:
            space = self.engine.space
            i = self.engine.items.index(gene)
            base_call = self.engine.evaluate(space.baseline_index())["call"][i]
            results = []
            for opt in space.decision(focus).options:
                if opt.id == space.baseline[focus]:
                    continue
                r = self.engine.evaluate(space.to_index({focus: opt.id}))
                results.append((opt, float(2 ** r["log2fc"][i]), int(r["call"][i])))
            flips = [o.id for o, _, c in results if c != base_call]
            folds = [f if f >= 1 else 1 / f for _, f, _ in results]
            add("f_focus", PLAIN[focus], "the choice asked about")
            add("f_focus_n", len(results), "number of other options for that choice")
            add("f_focus_flips", len(flips), "how many of those options change the call")
            add("f_focus_which", ", ".join(flips[:4]) or "none", "options that change the call")
            add(
                "f_focus_min",
                min(folds),
                "smallest fold change across those options",
                "{:.2f}",
                "×",
            )
            add(
                "f_focus_max", max(folds), "largest fold change across those options", "{:.2f}", "×"
            )
        t = f"{gene} is {{{{f_fold}}}} {{{{f_direction}}}} in MYCN-high tumours and is {{{{f_call}}}} ({{{{f_verdict}}}}). "
        if focus:
            t += "Changing {{f_focus}} alone ({{f_focus_n}} alternatives) gives {{f_focus_min}} to {{f_focus_max}}; {{f_focus_flips}} of them change the call ({{f_focus_which}}). "
        t += "The same call holds in {{f_holds}} of {{f_n_analyses}} reasonable analyses"
        t += "; the difference itself is significant in {{f_significant}} of them. "
        if e["flips"]:
            t += "It changes with {{f_flip1_choice}}: {{f_flip1_fold}}, {{f_flip1_call}}. "
        else:
            t += "No reasonable choice in the simulator changes the call. "
        t += (
            "Removing {{f_dropk}} sample(s) would change it."
            if e["drop_k"]
            else "No five samples or fewer carry the call."
        )
        return facts, meaning, t

    def _facts_whatif(self, args: dict):
        changes = args.get("changes") or {}
        table = whatif(self.engine, changes).set_index("gene")
        genes = args.get("genes") or [g for g in HEADLINE if g in table.index]
        space = self.engine.space
        facts, meaning = {}, {}

        def add(fid, value, desc, fmt="{}", unit=""):
            facts[fid] = Fact(id=fid, value=value, fmt=fmt, unit=unit)
            meaning[fid] = desc

        labels = [
            space.decision(d).options[space.decision(d).index(o)].label for d, o in changes.items()
        ]
        add("f_changes", " and ".join(labels) or "the baseline choices", "the choices changed")
        add(
            "f_n_changed",
            int((table["call"] != table["base_call"]).sum()),
            "number of genes whose call changes",
        )
        add("f_n_genes", len(table), "number of genes compared")
        parts = []
        for k, g in enumerate(genes[:4], start=1):
            r = table.loc[g]
            add(
                f"f_g{k}_base",
                r["base_fold"] if r["base_fold"] >= 1 else 1 / r["base_fold"],
                f"{g} fold change at baseline",
                "{:.2f}",
                "×",
            )
            add(
                f"f_g{k}_new",
                r["fold"] if r["fold"] >= 1 else 1 / r["fold"],
                f"{g} fold change with the new choices",
                "{:.2f}",
                "×",
            )
            add(
                f"f_g{k}_call",
                {"up": "up", "down": "down", "none": "no call"}[r["call"]],
                f"{g} call with the new choices",
            )
            add(
                f"f_g{k}_base_call",
                {"up": "up", "down": "down", "none": "no call"}[r["base_call"]],
                f"{g} call at baseline",
            )
            parts.append(
                f"{g} goes from {{{{f_g{k}_base}}}} ({{{{f_g{k}_base_call}}}}) to {{{{f_g{k}_new}}}} ({{{{f_g{k}_call}}}})"
            )
        t = (
            "With {{f_changes}}, "
            + "; ".join(parts)
            + ". Overall {{f_n_changed}} of {{f_n_genes}} calls change."
        )
        return facts, meaning, t

    def _facts_decision(self, args: dict):
        d = args["decision"]
        row = self.decisions.loc[d]
        space = qpcr_space(
            tuple(self.summary["study"]["references"]), tuple(self.summary["study"]["references"])
        )
        flipped = [
            g for g, e in self.explain.items() if any(f["decisions"] == [d] for f in e["flips"])
        ]
        facts = {
            "f_question": Fact(id="f_question", value=space.decision(d).question),
            "f_n_alone": Fact(id="f_n_alone", value=int(row["genes_flipped_alone"])),
            "f_share": Fact(
                id="f_share", value=round(100 * float(row["variance_share_defensible"])), unit=" %"
            ),
            "f_examples": Fact(id="f_examples", value=", ".join(flipped[:5]) or "none"),
        }
        meaning = {
            "f_question": "the decision",
            "f_n_alone": "genes whose call changes with this choice alone",
            "f_share": "share of fold-change variation due to this choice",
            "f_examples": "example genes",
        }
        t = "{{f_question}} On its own this choice changes {{f_n_alone}} calls and accounts for {{f_share}} of the variation in fold changes across reasonable analyses. Examples: {{f_examples}}."
        return facts, meaning, t

    def _facts_issues(self, args: dict):
        n = min(int(args.get("n", 3) or 3), 5)
        facts, meaning, lines = {}, {}, []
        for k, issue in enumerate(self.issues[:n], start=1):
            facts[f"f_i{k}_title"] = Fact(id=f"f_i{k}_title", value=issue["title"])
            facts[f"f_i{k}_action"] = Fact(id=f"f_i{k}_action", value=issue["action"])
            meaning[f"f_i{k}_title"] = f"issue #{k}"
            meaning[f"f_i{k}_action"] = f"what to do about issue #{k}"
            lines.append(f"{{{{f_i{k}_title}}}}: {{{{f_i{k}_action}}}}")
        return facts, meaning, " ".join(lines)

    def _facts_overview(self, args: dict):
        counts = pd.Series([e["verdict"] for e in self.explain.values()]).value_counts().to_dict()
        facts = {
            "f_n_genes": Fact(id="f_n_genes", value=len(self.explain)),
            "f_n_analyses": Fact(
                id="f_n_analyses", value=self.summary["ledger"]["total_cells"], fmt="{:,}"
            ),
            "f_solid": Fact(id="f_solid", value=counts.get("solid", 0)),
            "f_depends": Fact(id="f_depends", value=counts.get("depends on your choices", 0)),
            "f_fragile": Fact(id="f_fragile", value=counts.get("fragile", 0)),
            "f_check": Fact(id="f_check", value=counts.get("check data first", 0)),
        }
        meaning = {k: k[2:].replace("_", " ") for k in facts}
        t = "Across {{f_n_analyses}} analyses of {{f_n_genes}} genes: {{f_solid}} calls are solid, {{f_depends}} depend on your choices, {{f_fragile}} are fragile and {{f_check}} need a data check first."
        return facts, meaning, t

    def answer(self, question: str) -> Answer:
        tool, args, routed_by = self.route(question)
        if tool == "gene":
            q = question.lower()
            args = {
                "gene": args["gene"],
                "focus": next(
                    (d for d, words in KEYWORDS.items() if any(w in q for w in words)),
                    None,
                ),
            }
        facts, meaning, template = self.facts_for(tool, args)
        names = self.names()
        table = "\n".join(
            f"{fid}: {meaning[fid]} = {render_tokens('{{' + fid + '}}', facts)}" for fid in facts
        )
        problems: list[str] = []
        if self.client.available:
            messages = [
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nFacts (cite as tokens):\n{table}",
                }
            ]
            for _ in range(2):
                try:
                    draft = self.client.complete(WRITE_SYSTEM, messages, max_tokens=300)
                except ModelUnavailable as err:
                    problems.append(str(err))
                    break
                draft = re.sub(r"(\}\})\s*(%|×)", r"\1", draft)
                check = validate(draft, facts, names)
                if check.ok:
                    return Answer(
                        question,
                        tool,
                        args,
                        render_tokens(draft, facts),
                        routed_by,
                        "model",
                        self.client.model,
                        _rendered(facts),
                        problems,
                    )
                problems.append(check.error())
                messages += [
                    {"role": "assistant", "content": draft},
                    {
                        "role": "user",
                        "content": f"Rejected: {problems[-1]}. Rewrite using only tokens for numbers.",
                    },
                ]
        return Answer(
            question,
            tool,
            args,
            render_tokens(template, facts),
            routed_by,
            "template",
            self.client.model,
            _rendered(facts),
            problems,
        )


def _rendered(facts: dict[str, Fact]) -> dict[str, str]:
    return {fid: render_tokens("{{" + fid + "}}", facts) for fid in facts}


def default_client() -> ModelClient:
    """The configured model, else the local Ollama default if it answers, else none."""
    if os.environ.get("QPILOT_MODEL_PROVIDER"):
        return ModelClient.from_env()
    client = ModelClient(backend=OpenAICompatibleBackend(LOCAL_DEFAULT, timeout=LOCAL_TIMEOUT_S))
    try:
        return client if client.ping() else ModelClient(config=ModelConfig())
    except Exception:
        return ModelClient(config=ModelConfig())
