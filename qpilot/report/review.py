"""The reviewer's report and the limitations: what a careful qPCR reviewer would flag.

Eight questions a reviewer asks (R1–R8, from the rule list drafted on branch ``agents/report``
after MIQE 2.0, Vandesompele 2002, Ruiz-Villalba 2021 and Drude 2026) plus what only qPilot can
see: headline genes whose call leans on one analysis choice, choices still open that can change a
conclusion, the audit's "check the data first" genes and a group layout clustered on the plate.
Every finding is read from the study's numbers (facts); none is a model's opinion. Severity:
**major** (could change what the paper claims), **minor** (should be reported or fixed), **note**.
"""

from __future__ import annotations

from collections import Counter

from qpilot.explain.sets import verdict_differs
from qpilot.qpcr.confidence_checks import HOLDS_MIN
from qpilot.report.context import Ctx, dim_label
from qpilot.report.model import Limitation, ReviewCheck, ReviewFinding, ReviewView, Severity
from qpilot.report.text import Part, Q, safe_slug, tok

SEVERITIES: tuple[Severity, ...] = ("major", "minor", "note")
#: Audit verdicts a reviewer would query for a headline gene.
DOUBTFUL = ("fragile", "depends on your choices", "check data first")


def _names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _reasonable(c: Ctx) -> str | None:
    """The audit's reasonable set, as a fact token (None without that count)."""
    try:
        return c.audit_num("reasonable", "summary.json", "multiverse", "defensible", "cells")
    except (KeyError, TypeError):
        return None


def _holds(c: Ctx) -> str:
    return tok(
        c.facts.derive(
            "holds_min", HOLDS_MIN, "qpilot.qpcr.confidence_checks:/HOLDS_MIN", fmt="{:.0%}"
        )
    )


class Review:
    """Collects findings and passed checks."""

    def __init__(self, c: Ctx) -> None:
        self.c = c
        self.findings: list[ReviewFinding] = []
        self.passed: list[ReviewCheck] = []

    def flag(
        self,
        fid: str,
        severity: Severity,
        title: str,
        parts: list[Part],
        *,
        genes: list[str] | None = None,
        go_to: str | None = None,
        rule: str | None = None,
    ) -> None:
        """Add a finding."""
        self.findings.append(
            ReviewFinding(
                id=fid,
                severity=severity,
                title=title,
                text=self.c.t(*parts),
                genes=genes or [],
                go_to=go_to,  # type: ignore[arg-type]
                rule=rule,
            )
        )

    def ok(self, cid: str, title: str, parts: list[Part]) -> None:
        """Add a check the study passes."""
        self.passed.append(ReviewCheck(id=cid, title=title, text=self.c.t(*parts)))


# ---- R1–R8 ---------------------------------------------------------------------------------------


