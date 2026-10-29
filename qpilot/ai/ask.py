"""Ask your data: a plain question answered from engine tools, with every number traceable.

Two steps, portable to any endpoint (no native tool calling needed):

1. The model replies with JSON ``{"tool": ..., "args": {...}}`` naming one of ``qpcr_study``,
   ``qpcr_robustness``, ``qpcr_decide``, ``qpcr_plan``, ``qpcr_trace``, ``explain_number`` (or
   ``none``).
   qPilot runs it in-process against the same on-disk store and the same tool code as the MCP
   server, so an in-app model has exactly an external agent's powers, including the
   ``pending_human`` answer on choices that can change a conclusion.
2. The model writes the answer from the tool result, in which every number has been replaced by
   a ``{{fact_id}}`` token; the answer is validated, retried once, else a template answers.

With no model (provider ``none``) a keyword router picks the tool and a template answers.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from qpilot.ai import payload_log
from qpilot.ai.client import ModelClient, ModelUnavailable
from qpilot.ai.explain import KIND_TITLE, card_names, fact_table
from qpilot.ai.profile import Profile, build_fewshots
from qpilot.ai.prompts import SYSTEM_ASK_ANSWER, SYSTEM_ASK_TOOL
from qpilot.core.decisions import needs_human
from qpilot.core.store import StudyStore
from qpilot.core.validator import names_from_result, render_tokens, validate
from qpilot.qpcr.confidence_checks import METHOD_PHRASES
from qpilot.schemas import DecisionCard, Fact, StudyResult

TOOLS = (
    "qpcr_study",
    "qpcr_robustness",
    "qpcr_decide",
    "qpcr_plan",
    "qpcr_trace",
    "explain_number",
    "none",
)
TRACE_ARGS = ("gene", "sample", "well")  # exactly one, as text
# "trace ...", "where should I look", "what should I check", "why is X no call" (not a what-if)
TRACE_WORDS = re.compile(
    r"\btrac(e|ing)\b|\bwhere\s+(should|do|can|would|must)\s+(i|we|you)\s+(look|check)\b|"
    r"\bwhere\s+to\s+(look|check)\b|\bwhat\s+(should|do|must)\s+(i|we)\s+check\b",
    re.I,
)
TRACE_WHY = re.compile(
    r"\bwhy\s+(is|isn'?t|does|doesn'?t|did|didn'?t|was|wasn'?t|has|hasn'?t)\b", re.I
)
WHAT_IF = re.compile(r"\b(if|suppose|would|instead)\b", re.I)
WELL_IN_TEXT = re.compile(r"(?<![\w()\-.])([\w()\-.]+)[:/]([A-Za-z]{1,2}\d{1,3})(?!\w)")
# a sample id after "sample", "tumour"...; it must carry a digit ("sample 2016", "mouse-c1")
SAMPLE_IN_TEXT = re.compile(
    r"\b(?:sample|tumou?r|patient|subject)\s+([\w()\-.]*\d[\w()\-.]*)", re.I
)
TRACE_CALL_WORDS = {"up": "up", "down": "down", "none": "no call"}
# Trace's addresses reach a model as tokens only, never as the names they stand for
ADDRESS_FACT = re.compile(r"^f_ans_trace_(root|\d+_(sample|plate|well))$")
HIDDEN_ADDRESS = "a sample, plate or well name, not shown; write the token to name it"
TRACE_NO_ROOT = (
    "qPilot could not trace that. Name one gene, one sample, or a plate and well "
    "(PLATE:WELL) from this study."
)
NOTHING_TEXT = {
    "nothing_to_look_at": "Trace found nothing unusual behind it; the wells read as expected.",
    "choice_to_look_at": (
        "Trace found nothing unusual in the wells; an analysis choice can change it, so look at "
        "the Decision Cards."
    ),
    "absent": "It is in no comparison; trace the sample to see which well left it out.",
}
# qpcr_plan arguments a model may pass (the replicate budget included); counts are whole numbers
PLAN_ARGS = frozenset(
    {
        "fc",
        "sd_log2",
        "n_per_group",
        "alpha",
        "power",
        "sd_rt",
        "sd_well",
        "n_rt",
        "n_tech",
        "cost_subject",
        "cost_rt",
        "cost_well",
        "expected_cq",
    }
)
PLAN_INT_ARGS = ("n_rt", "n_tech")
NOT_IN_STUDY = "not in this study"
NOT_UNDERSTOOD = "not understood"
#: What ``qpcr_study`` can be asked about (``args.about``); without it, the study's size.
STUDY_TOPICS = ("overview", "calls", "references", "cards")
PENDING_TEXT = (
    "Not applied: this choice can change a conclusion, so a person must decide it in qPilot. "
    "The request is waiting for their review."
)
SUGGEST_TEXT = (
    "Not applied: in Suggest mode a person confirms every choice in qPilot. "
    "The request is waiting for their review."
)
STALE_TEXT = "Not applied: the card changed since it was read; read it again."
# A negated or what-if sentence is not a request to change anything.
NOT_A_REQUEST = re.compile(
    r"\b(do\s+not|don'?t|never|not\s+to|shouldn'?t|should\s+not|why|what\s+if|"
    r"what\s+happens|what\s+would|would\s+it|if\s+(i|we|you)|suppose|hypothetically|without)\b",
    re.I,
)
NUMBER_WORDS = {"five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twenty-five": 25, "thirty": 30}
DECIDE_WORDS = re.compile(
    r"\b(apply|switch|use|set|change|normali[sz]e|pick|choose|make|replace|swap|select|"
    r"go with|adopt|move to|cut at|instead)\b",
    re.I,
)
ONLY_WORDS = re.compile(r"\b(only|alone|just|single|solely|sole)\b", re.I)
# "the reference gene", "normalise to X", "as the control": one gene in the role, i.e. X alone.
SOLE_ROLE = re.compile(
    r"\bthe\s+(reference|control|housekeeping|normali[sz]ing)\s+gene\b|"
    r"\bnormali[sz]e\s+(it\s+|them\s+|everything\s+)?(to|against|on|by|with)\b|"
    r"\bas\s+(the\s+)?(reference|control|housekeeping|normali[sz]er)\b",
    re.I,
)
CLAIMS_DONE = re.compile(
    r"\b(i\s+(have\s+|'ve\s+)?(applied|switched|changed|set|updated|made|used)|"
    r"(has|have)\s+been\s+(applied|switched|changed|updated|set)|"
    r"(applied|switched|changed)\s+(the|it|to)|now\s+(uses|normali[sz]ed)|(is|are)\s+now|"
    r"from\s+now\s+on|no\s+(human\s+|further\s+)?review\s+(is\s+)?(needed|required)|"
    r"(choice|decision|change|selection)\s+(is|has\s+been|was)\s+(recorded|logged|saved|made|"
    r"applied))\b|\bdone[.,:!]",
    re.I,
)
GENE_LIKE = re.compile(r"\b[A-Z][A-Z0-9]{2,}[A-Z0-9_()\-]*\b")
# What a question about the whole study asks for (keyword routing; see study_topic).
ASKS_WHICH = re.compile(r"\b(which|what|how\s+many|list|name|show)\b", re.I)
GENES_WORD = re.compile(r"\b(genes?|targets?|transcripts?)\b", re.I)
CALL_WORDS = re.compile(
    r"\b(up|down|higher|lower|increased|decreased|elevated|reduced|(up|down)[\s-]?regulated|"
    r"changed?|differ(ent|s)?|significant(ly)?|called|calls?)\b",
    re.I,
)
REFERENCE_WORDS = re.compile(
    r"\b(reference|control|housekeeping|normali[sz]\w*)\s+(genes?|set)\b|\bgenorm\b", re.I
)
STABLE_WORDS = re.compile(r"\b(stable|stability|steadi\w*|best|rank\w*|genorm)\b", re.I)
CHOICE_TOPICS = re.compile(
    r"\b(reference|control|housekeeping|normali[sz]\w*|cut(-?off)?|threshold|empty\s+wells?|"
    r"undetermined|never\s+amplif\w*|non-?detects?|curves?|amplification|choices?|decisions?|"
    r"cards?)\b",
    re.I,
)
CHANGE_WORDS = re.compile(r"\b(change|flip|depend|matter|affect|switch)\w*\b", re.I)
OVERVIEW_WORDS = re.compile(
    r"\b(study|samples?|plates?|reactions?|wells?|size|overview|summary|summari[sz]e|design|"
    r"groups?|panel)\b|\bhow\s+many\s+genes\b",
    re.I,
)
CONCLUSION_WORDS = {"up": "higher", "down": "lower", "none": "not clearly different (no call)"}


class AskResult(BaseModel):
    """An answer, the same text with numbers rendered, the tool calls, and how it was made."""

    question: str
    answer: str
    plain: str
    tool_calls: list[dict[str, Any]]
    validated: bool
    fallback: bool
    provider: str
    status: str | None = None
    error: str | None = None
    rejected_drafts: int = 0
    facts: dict[str, Fact] = {}
    tool_from_model: bool = False


def _fact(fid: str, value: Any, fmt: str = "{}", unit: str = "", path: str = "answer") -> Fact:
    return Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path)


class _Context:
    """Everything one question needs: the store, the study, its cards and allowed names."""

    def __init__(self, store: StudyStore, study_id: str) -> None:
        from qpilot.mcp_server import QpilotTools  # same tool code as the MCP server

        self.store = store
        self.study_id = study_id
        self.result: StudyResult = store.get(study_id)
        self.cards: list[DecisionCard] = store.cards(study_id)
        self.tools = QpilotTools(store, agent_policy=False)  # the app applies its own toggle
        self.names = names_from_result(self.result)
        for card in self.cards:
            self.names |= card_names(card)
        self.names |= set(self.result.design.group_var.split("_"))
        self.names |= set(METHOD_PHRASES)  # the grader's thresholds, as its notes word them

        self.alias: tuple[str, str] | None = None  # (as written, the study's name) of an alias

    def gene(self, text: str) -> str | None:
        """The compared gene a question names, by name, assay name or HGNC alias (survivin).

        The same resolver as the Claim Auditor (:func:`qpilot.claims.lexicon.find_genes`); the
        longest name written wins. A gene found by an alias is remembered, so the answer can say
        which gene it is about.
        """
        from qpilot.claims.lexicon import find_genes

        hits = find_genes(text, self.result.contrasts)
        if not hits:
            return None
        hit = max(hits, key=lambda f: len(f.written))
        self.alias = (hit.written, hit.gene) if hit.via == "alias" else None
        return hit.gene

    def other_groups(self, text: str) -> str | None:
        """A sentence when the question names groups the study does not compare, else None."""
        from qpilot.claims.lexicon import Lexicon

        lex = Lexicon.from_study(self.result)
        other = next((g for g in lex.groups(text) if g.which == "other"), None)
        if other is None or any(g.which != "other" for g in lex.groups(text)):
            return None
        if lex.basis and lex.group_b == "rest":
            short = lex.basis.removesuffix(" expression")
            ours = f"{lex.group_a} against {short}-low expression (the rest)"
        else:
            ours = f"{lex.group_a} against {lex.group_b}"
        return f"This study compares {ours}, not {other.what}; for its own groups: "


# ---- running a tool and turning its numbers into facts ------------------------------------


def run_tool(ctx: _Context, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute one tool call in-process; unknown tools come back as an error."""
    if tool == "qpcr_study":
        r = ctx.result
        out: dict[str, Any] = {
            "n_plates": r.n_plates,
            "n_samples": r.n_samples,
            "n_reactions": r.n_reactions,
            "n_genes": len(r.contrasts),
            "group": r.design.group_var,
            "open_cards": [c.id for c in ctx.cards if c.status in ("open", "pending_human")],
        }
        about = args.get("about")
        if about == "calls":
            calls = {g: c.conclusion for g, c in r.contrasts.items()}
            out |= {
                "about": "calls",
                "up": sorted(g for g, c in calls.items() if c == "up"),
                "down": sorted(g for g, c in calls.items() if c == "down"),
                "n_no_call": sum(c == "none" for c in calls.values()),
            }
        elif about == "references":
            genorm = r.genorm
            out |= {
                "about": "references",
                "order": list(genorm.order),
                "M": {g: genorm.M_initial[g] for g in genorm.order if g in genorm.M_initial},
                "recommended": list(genorm.recommended),
                "cutoff_M": genorm.cutoff_M,
            }
        elif about == "cards":
            out |= {
                "about": "cards",
                "cards": [
                    {"card_id": c.id, "kind": c.kind, "n_flipped": c.impact.get("n_genes_flipped")}
                    for c in sorted(ctx.cards, key=lambda c: c.rank)
                ],
            }
        return out
    if tool == "qpcr_robustness":
        return ctx.tools.qpcr_robustness(ctx.study_id, str(args.get("gene", "")))
    if tool == "qpcr_decide":
        return ctx.tools.qpcr_decide(
            ctx.study_id,
            str(args.get("card_id", "")),
            str(args.get("option", "")),
            str(args.get("reason") or "requested from Ask your data"),
        )
    if tool == "qpcr_plan":
        kwargs = {k: v for k, v in args.items() if k in PLAN_ARGS}
        values = [v for v in kwargs.values() if v is not None]
        if any(isinstance(v, bool) or not isinstance(v, int | float) for v in values):
            raise TypeError("qpcr_plan arguments must be numbers")
        if any(not isinstance(kwargs[k], int) for k in PLAN_INT_ARGS if kwargs.get(k) is not None):
            raise TypeError("n_rt and n_tech must be whole numbers")
        return ctx.tools.qpcr_plan(**kwargs)
    if tool == "qpcr_trace":
        kw = {k: str(v) for k, v in args.items() if k in TRACE_ARGS and v is not None}
        return ctx.tools.qpcr_trace(ctx.study_id, **kw)
    if tool == "explain_number":
        fid = str(args.get("fact_id", ""))
        fact = ctx.result.facts.get(fid)
        if fact is None:
            return {"error": "unknown fact id"}
        return {"fact_id": fid, "path": fact.path}
    if tool == "none":
        return {"error": NOT_UNDERSTOOD if args.get("reason") == NOT_UNDERSTOOD else NOT_IN_STUDY}
    return {"error": f"unknown tool {tool!r}"}


