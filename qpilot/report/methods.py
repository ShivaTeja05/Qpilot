"""The Methods section: what was done to this study, in words a paper can use, every number a fact.

Paragraphs: the data, the curve analysis, reference genes and normalisation, groups and the
comparison, robustness to analysis choices, the decisions (with who made them and why), the audit
when one was run, and software and reporting. Each says only what the record shows; where the
study leaves something open (a choice not yet decided) the paragraph says so.
"""

from __future__ import annotations

from collections import Counter

from qpilot.io.datasets import VERMEULEN_SHA256
from qpilot.qpcr.confidence_checks import HOLDS_MIN
from qpilot.report.context import Ctx
from qpilot.report.model import Citation, MethodsParagraph, MethodsView
from qpilot.report.text import Cite, Part, Q, pointer, tok, with_cites

#: Every reference the report may cite (numbered by first use in the Methods).
REFERENCES: dict[str, str] = {
    "rdml": (
        "Lefever S, Hellemans J, Pattyn F, et al. RDML: structured language and reporting "
        "guidelines for real-time quantitative PCR data. Nucleic Acids Res. 2009;37(7):2065–2069."
    ),
    "vermeulen2009": (
        "Vermeulen J, De Preter K, Naranjo A, et al. Predicting outcomes for children with "
        "neuroblastoma using a multigene-expression signature: a retrospective SIOPEN/COG/GPOH "
        "study. Lancet Oncol. 2009;10(7):663–671."
    ),
    "ruijter2013": (
        "Ruijter JM, Pfaffl MW, Zhao S, et al. Evaluation of qPCR curve analysis methods for "
        "reliable biomarker discovery: bias, resolution, precision, and implications. Methods. "
        "2013;59(1):32–46. doi:10.1016/j.ymeth.2012.08.011"
    ),
    "ruijter2009": (
        "Ruijter JM, Ramakers C, Hoogaars WMH, et al. Amplification efficiency: linking baseline "
        "and bias in the analysis of quantitative PCR data. Nucleic Acids Res. 2009;37(6):e45. "
        "doi:10.1093/nar/gkp045"
    ),
    "untergasser2021": (
        "Untergasser A, Ruijter JM, et al. Web-based LinRegPCR: application for the visualization "
        "and analysis of (RT)-qPCR amplification and melting data. BMC Bioinformatics. "
        "2021;22:398."
    ),
    "vandesompele2002": (
        "Vandesompele J, De Preter K, Pattyn F, et al. Accurate normalization of real-time "
        "quantitative RT-PCR data by geometric averaging of multiple internal control genes. "
        "Genome Biol. 2002;3(7):research0034. doi:10.1186/gb-2002-3-7-research0034"
    ),
    "welch1947": (
        "Welch BL. The generalization of 'Student's' problem when several different population "
        "variances are involved. Biometrika. 1947;34(1–2):28–35."
    ),
    "miqe2": (
        "Bustin SA, Ruijter JM, van den Hoff MJB, et al. MIQE 2.0: revision of the Minimum "
        "Information for Publication of Quantitative Real-Time PCR Experiments guidelines. "
        "Clin Chem. 2025;71(6):634–651. doi:10.1093/clinchem/hvaf043"
    ),
}


class Cites:
    """Citation numbers in order of first use."""

    def __init__(self) -> None:
        self.order: list[str] = []

    def __call__(self, key: str) -> Cite:
        """The marker for a reference (numbered the first time it is cited)."""
        if key not in self.order:
            self.order.append(key)
        return Cite(self.order.index(key) + 1)

    def list(self) -> list[Citation]:
        """The numbered reference list."""
        return [Citation(n=i + 1, id=k, text=REFERENCES[k]) for i, k in enumerate(self.order)]


def _names(names: list[str] | tuple[str, ...]) -> str:
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


# ---- paragraphs ----------------------------------------------------------------------------------