def reference_genes(rv: Review) -> None:
    """R1 and R3: stability of the control genes, the set used, their shift between groups."""
    c = rv.c
    g = c.result.genorm
    m = g.M_initial
    refs = list(c.result.design.refs_primary)
    if m:
        best = min(m, key=lambda k: m[k])
        lo = c.num("m_min", m[best], "results.json:/genorm/M_initial@min")
        cut = c.num("cutoff_m", g.cutoff_M, "results.json:/genorm/cutoff_M", fmt="{:g}")
        stable = [k for k, v in m.items() if v < g.cutoff_M]
        n = c.count("n_candidates", len(m), "results.json:/genorm/M_initial@len")
        if not stable:
            parts: list[Part] = [
                f"None of the {n} candidate control genes reaches geNorm's usual stability "
                f"cut-off (lowest M {lo}, for ",
                Q(best),
                f"; cut-off M {cut})",
            ]
            if c.has("f_genorm_v_min"):
                cut_v = c.num("cutoff_v", g.cutoff_V, "results.json:/genorm/cutoff_V", fmt="{:g}")
                parts.append(
                    f" and the pairwise variation never falls below its cut-off (lowest V "
                    f"{tok('f_genorm_v_min')}; cut-off {cut_v})"
                )
            parts.append(". Normalisation is this study's weakest link")
            if c.has("f_n_flipped_refset", "f_n_genes"):
                parts.append(
                    f": the control genes alone change {tok('f_n_flipped_refset')} of "
                    f"{tok('f_n_genes')} calls"
                )
            parts.append(
                ". Report the M values and treat calls that lean on this choice as tentative."
            )
            rv.flag(
                "weak_normalisation",
                "major",
                "No stable control gene",
                parts,
                go_to="results",
                rule="R1",
            )
        else:
            n_s = c.count(
                "n_stable", len(stable), f"results.json:/genorm/M_initial@below={g.cutoff_M:g}"
            )
            rv.ok(
                "stable_refs",
                "Stable control genes",
                [f"{n_s} of {n} candidate control genes are below geNorm's usual cut-off M {cut}."],
            )
    if c.has("f_n_ref_pairs_flagged", "f_n_ref_pairs", "f_ref_flag_fold"):
        flagged = int(c.facts.value("f_n_ref_pairs_flagged") or 0)
        if flagged:
            parts = [
                f"{tok('f_n_ref_pairs_flagged')} of {tok('f_n_ref_pairs')} control-gene pairs "
                f"shift by at least {tok('f_ref_flag_fold')} between the groups"
            ]
            if c.has("f_ref_pair_top", "f_ref_ratio_top", "f_ref_ratio_top_p"):
                parts.append(
                    f" (largest {tok('f_ref_pair_top')}: {tok('f_ref_ratio_top')}, p "
                    f"{tok('f_ref_ratio_top_p')})"
                )
            parts.append(
                ". A control gene that moves with the groups biases every fold change it divides."
            )
            rv.flag(
                "refs_shift", "minor", "Control genes differ between the groups", parts,
                go_to="results", rule="R1",
            )  # fmt: skip
    if len(refs) >= 2:
        n_r = c.count("n_refs", len(refs), "results.json:/design/refs_primary@len")
        rv.ok(
            "geomean",
            "Normalised to several control genes",
            [f"The geometric mean of {n_r} control genes, not a single gene."],
        )
    elif refs:
        rv.flag(
            "single_ref",
            "major",
            "One control gene",
            ["Every quantity is divided by one control gene: ", Q(refs[0]), "; MIQE 2.0 asks for "
             "at least two, validated."],
            go_to="results",
            rule="R3",
        )  # fmt: skip


def _cq_efficiency(rv: Review) -> None:
    """R2 for a file of Cq values only: measured from each assay's dilution series, or not."""
    c = rv.c
    assumed = int(c.result.facts["f_n_eff_assumed"].value) if c.has("f_n_eff_assumed") else 0
    if not assumed:
        rv.ok(
            "efficiency",
            "Efficiency measured, not assumed",
            ["The file holds Cq values only; each assay's efficiency is from its dilution "
             "series, used in every quantity."],
        )  # fmt: skip
        return
    rv.flag(
        "no_efficiency", "major", "Efficiency assumed",
        ["The file holds Cq values only (no curves), and these assays have no dilution series, so "
         f"their efficiency is assumed: {tok('f_eff_assumed_genes')}. A dilution series of each "
         "assay on the plate would measure it."],
        rule="R2",
    )  # fmt: skip


def efficiency(rv: Review) -> None:
    """R2: efficiency measured and used."""
    c = rv.c
    eff = c.result.efficiency
    if c.has("f_cq_only"):  # a file of Cq values only: a dilution series, or assumed
        _cq_efficiency(rv)
        return
    if eff:
        lo = c.num("eff_min", min(eff.values()), "results.json:/efficiency@min")
        hi = c.num("eff_max", max(eff.values()), "results.json:/efficiency@max")
        rv.ok(
            "efficiency",
            "Efficiency measured, not assumed",
            [f"Per well by LinRegPCR; assay means from {lo} to {hi}, used in every quantity."],
        )
    else:
        rv.flag(
            "no_efficiency", "major", "Efficiency assumed",
            ["No efficiency is in this study: quantities assume one."], rule="R2",
        )  # fmt: skip