def answer_facts(ctx: _Context, tool: str, out: dict[str, Any]) -> tuple[dict, dict[str, Fact]]:
    """The tool result as the model sees it (numbers replaced by tokens) and those facts."""
    facts: dict[str, Fact] = {}

    def tok(fid: str, value: Any, fmt: str = "{}", unit: str = "") -> str:
        facts[fid] = _fact(fid, value, fmt, unit)
        return "{{" + fid + "}}"

    if "error" in out:
        view = {"error": out["error"]}
        if out["error"] in (NOT_IN_STUDY, "gene not in this study"):
            view["n_genes_in_study"] = tok("f_ans_n_genes", len(ctx.result.contrasts))
        return view, facts
    if tool == "qpcr_robustness":
        conf = out.get("confidence") or {}
        view = {
            "gene": out["gene"],
            "conclusion": out["conclusion"],
            "fold_change": tok("f_ans_fc", out["fc"], "{:.2g}", "×"),
            "ci_low": tok("f_ans_ci_lo", out["ci"][0], "{:.2g}", "×"),
            "ci_high": tok("f_ans_ci_hi", out["ci"][1], "{:.2g}", "×"),
            "p": tok("f_ans_p", out["p"], "{:.2g}"),
            "holds_fraction": tok("f_ans_holds", out["holds_fraction"], "{:.0%}"),
            "n_analyses": tok("f_ans_n_cells", out["n_cells"]),
            "confidence": tok("f_ans_level", conf.get("level", "not graded")),
            "confidence_reasons": [_tokenise_reason(r, tok) for r in conf.get("reasons", [])],
            "cards_that_can_flip_it": out.get("cards_that_can_flip_it", []),
        }
        return view, facts
    if tool == "qpcr_study":
        view = {
            "plates": tok("f_ans_n_plates", out["n_plates"]),
            "samples": tok("f_ans_n_samples", out["n_samples"]),
            "reactions": tok("f_ans_n_reactions", out["n_reactions"], "{:,}"),
            "genes": tok("f_ans_n_genes", out["n_genes"]),
            "group": out["group"],
            "open_cards": out["open_cards"],
        }
        if out.get("about") == "calls":
            view |= {
                "genes_up": out["up"],
                "n_up": tok("f_ans_n_up", len(out["up"])),
                "genes_down": out["down"],
                "n_down": tok("f_ans_n_down", len(out["down"])),
                "n_no_call": tok("f_ans_n_no_call", out["n_no_call"]),
            }
        elif out.get("about") == "references":
            view |= {
                "most_stable_first": [
                    {"gene": g, "M_all_candidates": tok(f"f_ans_m_{i}", out["M"][g], "{:.2f}")}
                    for i, g in enumerate(out["order"], 1)
                    if g in out["M"]
                ],
                "recommended": out["recommended"],
                "M_cutoff": tok("f_ans_m_cutoff", out["cutoff_M"], "{:g}"),
            }
        elif out.get("about") == "cards":
            view["choices"] = [
                {
                    "choice": KIND_TITLE.get(c["kind"], c["kind"]),
                    "genes_whose_call_it_can_change": tok(f"f_ans_flips_{i}", c["n_flipped"]),
                }
                for i, c in enumerate(out["cards"], 1)
                if c["n_flipped"] is not None
            ]
        return view, facts
    if tool == "qpcr_decide":
        card = out.get("card") or {}
        return {
            "status": out["status"],
            "reason": out.get("reason"),
            "card_id": card.get("card_id"),
            "decision": card.get("decision"),
        }, facts
    if tool == "qpcr_plan":
        view = {"message_has_numbers": True}
        if out.get("n_needed") is not None:
            view["n_per_group_needed"] = tok("f_ans_n_needed", out["n_needed"])
        if out.get("n_for_call") is not None:  # the headline: samples for qPilot's own call
            view["n_per_group_for_a_call"] = tok("f_ans_n_for_call", out["n_for_call"])
        if out.get("mde_fold") is not None:
            view["smallest_detectable_fold"] = tok("f_ans_mde_fold", out["mde_fold"], "{:.1f}", "×")
        sims = out.get("simulated") or {}
        for key in ("needed_called", "planned_called"):
            if key in sims:
                view[f"qpilot_rule_calls_it_at_{key.split('_')[0]}_n"] = tok(
                    f"f_ans_{key}", sims[key], "{:.0%}"
                )
        view["rules"] = out.get("rules", [])
        return view, facts
    if tool == "qpcr_trace":
        return _trace_view(out, tok), facts
    if tool == "explain_number":
        return {"fact": "{{" + out["fact_id"] + "}}", "computed_from": out["path"]}, facts
    return {}, facts


