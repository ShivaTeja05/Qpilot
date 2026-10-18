"""The Prism draft: which tables, which test, which graph and the caption, as one proposal payload.

:func:`draft_prism_project` turns a study's results into the payload of a ``prism.project``
proposal. Everything in it is qPilot's: the template (``qpilot.prism.tables.TEMPLATES``), the
genes (default: the study's headline genes that were analysed), the test (Welch's unpaired t
test on log2 relative quantities, the engine's own) and why, the graph (every biological unit,
mean and 95 % confidence interval), the usual-route comparison (``f_n_differ_route_*``) and each
gene's robustness (how often its conclusion holds) when the study has them.

Every number is a ``{{fact_id}}`` token of the study's own facts and passes
:func:`qpilot.core.validator.validate`. The caption is the template's by default. A model may
reword it, and its wording is used only if it passes the validator and cites exactly the facts
the template cites (nothing dropped, nothing added); otherwise one retry with the validator's
message, then the template. A remote model needs a pseudonymiser (gene names become keyed tokens
in what is sent, mapped back on return); without one the template is used and nothing is sent.

Nothing here writes a file or accepts anything: the payload becomes a proposal that a person
accepts before **Send to Prism** writes the bundle.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from qpilot.ai import payload_log
from qpilot.ai.client import ModelClient, ModelUnavailable
from qpilot.ai.explain import fact_table
from qpilot.ai.prompts import SYSTEM_PRISM_CAPTION
from qpilot.core.facts import slug
from qpilot.core.validator import TOKEN, names_from_result, render_tokens, validate
from qpilot.schemas import DecisionCard, Fact, StudyResult

DEFAULT_TEMPLATE = "two_groups_log2"
MAX_CAPTION_CHARS = 2_000
PROMPT_SHA256 = hashlib.sha256(SYSTEM_PRISM_CAPTION.encode("utf-8")).hexdigest()
ROUTE_IDS = ("ddcq", "linear_welch", "linear_student")
GRAPHS = {
    "column": {
        "points": "every biological unit",
        "centre": "mean",
        "error_bars": "95 % confidence interval",
    },
    "nested": {
        "points": "every technical replicate, marked by biological unit",
        "centre": "mean of the biological units",
        "error_bars": "95 % confidence interval",
    },
}


class PrismDraft(BaseModel):
    """The draft of a ``prism.project`` proposal; :meth:`payload` is what is proposed.

    ``caption`` is token text; ``caption_plain`` the same with the numbers rendered.
    ``made_by_model`` is True only when the model's reworded caption passed and is used;
    ``fallback`` is True when a model was asked and the template caption stands instead.
    ``meta`` holds one payload record per model call (for the caller's ``ai_calls.jsonl``).
    """

    template_id: str
    genes: list[str]
    test: dict[str, Any]
    graph: dict[str, Any]
    caption: str
    caption_plain: str
    template_caption: str
    routes: dict[str, dict[str, str]] = {}
    robustness: dict[str, dict[str, str]] = {}
    fact_ids: list[str] = []
    validated: bool
    fallback: bool
    made_by_model: bool = False
    reasons: list[str] = []
    notes: list[str] = []
    error: str | None = None
    meta: list[dict[str, Any]] = []
    prompt_sha256: str | None = None

    def payload(self) -> dict[str, Any]:
        """The ``prism.project`` payload: template, genes, test, graph, caption, facts."""
        return {
            "template_id": self.template_id,
            "genes": list(self.genes),
            "test": dict(self.test),
            "graph": dict(self.graph),
            "caption": self.caption,
            "routes": {k: dict(v) for k, v in self.routes.items()},
            "robustness": {k: dict(v) for k, v in self.robustness.items()},
            "facts": list(self.fact_ids),
        }


def _tok(fact_id: str) -> str:
    return "{{" + fact_id + "}}"


def default_genes(result: StudyResult) -> list[str]:
    """The study's headline genes that were analysed (the first four analysed otherwise)."""
    from qpilot.qpcr.designs import HEADLINE_GENES  # the engine's headline list

    genes = [g for g in HEADLINE_GENES if g in result.contrasts]
    return genes or list(result.contrasts)[:4]


def _groups(result: StudyResult) -> tuple[str, str]:
    """The two groups as caption text: fact tokens when the design names them."""
    if "f_group_a" in result.facts and "f_group_b" in result.facts:
        return _tok("f_group_a"), _tok("f_group_b")
    return result.design.group_var.replace("_", " "), "the rest"


def _names(result: StudyResult, genes: Iterable[str]) -> set[str]:
    names = names_from_result(result) | set(genes) | {"log2"}
    names |= {result.design.group_var, result.design.group_var.replace("_", " ")}
    return names


def template_caption(result: StudyResult, genes: Sequence[str], layout: str | None) -> str:
    """The caption in ``{{fact_id}}`` tokens; a gene without its facts is named, not numbered."""
    first, second = _groups(result)
    unit = (
        "every technical replicate, marked by biological unit"
        if layout == "nested"
        else ("one point per biological unit")
    )
    head = (
        f"log2 relative quantities, {first} versus {second}; {unit}, with the mean and 95 % "
        "confidence interval; Welch's t test on the log2 scale."
    )
    facts = result.facts
    sentences = [head]
    for gene in genes:
        s = slug(gene)
        ids = [
            f"f_fc_{s}_recommended",
            f"f_ci_lo_{s}_recommended",
            f"f_ci_hi_{s}_recommended",
            f"f_p_{s}_recommended",
        ]
        if not all(fid in facts for fid in ids):
            sentences.append(f"{gene}: shown in qPilot.")
            continue
        t = [_tok(fid) for fid in ids]
        text = f"{gene}: {t[0]} (95 % confidence interval {t[1]} to {t[2]}; p = {t[3]})"
        if f"f_holds_{s}" in facts and "f_n_cells" in facts:
            text += (
                f"; the conclusion holds in {_tok(f'f_holds_{s}')} of {_tok('f_n_cells')} "
                "reasonable analyses"
            )
        sentences.append(text + ".")
    return " ".join(sentences)


def _why(result: StudyResult) -> list[str]:
    """Why this test, in qPilot's words with fact tokens."""
    facts = result.facts
    why = [
        "Welch's t test does not assume that the two groups vary equally, and it is the test "
        "qPilot's engine used on the same log2 values, so Prism's p-values match the record."
    ]
    if "f_n_hi" in facts and "f_n_lo" in facts:
        why.append(
            f"The groups hold {_tok('f_n_hi')} and {_tok('f_n_lo')} biological units; technical "
            "replicates are averaged within a unit and never counted as n."
        )
    if all(f"f_n_differ_route_{r}" in facts for r in ROUTE_IDS) and "f_n_genes" in facts:
        why.append(
            "The usual spreadsheet route changes conclusions on these plates: "
            f"{_tok('f_n_differ_route_ddcq')} of {_tok('f_n_genes')} genes with an assumed "
            f"efficiency, {_tok('f_n_differ_route_linear_welch')} with Welch's test on the linear "
            f"scale and {_tok('f_n_differ_route_linear_student')} with Student's test on the "
            "linear scale."
        )
    return why


def _routes(result: StudyResult) -> dict[str, dict[str, str]]:
    from qpilot.qpcr.routes import ROUTE_LABELS  # the engine's names for the usual routes

    out = {}
    for route in ROUTE_IDS:
        fid = f"f_n_differ_route_{route}"
        if fid in result.facts:
            out[route] = {
                "label": ROUTE_LABELS.get(route, route),
                "n_differ": _tok(fid),
                "genes": _tok(f"f_genes_differ_route_{route}")
                if f"f_genes_differ_route_{route}" in result.facts
                else "",
            }
    return out


def _robustness(result: StudyResult, genes: Sequence[str]) -> dict[str, dict[str, str]]:
    out = {}
    for gene in genes:
        s = slug(gene)
        entry = {}
        for key, fid in (("holds", f"f_holds_{s}"), ("level", f"f_level_{s}")):
            if fid in result.facts:
                entry[key] = _tok(fid)
        if entry:
            if "f_n_cells" in result.facts:
                entry["of_analyses"] = _tok("f_n_cells")
            out[gene] = entry
    return out


def _cited(texts: Iterable[str]) -> list[str]:
    return sorted({fid for text in texts for fid in TOKEN.findall(text)})


def private_names(result: StudyResult) -> list[str]:
    """Every target name the study's text can carry (genes, references, the group's marker)."""
    names = set(result.contrasts) | set(result.genorm.M_initial) | set(result.design.refs_primary)
    names |= {w for w in result.design.group_var.split("_") if any(c.isupper() for c in w)}
    return sorted(n for n in names if n)


def _pseudonyms(pseudonymiser: Any, names: Sequence[str]) -> tuple[dict[str, str], dict[str, str]]:
    to_token = {n: pseudonymiser.pseudonymise(n) for n in names}
    return to_token, {t: n for n, t in to_token.items()}


def _swap(text: str, mapping: Mapping[str, str]) -> str:
    for old in sorted(mapping, key=len, reverse=True):
        text = re.sub(rf"(?<![\w(]){re.escape(old)}(?![\w)])", mapping[old], text)
    return text


def _reword(
    client: ModelClient,
    caption: str,
    facts: Mapping[str, Fact],
    names: set[str],
    pseudonymiser: Any | None,
    genes: Sequence[str],
    private: Sequence[str] = (),
) -> tuple[str | None, str | None, int]:
    """(model caption or None, error, calls made); ``private`` names become pseudonyms."""
    import json

    hidden = sorted(set(private) | set(genes))
    to_token, to_gene = _pseudonyms(pseudonymiser, hidden) if pseudonymiser else ({}, {})
    wanted = set(TOKEN.findall(caption))
    table = fact_table(facts, sorted(wanted))
    if to_token:  # a fact value may name a gene; such a value is never shown to a remote model
        table = {
            f: v
            for f, v in table.items()
            if not any(n in v["value_for_reading_only"] for n in hidden)
        }
    content = json.dumps({"caption": _swap(caption, to_token), "facts": table}, ensure_ascii=False)
    messages = [{"role": "user", "content": content}]
    error = None
    calls = 0
    for _attempt in range(2):
        try:
            calls += 1
            text = client.complete(SYSTEM_PRISM_CAPTION, messages, max_tokens=700).strip()
        except ModelUnavailable as err:
            return None, str(err), calls
        text = _swap(text, to_gene)
        problems = []
        check = validate(text, facts, names)
        if not check.ok:
            problems.append(check.error())
        got = set(TOKEN.findall(text))
        if got != wanted:
            missing, extra = sorted(wanted - got), sorted(got - wanted)
            if missing:
                problems.append("facts left out: " + ", ".join(missing))
            if extra:
                problems.append("facts not in the template caption: " + ", ".join(extra))
        if not text or len(text) > MAX_CAPTION_CHARS:
            problems.append("empty or too long")
        missing_genes = [g for g in genes if g not in text]
        if missing_genes:
            problems.append("genes left out: " + ", ".join(missing_genes))
        if not problems:
            return text, None, calls
        error = "; ".join(problems)
        messages = [
            *messages,
            {"role": "assistant", "content": _swap(text, to_token)},
            {"role": "user", "content": f"Rejected: {error}. Rewrite following the token rule."},
        ]
    return None, error, calls


def draft_prism_project(
    result: StudyResult,
    cards: Sequence[DecisionCard] | None,
    genes: Sequence[str] | None,
    template_id: str = DEFAULT_TEMPLATE,
    client: ModelClient | None = None,
    *,
    pseudonymiser: Any | None = None,
) -> PrismDraft:
    """Draft the Prism project for a study: template, genes, test and why, graph, caption.

    Args:
        result: The study's results (its facts are the only numbers used).
        cards: The study's Decision Cards (reserved; the draft follows the recommended choices
            the results describe).
        genes: Genes to send to Prism; default :func:`default_genes`. Genes the study did not
            analyse are left out with a note.
        template_id: A template of ``qpilot.prism.tables.TEMPLATES``.
        client: A model that may reword the caption; ``None`` or provider ``none``: template.
        pseudonymiser: Required before a remote model is asked (gene names become tokens).

    Raises:
        ValueError: An unknown template, or no analysed gene to draft.
    """
    from qpilot.prism.tables import PrismExportError, template_spec

    try:
        spec = template_spec(template_id)
    except PrismExportError as err:
        raise ValueError(str(err)) from err
    _ = cards
    notes: list[str] = []
    asked = list(genes) if genes else default_genes(result)
    chosen = [g for g in dict.fromkeys(asked) if g in result.contrasts]
    left_out = [g for g in asked if g not in result.contrasts]
    if left_out:
        notes.append(f"Not analysed in this study, so left out: {', '.join(left_out)}.")
    if not chosen:
        raise ValueError("none of these genes was analysed in this study")
    if spec.note:
        notes.append(spec.note)
    facts = result.facts
    names = _names(result, chosen)
    caption = template_caption(result, chosen, spec.layout)
    why = _why(result)
    for text in (caption, *why):
        check = validate(text, facts, names)
        if not check.ok:  # a bug in qPilot's own words: never shipped
            raise ValueError(f"the Prism draft failed the validator: {check.error()}")
    test = {
        "id": "welch_log2" if spec.layout != "nested" else "nested_t_log2",
        "label": spec.test,
        "scale": "log2_rq",
        "why": why,
    }
    graph = {"label": spec.graph, **GRAPHS.get(spec.layout or "column", GRAPHS["column"])}
    reasons = ["the test is the engine's own, on the same log2 values"]
    used, fallback, made_by_model, error = caption, False, False, None
    prompt_sha = None
    meta: list[dict[str, Any]] = []
    if client is not None and client.available:
        from qpilot.ai.interpret import client_is_remote

        if client_is_remote(client) and pseudonymiser is None:
            fallback, error = True, "a remote model needs a pseudonymiser; nothing was sent"
        else:
            start = len(client.metas)
            remote = client_is_remote(client)
            worded, error, _calls = _reword(
                client,
                caption,
                facts,
                names,
                pseudonymiser if remote else None,
                chosen,
                private_names(result),
            )
            meta = [dict(m) for m in client.metas[start:]]
            prompt_sha = PROMPT_SHA256
            if worded is not None:
                used, made_by_model = worded, True
                reasons.append("the caption was reworded by the model and passed the validator")
            else:
                fallback = True
    if not made_by_model:
        reasons.append("the caption is qPilot's template")
    routes = _routes(result)
    robustness = _robustness(result, chosen)
    tables = [*routes.values(), *robustness.values()]
    return PrismDraft(
        template_id=spec.id,
        genes=chosen,
        test=test,
        graph=graph,
        caption=used,
        caption_plain=render_tokens(used, facts),
        template_caption=caption,
        routes=routes,
        robustness=robustness,
        fact_ids=_cited([used, *why, *(v for t in tables for v in t.values())]),
        validated=validate(used, facts, names).ok,
        fallback=fallback,
        made_by_model=made_by_model,
        reasons=reasons,
        notes=notes,
        error=error,
        meta=meta,
        prompt_sha256=prompt_sha,
    )


def log_lines(draft: PrismDraft, client: ModelClient) -> list[dict[str, Any]]:
    """One ``ai_calls.jsonl`` line per model call of a Prism draft (the caller writes them)."""
    lines = []
    for i, meta in enumerate(draft.meta, 1):
        last = i == len(draft.meta)
        entry = payload_log.log_entry(
            "prism_draft",
            client.provider,
            client.model,
            meta,
            draft.caption if last else "",
            draft.made_by_model if last else False,
            draft.fallback if last else False,
        )
        lines.append(entry | {"call": i, "of": len(draft.meta), "prompt_sha256": PROMPT_SHA256})
    return lines


__all__ = [
    "DEFAULT_TEMPLATE",
    "PROMPT_SHA256",
    "PrismDraft",
    "default_genes",
    "draft_prism_project",
    "log_lines",
    "private_names",
    "template_caption",
]