def biological_n(rv: Review) -> None:
    """R4 and R5: n counts biological units; the test runs on per-unit log quantities."""
    c = rv.c
    if not c.has("f_n_hi", "f_n_lo"):
        return
    small = min(int(c.facts.value("f_n_hi")), int(c.facts.value("f_n_lo")))
    if small < 3:
        rv.flag(
            "small_n", "major", "Too few biological units",
            [f"The groups hold {tok('f_n_hi')} and {tok('f_n_lo')} biological units."],
            go_to="results", rule="R4",
        )  # fmt: skip
    else:
        rv.ok(
            "biological_n",
            "n counts biological units",
            [
                f"{tok('f_n_hi')} and {tok('f_n_lo')} units; technical replicates are averaged "
                "within a unit and tested on the log2 scale."
            ],
        )


def nondetects(rv: Review) -> None:
    """R6: wells without a quantity and the amplification-call rule."""
    c = rv.c
    if c.has("f_n_flipped_undetermined") and int(c.facts.value("f_n_flipped_undetermined")) == 0:
        rv.ok(
            "undetermined",
            "Wells without a quantity",
            [
                "Dropping them or counting them as very low changes "
                f"{tok('f_n_flipped_undetermined')} calls."
            ],
        )
    worst = None
    for key in ("cq_le_35", "cq_le_38", "cq_le_40"):
        fid, label = f"f_n_flipped_amp_{key}", f"f_amp_label_{key}"
        if c.has(fid, label) and int(c.facts.value(fid)) > 0:
            worst = worst or (fid, label)
    if worst and c.has("f_amp_primary"):
        rv.flag(
            "amp_rule",
            "minor",
            "Late curves decide some calls",
            [
                f"Under the rule {tok(worst[1])}, {tok(worst[0])} calls change; this study counts "
                f"a curve as amplified by {tok('f_amp_primary')}. State the rule and its cut-off.",
            ],
            go_to="results",
            rule="R6",
        )


def controls(rv: Review) -> None:
    """R7: no-template and no-RT controls."""
    c = rv.c
    design = c.inputs.design
    roles = Counter(s.role for s in design.samples.values()) if design is not None else Counter()
    meta = c.inputs.rdml
    nrt = roles.get("nrt", 0) + (meta.sample_types.get("nrt", 0) if meta else 0)
    if (design is not None or meta is not None) and not nrt:
        rv.flag(
            "no_nrt",
            "minor",
            "No no-RT controls",
            [
                "The study has no no-RT control samples. MIQE 2.0 no longer requires them once "
                "the samples are shown to be free of genomic DNA; say how that was shown."
            ],
            go_to="design" if c.inputs.session else None,
            rule="R7",
        )
    ntc, where, path = (
        roles.get("ntc", 0),
        "in the design",
        "study_design.json:/samples@count=role:ntc",
    )
    if not ntc and meta is not None and meta.sample_types.get("ntc"):
        ntc, where, path = (
            meta.sample_types["ntc"],
            "in the RDML file",
            "input.rdml:/sample/type@count=ntc",
        )
    if ntc:
        n = c.count("role_ntc" if where == "in the design" else "rdml_ntc", ntc, path)
        audit = c.inputs.audit
        obs = (
            (audit.summary.get("troubleshooting") or {}).get("observations") or {} if audit else {}
        )
        parts: list[Part] = [f"{n} no-template control samples are typed {where}"]
        if isinstance(obs.get("ntc"), int) and obs["ntc"] > 0:
            k = c.audit_num(
                "ntc_observations", "summary.json", "troubleshooting", "observations", "ntc"
            )
            parts.append(
                f"; the audit lists {k} observations on them. Report how often they amplified."
            )
            rv.flag("ntc", "note", "No-template controls", parts, go_to="audit", rule="R7")
        else:
            rv.ok("ntc", "No-template controls typed", [*parts, "."])


def disclosure(rv: Review) -> None:
    """R8: primer sequences and the raw curves in RDML."""
    c = rv.c
    meta = c.inputs.rdml
    if meta is None:
        return
    if not (meta.n_targets_with_primers or meta.n_targets_with_assay):
        total = c.count("rdml_n_targets", meta.n_targets, "input.rdml:/target@len")
        rv.flag(
            "no_primers",
            "minor",
            "Primer sequences are not in the file",
            [
                f"None of the {total} targets in the RDML file carries a primer or probe sequence "
                "or an assay id; the paper must give them (or the assay context sequences)."
            ],
            rule="R8",
        )
    if meta.n_reactions_with_curves:
        clause = c.reactions_in_file(meta.n_reactions_with_curves, meta.n_runs)
        where = f" ({clause})" if clause else ""
        n = c.count(
            "rdml_n_curves",
            meta.n_reactions_with_curves,
            "input.rdml:/react/data/adp@count",
            fmt="{:,}",
        )
        rv.ok(
            "raw_curves",
            "Raw curves can be deposited",
            [f"The RDML file holds the raw fluorescence of {n} reactions{where}."],
        )