def _trace_view(out: dict[str, Any], tok: Any) -> dict[str, Any]:
    """A trace as the model sees it: addresses carry digits, so they are string facts too."""
    from qpilot.qpcr.trace import CHECKS

    root = out.get("root") or {}
    summary = out.get("summary") or {}
    view: dict[str, Any] = {
        "root_kind": root.get("kind"),
        "answer": out.get("answer"),
        "places_to_look": [],
    }
    if root.get("kind") == "gene":
        view["gene"] = root.get("id")
        view["call"] = summary.get("call")
    else:
        view["root"] = tok("f_ans_trace_root", str(root.get("id", "")))
    for i, place in enumerate(out.get("places") or [], 1):
        item: dict[str, Any] = {"sample": tok(f"f_ans_trace_{i}_sample", str(place["sample"]))}
        for key in ("plate", "well", "target"):
            if place.get(key):
                item[key] = tok(f"f_ans_trace_{i}_{key}", str(place[key]))
        if place.get("fold_off") is not None:
            item["values_read_off_by"] = tok(
                f"f_ans_trace_{i}_fold", place["fold_off"], "{:.3g}", "×"
            )
        if place.get("feeds"):
            item["values_fed"] = tok(f"f_ans_trace_{i}_feeds", place["feeds"])
        item["looks_like"] = [
            CHECKS[c]["looks_like"] for c in place.get("checks") or [] if c in CHECKS
        ]
        item["consequence"] = place.get("consequence")
        view["places_to_look"].append(item)
    n_more = summary.get("n_more")
    if isinstance(n_more, int) and n_more > 0:
        view["more_places"] = tok("f_ans_trace_n_more", n_more)
    return view