def data(c: Ctx, cite: Cites) -> list[Part]:
    """The data: what was read, from which file."""
    r = c.result
    plates = c.count("n_plates", r.n_plates, "results.json:/n_plates")
    parts: list[Part] = []
    reactions = tok("f_n_reactions") if c.has("f_n_reactions") else None
    samples = tok("f_n_samples") if c.has("f_n_samples") else None
    lead = "Raw fluorescence"
    if reactions:
        lead += f" of {reactions} reactions"
    lead += f" on {plates} plates"
    if samples:
        lead += f" ({samples} samples)"
    parts.append(lead + " was read from ")
    name = c.inputs.source.name if c.inputs.source is not None else None
    meta = c.inputs.rdml
    if name:
        parts += ["the RDML file ", Q(name)]
    else:
        parts.append("an RDML file")
    parts.append(" ")
    parts.append(cite("rdml"))
    inner = []
    if meta is not None and meta.version:
        inner.append(
            f"RDML version {c.word('rdml_version', meta.version, 'input.rdml:/rdml/version')}"
        )
    sha = c.word("input_sha256", r.input_sha256, "results.json:/input_sha256")
    inner.append(f"SHA-256 {sha}")
    parts.append(" (" + "; ".join(inner) + ").")
    if r.input_sha256 == VERMEULEN_SHA256:
        parts += [
            " These are the published neuroblastoma data of Vermeulen et al. ",
            cite("vermeulen2009"),
            ", as redistributed for the curve-analysis benchmark of Ruijter and colleagues ",
            cite("ruijter2013"),
            ".",
        ]
    if meta is not None and meta.instruments:
        parts += [" Instrument named in the file: ", Q("; ".join(meta.instruments)), "."]
    return parts


def curves(c: Ctx, cite: Cites) -> list[Part]:
    """The curve analysis: LinRegPCR, efficiency, amplification calls, wells without a value."""
    r = c.result
    parts: list[Part] = [
        "Each well's baseline, amplification efficiency and starting quantity (N0) were "
        "estimated with LinRegPCR ",
        cite("ruijter2009"),
        cite("untergasser2021"),
    ]
    commit = c.version("rdmlpython_vendored")
    if commit:
        parts.append(
            f", using the RDML consortium's rdmlpython vendored unchanged at commit {commit}"
        )
    parts.append(
        "; Cq is TD0, the cycle where the third derivative of the curve crosses zero (qPilot "
        "compares N0, not Cq)."
    )
    eff = r.efficiency
    if eff:
        n = c.count("n_assays", len(eff), "results.json:/efficiency@len")
        lo = c.num("eff_min", min(eff.values()), "results.json:/efficiency@min")
        hi = c.num("eff_max", max(eff.values()), "results.json:/efficiency@max")
        sentence = (
            " Each assay's efficiency is the mean of its wells' individual efficiencies, from "
            f"{lo} to {hi} across the {n} assays"
        )
        if c.has("f_eff_median"):
            sentence += f" (median {tok('f_eff_median')})"
        parts.append(sentence + ", as amplification factor per cycle; N0 uses that mean.")
    if c.has("f_amp_primary"):
        parts.append(f" A curve counts as amplified by {tok('f_amp_primary')}.")
    if c.has("f_n_undetermined", "f_n_unknown_wells", "f_pct_undetermined"):
        parts.append(
            f" Of {tok('f_n_unknown_wells')} sample wells, {tok('f_n_undetermined')} "
            f"({tok('f_pct_undetermined')}) gave no quantity"
        )
        card = next((x for x in c.inputs.cards if x.kind == "undetermined"), None)
        option = (card.decision or card.recommended) if card is not None else None
        if card is not None and option is not None:
            verb = "they were left out" if option == "drop" else "they were counted as very low"
            parts += [f"; {verb} (", Q(c.option_label(card, option) or option), ")"]
        parts.append(".")
    design = c.inputs.design
    excluded = list(design.excluded_wells) if design is not None else []
    if excluded:
        n = c.count("n_excluded", len(excluded), "study_design.json:/excluded_wells@len")
        word = _plural(len(excluded), "well", "wells")
        parts += [f" A person excluded {n} {word}: ", Q(", ".join(excluded)), "."]
    return parts