# ---- what qPilot sees ----------------------------------------------------------------------------


def headline_genes(rv: Review) -> None:
    """Headline genes whose call leans on one analysis choice, or that the audit doubts."""
    c = rv.c
    verdicts = _verdicts(c)
    holds = _holds(c)
    for gene in c.headline:
        contrast = c.result.contrasts[gene]
        robust = c.result.robustness.get(gene)
        if contrast.conclusion == "none" or robust is None:
            continue
        s = safe_slug(gene)
        flips = sorted(
            d for d, v in robust.impact.items() if isinstance(v, dict) and v.get("flips")
        )
        verdict = verdicts.get(gene)
        weak = robust.holds < HOLDS_MIN
        if not (flips or weak or verdict in DOUBTFUL):
            continue
        parts: list[Part] = [f"{gene} ({contrast.conclusion}"]
        if c.has(f"f_fc_{s}_recommended"):
            parts[0] += f", {tok(f'f_fc_{s}_recommended')}"
        parts[0] += ")"
        if c.has(f"f_holds_{s}", "f_n_cells"):
            parts.append(
                f" keeps its call in {tok(f'f_holds_{s}')} of the {tok('f_n_cells')} analyses "
                "qPilot checks"
            )
            if weak:
                parts.append(f", fewer than {holds}")
        if flips:
            parts.append("; " + _names([dim_label(d) for d in flips]) + " alone can change it")
        parts.append(".")
        if verdict:
            parts += [" The audit's verdict: ", Q(_label(c, verdict)), "."]
            if weak and verdict not in DOUBTFUL:
                parts.append(" " + verdict_differs(_reasonable(c)))
        major = weak or verdict in DOUBTFUL
        rv.flag(
            f"headline_{s}",
            "major" if major else "minor",
            f"A headline call leans on a choice: {gene}",
            parts,
            genes=[gene],
            go_to="gene",
        )


def other_fragile(rv: Review) -> None:
    """Called genes outside the headline that hold in fewer than four out of five analyses."""
    c = rv.c
    weak = [
        g
        for g, con in c.result.contrasts.items()
        if g not in c.headline
        and con.conclusion != "none"
        and (r := c.result.robustness.get(g)) is not None
        and r.holds < HOLDS_MIN
    ]
    if not weak:
        return
    n = c.count(
        "n_weak_other",
        len(weak),
        "results.json:/robustness@count=called,holds_below_min,not_headline",
    )
    rv.flag(
        "other_fragile",
        "minor",
        "Other calls lean on the analysis choices",
        [
            f"{n} more called genes keep their call in fewer than {_holds(c)} of the analyses "
            "qPilot checks: ",
            Q(", ".join(weak)),
            ". Report them as tentative or show they hold.",
        ],
        genes=weak,
        go_to="results",
    )


def open_choices(rv: Review) -> None:
    """Choices that can change a conclusion and are not decided; agent requests waiting."""
    c = rv.c
    if c.open_flipping:
        n = c.count(
            "n_open_flipping",
            len(c.open_flipping),
            "cards.json:@count=status:open|pending_human,flips",
        )
        titles = "; ".join(c.card_title(card) for card in c.open_flipping)
        rv.flag(
            "open_choices",
            "major",
            "Choices that can change a conclusion are still open",
            [
                f"{n} choices that change at least one conclusion have not been decided by a "
                "person: ",
                Q(titles),
                ". The recommended options are used; decide each with a reason before reporting.",
            ],
            go_to="results",
        )
    if c.inputs.pending:
        n_p = c.count("n_pending", len(c.inputs.pending), "pending.jsonl:@len")
        rv.flag(
            "pending_requests", "minor", "Agent requests wait for a person",
            [f"{n_p} requests from an agent wait for a person's answer."], go_to="results",
        )  # fmt: skip