def _tokenise_reason(reason: str, tok: Any) -> str:
    """A confidence reason as the model sees it, with its data numbers as tokens.

    Those are how many choices flip the gene at once and how many analyses qPilot checks (the
    grid's size); the method thresholds the reasons quote (95 % confidence interval, 80 % of
    the analyses, M 1.5) stay as written.
    """
    reason = re.sub(
        r"\b(\d+)(?=\s+choices?\b)", lambda m: tok("f_ans_min_flip", int(m.group(1))), reason
    )
    return re.sub(
        r"\b(\d+)(?=\s+analyses\s+qPilot\s+checks\b)",
        lambda m: tok("f_ans_n_cells", int(m.group(1))),
        reason,
    )


def template_answer(ctx: _Context, tool: str, out: dict[str, Any], view: dict) -> str:
    """A deterministic answer in tokens for any tool result."""
    if "error" in out:
        if out["error"] == NOT_UNDERSTOOD:
            return can_answer(ctx)
        if out["error"] in (NOT_IN_STUDY, "gene not in this study"):
            return (
                "That is not in this study; qPilot can answer about the "
                "{{f_ans_n_genes}} genes on this panel."
            )
        if tool == "qpcr_decide":
            return f"Not applied: {out['error']}. Nothing was changed."
        if tool == "qpcr_trace":
            err = str(out["error"])
            if any(ch.isnumeric() for ch in err) or err.startswith("give exactly one"):
                return TRACE_NO_ROOT
            return f"qPilot could not trace that: {err}."
        return f"qPilot could not answer that: {out['error']}."
    if tool == "qpcr_robustness":
        group = ctx.result.design.group_var.replace("_", " ")
        flip = [KIND_TITLE.get(_kind(ctx, c), c).lower() for c in out["cards_that_can_flip_it"]]
        text = (
            f"{out['gene']} is {CONCLUSION_WORDS[out['conclusion']]} in the {group} group under "
            "the recommended choices: {{f_ans_fc}} (confidence interval {{f_ans_ci_lo}} to "
            "{{f_ans_ci_hi}}). It holds in {{f_ans_holds}} of the {{f_ans_n_cells}} analyses "
            "qPilot checks; confidence {{f_ans_level}}."
        )
        if flip:
            text += " It can change with: " + "; ".join(flip) + "."
        elif out.get("holds_fraction") is not None and out["holds_fraction"] < 1:
            text += " No single choice flips it on its own, but some combinations of choices do."
        else:
            text += " No single choice flips it."
        return text
    if tool == "qpcr_study":
        about = out.get("about")
        if about == "calls":
            group = ctx.result.design.group_var.replace("_", " ")
            up = ", ".join(out["up"]) or "none"
            down = ", ".join(out["down"]) or "none"
            return (
                f"Higher in the {group} group ({{{{f_ans_n_up}}}} genes): {up}. Lower "
                f"({{{{f_ans_n_down}}}} genes): {down}. No call (not clearly different): "
                "{{f_ans_n_no_call}} genes."
            )
        if about == "references":
            rows = view["most_stable_first"]
            if len(rows) < 2:
                return "geNorm needs at least two control genes to rank them."
            (a, b), rest = rows[:2], rows[2:]
            text = (
                f"geNorm's most stable pair is {a['gene']} and {b['gene']} (M "
                f"{a['M_all_candidates']} and {b['M_all_candidates']} among all candidates; "
                "geNorm sets genes aside one at a time and cannot split the last pair)"
            )
            if rest:
                text += ", then " + _and([f"{r['gene']} ({r['M_all_candidates']})" for r in rest])
            return (
                text + ". Lower M is steadier; geNorm's cut-off is {{f_ans_m_cutoff}}. It "
                "recommends normalising to " + _and(out["recommended"]) + "."
            )
        if about == "cards":
            parts = [
                f"{row['choice']}: {row['genes_whose_call_it_can_change']}"
                for row in view["choices"]
            ]
            return (
                "How many genes' calls each choice can change (under at least one of its "
                "options): " + "; ".join(parts) + "."
            )
        return (
            "This study has {{f_ans_n_plates}} plates, {{f_ans_n_samples}} samples and "
            "{{f_ans_n_genes}} genes."
        )
    if tool == "qpcr_decide":
        card = next((c for c in ctx.cards if c.id == view.get("card_id")), None)
        if out["status"] == "pending_human":
            return PENDING_TEXT if card is None or needs_human(card) else SUGGEST_TEXT
        if out["status"] == "stale":
            return STALE_TEXT
        title = KIND_TITLE.get(card.kind, card.id) if card else view.get("card_id")
        label = next(
            (o.label for o in (card.options if card else []) if o.id == view.get("decision")),
            view.get("decision"),
        )
        return f"Applied: {title}, {label}. It is in the decision log."
    if tool == "qpcr_plan":
        if "n_per_group_needed" not in view:
            return "Give the spread between biological replicates to get a sample size."
        if "n_per_group_for_a_call" in view:
            text = (
                "For qPilot's rule (p < 0.05 and at least 2-fold) to call a real change of this "
                "size you need {{f_ans_n_for_call}} per group; for p < 0.05 alone, "
                "{{f_ans_n_needed}} per group"
            )
        else:
            text = "You need {{f_ans_n_needed}} per group for p < 0.05"
        if "qpilot_rule_calls_it_at_needed_n" in view:
            text += (
                "; at that size qPilot's rule (p < 0.05 and at least 2-fold) calls a real change "
                "of this size {{f_ans_needed_called}} of the time"
            )
        text += "."
        if "smallest_detectable_fold" in view:
            text += (
                " The planned design reaches significance for changes of at least "
                "{{f_ans_mde_fold}}"
            )
            if "qpilot_rule_calls_it_at_planned_n" in view:
                text += ", and qPilot's rule would call this change "
                text += "{{f_ans_planned_called}} of the time"
            text += "."
        return text
    if tool == "qpcr_trace":
        return _trace_answer(view)
    if tool == "explain_number":
        return f"{view['fact']} is computed from {_path_words(view['computed_from'])}."
    return "qPilot could not answer that."


