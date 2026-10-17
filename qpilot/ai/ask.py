"""Ask your data: a plain question answered from engine tools, with every number traceable.

Two steps, portable to any endpoint (no native tool calling needed):

1. The model replies with JSON ``{"tool": ..., "args": {...}}`` naming one of ``qpcr_study``,
   ``qpcr_robustness``, ``qpcr_decide``, ``qpcr_plan``, ``explain_number`` (or ``none``).
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

TOOLS = ("qpcr_study", "qpcr_robustness", "qpcr_decide", "qpcr_plan", "explain_number", "none")
NOT_IN_STUDY = "not in this study"
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

    def gene(self, text: str) -> str | None:
        lowered = text.lower()
        hits = [
            g
            for g in self.result.contrasts
            if re.search(rf"(?<![\w(]){re.escape(g.lower())}(?![\w)])", lowered)
        ]
        return max(hits, key=len) if hits else None


# ---- running a tool and turning its numbers into facts ------------------------------------


def run_tool(ctx: _Context, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute one tool call in-process; unknown tools come back as an error."""
    if tool == "qpcr_study":
        r = ctx.result
        return {
            "n_plates": r.n_plates,
            "n_samples": r.n_samples,
            "n_reactions": r.n_reactions,
            "n_genes": len(r.contrasts),
            "group": r.design.group_var,
            "open_cards": [c.id for c in ctx.cards if c.status in ("open", "pending_human")],
        }
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
        allowed = {"fc", "sd_log2", "n_per_group", "alpha", "power"}
        kwargs = {k: v for k, v in args.items() if k in allowed}
        values = [v for v in kwargs.values() if v is not None]
        if any(isinstance(v, bool) or not isinstance(v, int | float) for v in values):
            raise TypeError("qpcr_plan arguments must be numbers")
        return ctx.tools.qpcr_plan(**kwargs)
    if tool == "explain_number":
        fid = str(args.get("fact_id", ""))
        fact = ctx.result.facts.get(fid)
        if fact is None:
            return {"error": "unknown fact id"}
        return {"fact_id": fid, "path": fact.path}
    if tool == "none":
        return {"error": NOT_IN_STUDY}
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
    if tool == "explain_number":
        return {"fact": "{{" + out["fact_id"] + "}}", "computed_from": out["path"]}, facts
    return {}, facts


def _tokenise_reason(reason: str, tok: Any) -> str:
    """A confidence reason as the model sees it, with its one data number as a token.

    That number is how many choices flip the gene at once; the method thresholds the reasons
    quote (95 % confidence interval, 80 % of the reasonable analyses, M 1.5) stay as written.
    """
    return re.sub(
        r"\b(\d+)(?=\s+choices?\b)", lambda m: tok("f_ans_min_flip", int(m.group(1))), reason
    )


def template_answer(ctx: _Context, tool: str, out: dict[str, Any], view: dict) -> str:
    """A deterministic answer in tokens for any tool result."""
    if "error" in out:
        if out["error"] in (NOT_IN_STUDY, "gene not in this study"):
            return (
                "That is not in this study; qPilot can answer about the "
                "{{f_ans_n_genes}} genes on this panel."
            )
        if tool == "qpcr_decide":
            return f"Not applied: {out['error']}. Nothing was changed."
        return f"qPilot could not answer that: {out['error']}."
    if tool == "qpcr_robustness":
        group = ctx.result.design.group_var.replace("_", " ")
        flip = [KIND_TITLE.get(_kind(ctx, c), c).lower() for c in out["cards_that_can_flip_it"]]
        text = (
            f"{out['gene']} is {CONCLUSION_WORDS[out['conclusion']]} in the {group} group under "
            "the recommended choices: {{f_ans_fc}} (confidence interval {{f_ans_ci_lo}} to "
            "{{f_ans_ci_hi}}). It holds in {{f_ans_holds}} of the {{f_ans_n_cells}} reasonable "
            "analyses; confidence {{f_ans_level}}."
        )
        if flip:
            text += " It can change with: " + "; ".join(flip) + "."
        else:
            text += " No single choice flips it."
        return text
    if tool == "qpcr_study":
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
        text = "You need {{f_ans_n_needed}} per group"
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
    if tool == "explain_number":
        return f"{view['fact']} is computed from {_path_words(view['computed_from'])}."
    return "qPilot could not answer that."


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
    if gene:
        return "qpcr_robustness", {"gene": gene}
    known = {n.lower() for n in ctx.names}
    if any(w.lower() not in known for w in GENE_LIKE.findall(question)):
        return "none", {"reason": NOT_IN_STUDY}
    return "qpcr_study", {}


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
        entry = payload_log.log_entry(
            "ask", client.provider, client.model, client.last_meta, text, validated, fallback
        )
        store.append_ai_call(study_id, entry)
    return result


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