def groups(rv: Review) -> None:
    """Groups cut from the data, and how the cut-off moves the calls."""
    c = rv.c
    if not c.marker_mode:
        return
    cut = c.num("cut", c.result.design.cut, "results.json:/design/cut", fmt="{:.0%}")
    parts: list[Part] = [
        f"The groups are the top {cut} by expression of ",
        Q(c.marker or c.group_names[0]),
    ]
    parts.append(
        " against the rest, cut from the same data: genes that track the marker separate by "
        "construction"
    )
    if c.has("f_n_flipped_cutoff"):
        parts.append(f", and the cut-off alone changes {tok('f_n_flipped_cutoff')} calls")
    parts.append(". Present the results as associations with the marker's expression.")
    rv.flag("groups_from_data", "minor", "Groups defined from the data", parts, go_to="results")


def multiplicity(rv: Review) -> None:
    """No correction for multiple testing (and what the audit says about it)."""
    c = rv.c
    if not c.has("f_n_genes") or c.facts.value("f_n_genes") == 1:
        return  # one gene compared: there is nothing to correct across
    audit = c.inputs.audit
    alone = (audit.summary.get("question_choices_flip_alone") or {}) if audit else {}
    alpha = f"{c.result.conclusion_rule.get('alpha', 0.05):g}"
    if isinstance(alone.get("multiplicity"), int):
        k = c.audit_num(
            "multiplicity_flips", "summary.json", "question_choices_flip_alone", "multiplicity"
        )
        parts: list[Part] = [
            f"{tok('f_n_genes')} genes are tested at p < {alpha} without a correction for multiple "
            "testing; in the audit, a correction alone (Benjamini–Hochberg or Holm) changes "
            f"{k} calls."
        ]
        if alone["multiplicity"] == 0:
            rv.ok("multiplicity", "Multiple testing", parts)
            return
        rv.flag("multiplicity", "minor", "No correction for multiple testing", parts, go_to="audit")
        return
    rv.flag(
        "multiplicity", "minor", "No correction for multiple testing",
        [f"{tok('f_n_genes')} genes are tested at p < {alpha} with no correction for multiple "
         "testing; run the audit to see whether a correction changes any call."],
        go_to="audit",
    )  # fmt: skip


def audit_checks(rv: Review) -> None:
    """The audit: absent, out of date, genes to check first, a clustered plate layout."""
    c = rv.c
    a = c.inputs.audit
    if a is None:
        rv.flag(
            "no_audit", "note", "No robustness audit yet",
            ["Run the audit for each gene's verdict under every combination of the analysis "
             "decisions."],
            go_to="audit",
        )  # fmt: skip
        return
    if not c.audit_current:
        rv.flag(
            "audit_old", "minor", "The audit is of an earlier decision log",
            ["Decisions were made after the audit ran; run it again so its verdicts match."],
            go_to="audit",
        )  # fmt: skip
    verdicts = _verdicts(c)
    check = sorted(g for g, v in verdicts.items() if v == "check data first")
    if check:
        n = c.audit_num(
            "verdict_check_data_first", "audit_manifest.json", "verdict_counts", "check data first"
        )
        rv.flag(
            "check_data",
            "major",
            "Check these genes' data first",
            [f"The audit marks {n} genes “", Q("check data first"), "”: ", Q(", ".join(check)),
             ". Their call rests on a few samples or wells; look at them before reporting."],
            genes=check,
            go_to="audit",
        )  # fmt: skip
    ident = (a.summary.get("troubleshooting") or {}).get("identifiability") or {}
    p_row = ident.get("group_clustered_by_row_p")
    if isinstance(p_row, int | float) and p_row < 0.05:
        p = c.audit_num(
            "group_row_p", "summary.json", "troubleshooting", "identifiability",
            "group_clustered_by_row_p", fmt="{:.2g}",
        )  # fmt: skip
        rv.flag(
            "plate_layout",
            "minor",
            "Groups are clustered on the plate",
            [
                f"Group membership is clustered by plate row (p {p}): a spatial artefact on the "
                "plate could mimic a group difference. Say how the samples were laid out."
            ],
            go_to="audit",
        )