def can_answer(ctx: _Context) -> str:
    """What Ask can answer without a model, with an example gene from this study."""
    called = sorted(g for g, c in ctx.result.contrasts.items() if c.conclusion != "none")
    example = (called or sorted(ctx.result.contrasts) or ["a gene"])[0]
    return (
        f"I can answer: how one gene came out and how robust it is (try “Is {example} "
        "robust?”), where to look behind a gene, a sample or a well (try “Where should I look "
        f"for {example}?”), which genes are up or down, which control genes are most stable, how "
        "many genes each analysis choice can change, and the study's size. Name a gene or ask "
        "one of those."
    )


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _trace_answer(view: dict[str, Any]) -> str:
    """Fixed wording for a trace, in tokens: every address and number is a fact."""
    from qpilot.explain.trace_text import CONSEQUENCE_WORDS

    if view.get("root_kind") == "gene":
        call = TRACE_CALL_WORDS.get(view.get("call") or "", "")
        text = f"Trace for {view['gene']}" + (f" ({call})" if call else "") + ". "
    else:
        text = f"Trace for {view.get('root_kind') or 'this'} {view.get('root', '')}. "
    places = view.get("places_to_look") or []
    if not places:
        return text + NOTHING_TEXT.get(view.get("answer") or "", NOTHING_TEXT["nothing_to_look_at"])
    parts = []
    for place in places:
        where = f"sample {place['sample']}"
        if "plate" in place:
            where += f", plate {place['plate']}"
        if "well" in place:
            where += f", well {place['well']}"
        what = CONSEQUENCE_WORDS.get(place.get("consequence") or "", "changes nothing here")
        line = f"{where}: {what}"
        if "values_read_off_by" in place:
            line += f" (the sample's values read {place['values_read_off_by']} off)"
        parts.append(line)
    text += "Where to look first: " + parts[0] + "."
    if len(parts) > 1:
        text += " Then " + "; then ".join(parts[1:]) + "."
    if "more_places" in view:
        text += " Trace found {{f_ans_trace_n_more}} more unusual places."
    return text + " Setting a place aside is a decision for a person in qPilot."