def normalisation(c: Ctx, cite: Cites) -> list[Part]:
    """Reference genes: geNorm M and V, the set used, the group-effect check."""
    g = c.result.genorm
    parts: list[Part] = []
    if g.M_initial:
        m = g.M_initial
        n = c.count("n_candidates", len(m), "results.json:/genorm/M_initial@len")
        best = min(m, key=lambda k: m[k])
        worst = max(m, key=lambda k: m[k])
        lo = c.num("m_min", m[best], "results.json:/genorm/M_initial@min")
        hi = c.num("m_max", m[worst], "results.json:/genorm/M_initial@max")
        cut_m = c.num("cutoff_m", g.cutoff_M, "results.json:/genorm/cutoff_M", fmt="{:g}")
        parts += [
            f"The {n} candidate control genes (",
            Q(_names(list(m))),
            ") were ranked by geNorm stability M ",
            cite("vandesompele2002"),
            f": M from {lo} (",
            Q(best),
            f") to {hi} (",
            Q(worst),
            ")",
        ]
        stable = [k for k, v in m.items() if v < g.cutoff_M]
        if stable:
            n_stable = c.count(
                "n_stable", len(stable), f"results.json:/genorm/M_initial@below={g.cutoff_M:g}"
            )
            parts.append(f"; {n_stable} below the usual cut-off M {cut_m}")
        else:
            parts.append(f"; none is below the usual cut-off M {cut_m}")
        if c.has("f_genorm_v_min"):
            cut_v = c.num("cutoff_v", g.cutoff_V, "results.json:/genorm/cutoff_V", fmt="{:g}")
            parts.append(
                f", and the lowest pairwise variation V is {tok('f_genorm_v_min')} (usual "
                f"cut-off {cut_v})"
            )
        parts.append(". ")
    refs = list(c.result.design.refs_primary)
    if refs:
        n = c.count("n_refs", len(refs), "results.json:/design/refs_primary@len")
        parts += [
            f"Each gene's quantity was divided by the geometric mean of {n} control "
            f"{_plural(len(refs), 'gene', 'genes')} (",
            Q(_names(refs)),
            ") in each biological unit, on the log2 scale",
        ]
        card = next((x for x in c.inputs.cards if x.kind == "reference_set"), None)
        if card is not None:
            parts += _card_clause(c, card)
        parts.append(".")
    if c.has("f_n_ref_pairs_flagged", "f_n_ref_pairs", "f_ref_flag_fold"):
        parts.append(
            f" Between the groups, {tok('f_n_ref_pairs_flagged')} of {tok('f_n_ref_pairs')} "
            f"control-gene pairs shift by at least {tok('f_ref_flag_fold')}"
        )
        if c.has("f_ref_pair_top", "f_ref_ratio_top", "f_ref_ratio_top_p"):
            parts.append(
                f" (largest {tok('f_ref_pair_top')}: {tok('f_ref_ratio_top')}, p "
                f"{tok('f_ref_ratio_top_p')})"
            )
        parts.append(".")
    return parts


def _card_clause(c: Ctx, card) -> list[Part]:  # noqa: ANN001 - DecisionCard
    """``; a person chose this (“reason”)`` and the like, for one card."""
    label = c.option_label(card, card.decision or card.recommended)
    if card.status == "decided" and card.decided_by == "human":
        out: list[Part] = ["; a person chose “", Q(label or ""), "”"]
        if card.reason:
            out += [" (“", Q(card.reason), "”)"]
        return out
    if card.status == "decided":
        return ["; chosen by ", Q(card.decided_by or "the system"), ": ", Q(label or "")]
    if card.status == "auto_decided":
        return ["; set automatically because no option changes a conclusion at this analysis"]
    return ["; this is the recommended option and the choice is still open"]