def withheld(rv: Review) -> None:
    """Genes the engine withheld."""
    c = rv.c
    if c.has("f_n_withheld") and int(c.facts.value("f_n_withheld") or 0) > 0:
        rv.flag(
            "withheld", "note", "Some genes were not compared",
            [f"{tok('f_n_withheld')} genes have too few values in a group to be compared; say so."],
            go_to="results",
        )  # fmt: skip


def _verdicts(c: Ctx) -> dict[str, str]:
    a = c.inputs.audit
    if a is None:
        return {}
    by_gene = (a.summary.get("verdicts") or {}).get("by_gene")
    if isinstance(by_gene, dict):
        return {str(g): str(v) for g, v in by_gene.items()}
    return {str(g): str(e.get("verdict")) for g, e in a.explain.items() if isinstance(e, dict)}


def _label(c: Ctx, verdict: str) -> str:
    try:
        from qsim.app import VERDICT_LABEL

        return str(VERDICT_LABEL.get(verdict, verdict))
    except Exception:  # the simulator is not installed: the verdict's own words
        return verdict


CHECKS = (
    open_choices,
    headline_genes,
    reference_genes,
    audit_checks,
    groups,
    other_fragile,
    nondetects,
    multiplicity,
    controls,
    disclosure,
    efficiency,
    biological_n,
    withheld,
)


def review(c: Ctx) -> ReviewView:
    """The reviewer's report: findings, most severe first, and what checks out."""
    rv = Review(c)
    for check in CHECKS:
        check(rv)
    order = {s: i for i, s in enumerate(SEVERITIES)}
    findings = sorted(rv.findings, key=lambda f: order[f.severity])  # stable within a severity
    counts = Counter(f.severity for f in findings)
    path = "report:/review/findings@count=severity:"
    toks = {s: c.count(f"review_{s}", counts[s], path + s) for s in SEVERITIES}
    lead = c.t(
        f"What a careful reviewer would raise: major points {toks['major']}, minor points "
        f"{toks['minor']}, notes {toks['note']}. Each is read from this study's own numbers; none "
        "is a model's opinion."
    )
    return ReviewView(
        lead=lead,
        findings=findings,
        passed=rv.passed,
        counts={s: counts[s] for s in SEVERITIES},
    )


def limitations(c: Ctx) -> list[Limitation]:
    """The study's limitations in plain words."""
    out: list[tuple[str, list[Part]]] = [
        (
            "research_use",
            [
                "Research use only; not for clinical use. A call says that the groups differ in "
                "these samples, not why."
            ],
        )
    ]
    if c.marker_mode:
        out.append(
            (
                "groups_from_data",
                [
                    "The groups are defined from the data (by the marker gene's expression), not "
                    "by an independent clinical call: the differences describe this split."
                ],
            )
        )
    if c.has("f_n_genes") and c.facts.value("f_n_genes") != 1:
        out.append(
            (
                "multiplicity",
                [
                    f"No correction for multiple testing across the {tok('f_n_genes')} genes in "
                    "the planned analysis."
                ],
            )
        )
    g = c.result.genorm
    if g.M_initial and not any(v < g.cutoff_M for v in g.M_initial.values()):
        out.append(
            (
                "refs",
                [
                    "No candidate control gene is stable by geNorm's usual cut-off, so fold "
                    "changes carry the control genes' own variation."
                ],
            )
        )
    out += [
        (
            "lod",
            [
                "Limits of detection and quantification were not determined; calls that rest on "
                "wells near detection depend on the rule for wells without a quantity."
            ],
        ),
        (
            "specificity",
            ["Melt curves are not analysed; assay specificity must be shown separately."],
        ),
        (
            "robustness_meaning",
            [
                "How often a call holds across reasonable analyses measures its sensitivity to "
                "analysis choices; it is not the probability that the call is true."
            ],
        ),
        (
            "record",
            [
                "The Analysis Record is tamper-evident, not tamper-proof: verifying it shows any "
                "change, but cannot prove who made it."
            ],
        ),
    ]
    if c.inputs.audit is None:
        out.append(("no_audit", ["No robustness audit was run for this study."]))
    return [Limitation(id=i, text=c.t(*parts)) for i, parts in out]