def _kind(ctx: _Context, card_id: str) -> str:
    return next((c.kind for c in ctx.cards if c.id == card_id), card_id)


def _path_words(path: str) -> str:
    path = path.replace("[0]", " lower bound").replace("[1]", " upper bound")
    return " › ".join(path.split("."))


# ---- routing without a model ------------------------------------------------------------


def route(ctx: _Context, question: str) -> tuple[str, dict[str, Any]]:
    """Keyword routing used when no model is configured (and when a tool call is unusable)."""
    lowered = question.lower()
    if DECIDE_WORDS.search(question) and not NOT_A_REQUEST.search(question):
        hit = _requested_option(ctx, lowered)
        if hit:
            card_id, option_id = hit
            reason = "requested from Ask your data"
            return "qpcr_decide", {"card_id": card_id, "option": option_id, "reason": reason}
    gene = ctx.gene(question)
    traced = bool(TRACE_WORDS.search(question)) or (
        bool(gene) and bool(TRACE_WHY.search(question)) and not WHAT_IF.search(question)
    )
    if traced:
        if well := WELL_IN_TEXT.search(question):
            return "qpcr_trace", {"well": f"{well.group(1)}:{well.group(2)}"}
        if gene:
            return "qpcr_trace", {"gene": gene}
        if sample := SAMPLE_IN_TEXT.search(question):
            return "qpcr_trace", {"sample": sample.group(1)}
    if gene:
        return "qpcr_robustness", {"gene": gene}
    known = {n.lower() for n in ctx.names}
    if any(w.lower() not in known for w in GENE_LIKE.findall(question)):
        return "none", {"reason": NOT_IN_STUDY}
    if traced:
        return "qpcr_trace", {}
    topic = study_topic(question)
    if topic is None and _names_group(ctx, lowered):
        topic = "overview"  # "What does MYCN high mean?": the study and its groups
    if topic is None:
        return "none", {"reason": NOT_UNDERSTOOD}
    return "qpcr_study", {} if topic == "overview" else {"about": topic}