def comparison(c: Ctx, cite: Cites) -> list[Part]:
    """Groups and the comparison: the test, the rule, the calls."""
    r = c.result
    rule = r.conclusion_rule
    alpha = f"{rule.get('alpha', 0.05):g}"
    fold = f"{2 ** rule.get('min_log2fc', 1.0):g}"
    a, b = c.group_names
    parts: list[Part] = []
    hi = tok("f_n_hi") if c.has("f_n_hi") else None
    lo = tok("f_n_lo") if c.has("f_n_lo") else None
    if c.marker_mode:
        cut = c.num("cut", r.design.cut, "results.json:/design/cut", fmt="{:.0%}")
        parts += ["Biological units were split by the expression of ", Q(c.marker or a)]
        parts.append(f": the top {cut} form the ")
        parts += [Q(a), " group"]
        if hi:
            parts.append(f" ({hi} units)")
        parts.append(" and the rest the reference group")
        if lo:
            parts.append(f" ({lo} units)")
        parts.append("; the groups are defined from the data, not by a clinical call. ")
    else:
        parts += ["The groups come from the confirmed design: ", Q(a)]
        if hi:
            parts.append(f" ({hi} units)")
        parts += [" against ", Q(b)]
        if lo:
            parts.append(f" ({lo} units)")
        parts.append(". ")
    parts += [
        "Technical replicates were averaged within each biological unit (mean log2 N0) and "
        "never counted as n. Each gene was compared between the groups with Welch's t-test ",
        cite("welch1947"),
        " on per-unit log2 normalised quantities; fold changes are reported with 95 % confidence "
        f"intervals. A gene is called up or down only if p < {alpha} and the change is at least "
        f"{fold}-fold; otherwise it has no call.",
    ]
    if c.has("f_n_genes"):
        parts.append(
            f" No correction for multiple testing was applied across the {tok('f_n_genes')} genes."
        )
    parts.append(
        f" At this analysis {c.call_count('up')} genes are up, {c.call_count('down')} down and "
        f"{c.call_count('none')} have no call"
    )
    if c.has("f_n_withheld") and int(c.facts.value("f_n_withheld") or 0) > 0:
        parts.append(f"; {tok('f_n_withheld')} genes were withheld (too few values in a group)")
    parts.append(".")
    return parts


def robustness(c: Ctx, cite: Cites) -> list[Part]:
    """QPilot's choice grid: its size, what it varies, how many calls hold."""
    if not c.has("f_n_cells"):
        return []
    opts = c.inputs.grid_options
    what = {
        "refs": ("control-gene set", "control-gene sets"),
        "cut": ("group cut-off", "group cut-offs"),
        "undetermined": ("rule for wells without a quantity", "rules for wells without a quantity"),
        "amp_call": ("amplification-call rule", "amplification-call rules"),
    }
    dims = []
    for dim, options in opts.items():
        one, many = what.get(dim, (dim.replace("_", " "), dim.replace("_", " ")))
        n = c.count(f"grid_{dim}", len(options), f"grid.csv:{pointer(dim)}@len")
        dims.append(f"{n} {_plural(len(options), one, many)}")
    parts: list[Part] = [
        f"Every conclusion was recomputed under the {tok('f_n_cells')} analyses qPilot checks "
        "(qPilot's choice grid"
    ]
    parts.append(": every combination of " + _names(dims) + ")." if dims else ").")
    holds = c.num("holds_min", HOLDS_MIN, "qpilot.qpcr.confidence_checks:/HOLDS_MIN", fmt="{:.0%}")
    if c.has("f_n_hold_lt_80", "f_n_genes"):
        parts.append(
            f" {tok('f_n_hold_lt_80')} of {tok('f_n_genes')} genes keep their call in fewer than "
            f"{holds} of them."
        )
    alone = [
        (fid, label)
        for fid, label in (
            ("f_n_flipped_refset", "the control genes"),
            ("f_n_flipped_cutoff", "the group cut-off"),
            ("f_n_flipped_amp_call", "the amplification-call rule"),
            ("f_n_flipped_undetermined", "the rule for wells without a quantity"),
        )
        if c.has(fid)
    ]
    if alone:
        first, *rest = alone
        bits = [f"{label} alone {tok(fid)}" for fid, label in rest]
        text = f" {first[1][:1].upper()}{first[1][1:]} alone change {tok(first[0])} calls"
        parts.append(text + (", " + _names(bits) if bits else "") + ".")
    return parts