def _names_group(ctx: _Context, lowered: str) -> bool:
    """Whether the question names the comparison group (every word of it)."""
    parts = [p.lower() for p in ctx.result.design.group_var.split("_") if p]
    return bool(parts) and all(re.search(rf"\b{re.escape(p)}\b", lowered) for p in parts)


def study_topic(question: str) -> str | None:
    """What a question about the whole study asks for (one of STUDY_TOPICS), or None."""
    if CHANGE_WORDS.search(question) and CHOICE_TOPICS.search(question):
        if GENES_WORD.search(question) and ASKS_WHICH.search(question):
            return "cards"  # "How many genes change with the reference genes?"
    if REFERENCE_WORDS.search(question) and STABLE_WORDS.search(question):
        return "references"
    if GENES_WORD.search(question) and CALL_WORDS.search(question) and ASKS_WHICH.search(question):
        return "calls"
    if OVERVIEW_WORDS.search(question):
        return "overview"
    return None


def _requested_option(ctx: _Context, lowered: str) -> tuple[str, str] | None:
    """The (card, option) a change request names, matched generously; None if none is named."""
    named = {
        option.id
        for card in ctx.cards
        for option in card.options
        if option.id.endswith("_alone") and _names(option.label, lowered)
    }
    # "normalise to HMBS and UBC" names two genes, so it is not a request for one of them alone.
    only = bool(ONLY_WORDS.search(lowered)) or (bool(SOLE_ROLE.search(lowered)) and len(named) == 1)
    for card in ctx.cards:
        for option in sorted(card.options, key=lambda o: -len(o.label)):
            label = option.label.lower()
            if label in lowered:
                return card.id, option.id
            if option.id.endswith("_alone") and only and _names(label, lowered):
                return card.id, option.id
            if option.id == "top2" and re.search(r"\btop (two|2)\b|two most stable", lowered):
                return card.id, option.id
            pct = re.match(r"cut_(\d+)$", option.id)
            words = [w for w, n in NUMBER_WORDS.items() if pct and n == int(pct.group(1))]
            amount = "|".join([pct.group(1), *words]) if pct else ""
            if pct and re.search(rf"\b({amount})\s?(%|percent\b|per\s+cent\b)", lowered):
                return card.id, option.id
    return None


def _names(label: str, lowered: str) -> bool:
    """Whether ``lowered`` names the gene of an "X alone" option label as a whole word."""
    bare = re.sub(r"\s+alone$", "", label.lower())
    return bool(re.search(rf"(?<![\w(]){re.escape(bare)}(?![\w)])", lowered))


def _parse_tool(text: str) -> tuple[str, dict[str, Any]] | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    tool, args = data.get("tool"), data.get("args") or {}
    if tool not in TOOLS or not isinstance(args, dict):
        return None
    return tool, args


# ---- the entry point --------------------------------------------------------------------