def decisions(c: Ctx, cite: Cites) -> list[Part]:
    """The decision log: each card's option, who chose it and why; the Studio proposals."""
    entries = c.inputs.entries
    n = c.count("n_entries", len(entries), "decisions.jsonl:@len")
    head = c.word("chain_head", c.inputs.head, "decisions.jsonl:@head")
    parts: list[Part] = [
        f"The analysis choices are recorded in a hash-chained decision log ({n} "
        f"{_plural(len(entries), 'entry', 'entries')}; head {head}). "
    ]
    for card in c.inputs.cards:
        label = c.option_label(card, card.decision or card.recommended) or ""
        parts += [Q(c.card_title(card)), ": ", Q(label)]
        if card.status == "decided":
            who = {"human": "a person", "agent": "an agent"}.get(card.decided_by or "", "")
            parts.append(f", decided by {who or 'the system'}")
            if card.reason:
                parts += [" (“", Q(card.reason), "”)"]
        elif card.status == "auto_decided":
            parts.append(", set automatically because no option changes a conclusion here")
        elif card.status == "pending_human":
            parts.append(", the recommended option; an agent's request waits for a person")
        else:
            parts.append(", the recommended option; still open")
            if card.impact.get("flips"):
                parts.append(" (another option changes at least one conclusion)")
        parts.append(". ")
    proposals = c.inputs.proposals
    if proposals:
        acts = Counter(str(p.get("action", "")) for p in proposals)
        by_human = Counter(str(p.get("action", "")) for p in proposals if p.get("actor") == "human")
        path = "proposals.jsonl:@count=action:"
        made = Counter(
            str(((p.get("proposal") or {}).get("made_by") or {}).get("kind", ""))
            for p in proposals
            if p.get("action") == "propose"
        )
        proposed = c.count("n_proposed", acts["propose"], path + "propose")
        accepted = c.count("n_accepted", by_human["accept"], path + "accept,actor:human")
        rejected = c.count("n_rejected", by_human["reject"], path + "reject,actor:human")
        kinds = []
        for kind, words in (("rule", "by rules"), ("model", "by a model"), ("agent", "by agents")):
            if made[kind]:
                n_kind = c.count(f"n_made_{kind}", made[kind], f"{path}propose,made_by:{kind}")
                kinds.append(f"{n_kind} {words}")
        parts.append(
            f"In Studio, {proposed} proposals about the design and the curves were made"
            + (f" ({_names(kinds)})" if kinds else "")
            + f"; a person accepted {accepted} and rejected {rejected} before the design and the "
            "curves were confirmed."
        )
    if c.inputs.pending:
        n_p = c.count("n_pending", len(c.inputs.pending), "pending.jsonl:@len")
        parts.append(f" {n_p} agent requests wait for a person.")
    return parts