def ask(
    question: str,
    store: StudyStore,
    study_id: str,
    client: ModelClient | None = None,
    profile: Profile | None = None,
    log: bool = True,
) -> AskResult:
    """Answer ``question`` about a study; every number in the answer is a fact token."""
    client = client or ModelClient.from_env()
    profile = profile or Profile()
    ctx = _Context(store, study_id)
    question = (question or "").strip()[:1000]
    calls: list[dict[str, Any]] = []
    error = None
    model_used = client.available
    tool_from_model = False
    first_call = len(client.metas)

    tool, args = route(ctx, question)
    if model_used:
        try:
            reply = client.complete(
                SYSTEM_ASK_TOOL,
                [{"role": "user", "content": _tool_prompt(ctx, question, profile)}],
                max_tokens=300,
            )
            parsed = _parse_tool(reply)
            if parsed is None:
                error = "the model's tool call did not parse; keyword routing used"
            elif tool == "qpcr_decide":
                # Safety first: a plain request to apply a card option always goes through
                # qpcr_decide with the card and option the person named (and so through the
                # human gate), whatever tool or arguments the model picked.
                picked = (parsed[0], parsed[1].get("card_id"), parsed[1].get("option"))
                tool_from_model = picked == (tool, args["card_id"], args["option"])
                if not tool_from_model:
                    error = (
                        f"the model's call ({parsed[0]}) differs from the change request; "
                        "qpcr_decide used with the card and option asked for"
                    )
            else:
                tool, args = parsed
                tool_from_model = True
                if tool == "qpcr_study" and args.get("about") not in STUDY_TOPICS:
                    topic = study_topic(question)
                    args = {} if topic in (None, "overview") else {"about": topic}
        except ModelUnavailable as err:
            model_used, error = False, str(err)

    try:
        out = run_tool(ctx, tool, args)
    except (TypeError, ValueError, KeyError, ArithmeticError) as err:
        # A model sent arguments of the wrong type or shape: fall back to qPilot's own routing.
        error = (
            f"the model's {tool} call was malformed ({type(err).__name__}); keyword routing used"
        )
        tool, args = route(ctx, question)
        tool_from_model = False
        out = run_tool(ctx, tool, args)
    calls.append(
        {"tool": tool, "args": args, "status": out.get("status"), "error": out.get("error")}
    )
    view, extra = answer_facts(ctx, tool, out)
    facts = {**ctx.result.facts, **extra}
    status = out.get("status")
    fallback_text = template_answer(ctx, tool, out, view)
    if tool in ("qpcr_robustness", "qpcr_trace") and "error" not in out:
        fallback_text = _about(ctx, question) + fallback_text

    text, validated, fallback, rejected = fallback_text, True, True, 0
    # Whatever happened to a change request (applied, waiting, stale or refused) is always
    # reported in qPilot's own fixed words, so a model can never misdescribe it; the model
    # writes every other answer.
    if model_used and tool != "qpcr_decide":
        text, validated, fallback, err, rejected = _model_answer(
            client, ctx, question, tool, view, facts
        )
        error = err or error
        if fallback:
            text = fallback_text
        elif CLAIMS_DONE.search(text):
            # Whatever the routing missed: an answer may never claim a change that was not made.
            text, fallback = fallback_text, True
            error = "the model claimed a change that qPilot did not make; template used"
    check = validate(text, facts, ctx.names)
    result = AskResult(
        question=question,
        answer=text,
        plain=render_tokens(text, facts),
        tool_calls=calls,
        validated=check.ok,
        fallback=fallback,
        provider=client.provider,
        status=status,
        error=error,
        rejected_drafts=rejected,
        facts=extra,
        tool_from_model=tool_from_model,
    )
    if log and client.available:
        # One line per model call (tool choice, answer, retry); the outcome is on the last.
        made = client.metas[first_call:]
        for i, meta in enumerate(made, 1):
            last = i == len(made)
            entry = payload_log.log_entry(
                "ask",
                client.provider,
                client.model,
                meta,
                text if last else "",
                validated,
                fallback,
            )
            entry |= {"call": i, "of": len(made)}
            if not last:
                entry["validated"] = entry["fallback"] = None
            store.append_ai_call(study_id, entry)
    return result


def _about(ctx: _Context, question: str) -> str:
    """Words before a gene's answer: the alias it was asked by, the groups it was asked about."""
    gene = ctx.gene(question)
    lead = ""
    if gene and ctx.alias:
        lead = f"{ctx.alias[0][:1].upper()}{ctx.alias[0][1:]} is {gene} in this study. "
    groups = ctx.other_groups(question)
    if groups:
        lead += groups
    return lead


def _tool_prompt(ctx: _Context, question: str, profile: Profile) -> str:
    entries = ctx.store.entries(ctx.study_id)
    return json.dumps(
        {
            "question": question,
            "genes_in_study": sorted(ctx.result.contrasts),
            "cards": [
                {"card_id": c.id, "kind": c.kind, "options": [o.id for o in c.options]}
                for c in ctx.cards
            ],
            "examples_from_this_lab": build_fewshots(entries, ctx.cards, profile.max_fewshots),
        },
        ensure_ascii=False,
    )


def _model_answer(client, ctx, question, tool, view, facts):
    table = fact_table(facts, [fid for fid in facts if fid.startswith("f_ans_")])
    for fid, row in table.items():
        if ADDRESS_FACT.match(fid):  # a sample, plate or well name: the model copies the token
            row["value_for_reading_only"] = HIDDEN_ADDRESS
    content = json.dumps(
        {"question": question, "tool": tool, "result": view, "facts": table}, ensure_ascii=False
    )
    messages = [{"role": "user", "content": content}]
    error = None
    rejected = 0
    for _attempt in range(2):
        try:
            text = client.complete(SYSTEM_ASK_ANSWER, messages).strip()
        except ModelUnavailable as err:
            return "", False, True, str(err), rejected
        check = validate(text, facts, ctx.names)
        if check.ok and text:
            return text, True, False, None, rejected
        rejected += 1
        error = check.error()
        messages = [
            *messages,
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"Rejected: {error}. Rewrite following the token rule."},
        ]
    return "", False, True, error, rejected