def audit(c: Ctx, cite: Cites) -> list[Part]:
    """The robustness audit, when one was run."""
    a = c.inputs.audit
    if a is None:
        return []
    parts: list[Part] = []
    try:
        version = c.audit_num("qsim_version", "summary.json", "qsim_version")
    except (KeyError, TypeError):
        version = None
    levels = (a.summary.get("space") or {}).get("levels")
    lead = "A robustness audit (qPilot's Decision Simulator"
    lead += f", qsim {version})" if version else ")"
    lead += " re-ran the confirmed study under every combination of "
    if isinstance(levels, list) and levels:
        n_dec = c.count("audit_n_decisions", len(levels), "audit:summary.json:/space/levels@len")
        lead += f"{n_dec} analysis decisions"
    else:
        lead += "its analysis decisions"
    try:
        n_all = c.audit_num("analyses", "audit_manifest.json", "analyses", fmt="{:,}")
        lead += f" ({n_all} analyses)"
    except (KeyError, TypeError):
        pass
    parts.append(lead)
    rep = a.manifest.get("reproduces_qpilot") or {}
    if rep.get("ok") is True:
        try:
            genes = c.audit_num(
                "reproduced_genes", "audit_manifest.json", "reproduces_qpilot", "genes"
            )
            diff = c.audit_num(
                "max_diff_log2fc",
                "audit_manifest.json",
                "reproduces_qpilot",
                "max_abs_diff_log2fc",
                fmt="{:.1g}",
            )
            parts.append(
                f", after reproducing qPilot's comparison of all {genes} genes (largest "
                f"difference in log2 fold change {diff})"
            )
        except (KeyError, TypeError):
            pass
    elif rep:
        parts.append(", but it did not reproduce qPilot's comparison exactly (see the audit)")
    parts.append(".")
    counts = a.manifest.get("verdict_counts") or {}
    try:
        reasonable = c.audit_num("reasonable", "summary.json", "multiverse", "defensible", "cells")
    except (KeyError, TypeError):
        reasonable = None
    if counts:
        words = []
        for key, phrase in VERDICT_PHRASES:
            if key in counts:
                n_v = c.audit_num(
                    f"verdict_{key.replace(' ', '_')}", "audit_manifest.json", "verdict_counts", key
                )
                words.append(f"{n_v} {phrase}")
        lead = " In the audit's reasonable set"
        if reasonable:
            lead += (
                f" ({reasonable} analyses: no shortcuts such as single or paired control genes; "
                "groups and multiplicity as planned)"
            )
        parts.append(lead + ", " + _names(words) + ".")
    if c.audit_current:
        parts.append(" It was run at the decision log's current head.")
    else:
        head = a.manifest.get("chain_head")
        if isinstance(head, str) and head:
            word = c.word("audit_head", head, "audit:audit_manifest.json:/chain_head")
            parts.append(
                f" It was run at an earlier head of the decision log ({word}); decisions made "
                "since are not in it."
            )
    return parts


#: Verdicts in the audit's order, and how a sentence counts them.
VERDICT_PHRASES = (
    ("solid", "genes are solid"),
    ("holds with caveats", "hold with caveats"),
    ("depends on your choices", "depend on the choices"),
    ("fragile", "are fragile"),
    ("check data first", "need their data checked first"),
    ("no call", "have no call"),
)


def software(c: Ctx, cite: Cites) -> list[Part]:
    """Software versions and reporting standard."""
    parts: list[Part] = []
    qp = c.version("qpilot")
    text = "Analysis with qPilot" + (f" {qp}" if qp else "")
    git = c.version("qpilot_git")
    if git:
        text += f" (git {git})"
    py = c.version("python")
    if py:
        text += f" on Python {py}"
    text += (
        "; LinRegPCR from rdmlpython (MIT licence), geNorm reimplemented from its paper and "
        "Welch's test from SciPy's t distribution"
    )
    if c.inputs.audit is not None:
        text += ", and the audit with qPilot's Decision Simulator"
    parts.append(
        text + ". The study's Analysis Record (the input file, every decision and their "
        "checksums) re-runs to the same numbers with qpilot rerun. Reported following MIQE 2.0 "
    )
    parts += [cite("miqe2"), "; the checklist is attached."]
    return parts


PARAGRAPHS = (
    ("data", "Data", data),
    ("curves", "Curve analysis", curves),
    ("normalisation", "Reference genes and normalisation", normalisation),
    ("comparison", "Groups and comparison", comparison),
    ("robustness", "Robustness to analysis choices", robustness),
    ("decisions", "Analysis decisions", decisions),
    ("audit", "Robustness audit", audit),
    ("software", "Software and reporting", software),
)


def methods(c: Ctx) -> MethodsView:
    """The Methods section of the study."""
    cite = Cites()
    paragraphs = []
    for pid, title, build in PARAGRAPHS:
        parts = build(c, cite)
        if parts:
            paragraphs.append(MethodsParagraph(id=pid, title=title, text=c.t(*parts)))
    citations = cite.list()
    plain = "\n\n".join(p.text.plain for p in paragraphs)
    cited = "\n\n".join(with_cites(p.text) for p in paragraphs)
    if citations:
        cited += "\n\nReferences\n" + "\n".join(f"{x.n}. {x.text}" for x in citations)
    return MethodsView(
        paragraphs=paragraphs, citations=citations, plain=plain, with_citations=cited
    )
