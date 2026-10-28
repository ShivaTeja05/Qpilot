"""The Methods section: what was done to this study, in words a paper can use, every number a fact.

Paragraphs: the data, the curve analysis, reference genes and normalisation, groups and the
comparison, robustness to analysis choices, the decisions (with who made them and why), the audit
when one was run, and software and reporting. Each says only what the record shows; where the
study leaves something open (a choice not yet decided) the paragraph says so.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from qpilot.explain.words import noun
from qpilot.io.datasets import VERMEULEN_SHA256
from qpilot.io.inputs import input_label, is_converted
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
    "andersen2004": (
        "Andersen CL, Jensen JL, Ørntoft TF. Normalization of real-time quantitative reverse "
        "transcription-PCR data: a model-based variance estimation approach to identify genes "
        "suited for normalization, applied to bladder and colon cancer data sets. Cancer Res. "
        "2004;64(15):5245–5250. doi:10.1158/0008-5472.CAN-04-0496"
    ),
    "mestdagh2009": (
        "Mestdagh P, Van Vlierberghe P, De Weer A, et al. A novel and universal method for "
        "microRNA RT-qPCR data normalization. Genome Biol. 2009;10(6):R64. "
        "doi:10.1186/gb-2009-10-6-r64"
    ),
    "hellemans2007": (
        "Hellemans J, Mortier G, De Paepe A, Speleman F, Vandesompele J. qBase relative "
        "quantification framework and software for management and automated analysis of "
        "real-time quantitative PCR data. Genome Biol. 2007;8(2):R19. doi:10.1186/gb-2007-8-2-r19"
    ),
    "ruijter2015": (
        "Ruijter JM, Ruiz Villalba A, Hellemans J, Untergasser A, van den Hoff MJB. Removal of "
        "between-run variation in a multi-plate qPCR experiment. Biomol Detect Quantif. "
        "2015;5:10–14. doi:10.1016/j.bdq.2015.07.001"
    ),
    "welch1947": (
        "Welch BL. The generalization of 'Student's' problem when several different population "
        "variances are involved. Biometrika. 1947;34(1–2):28–35."
    ),
    "holm1979": (
        "Holm S. A simple sequentially rejective multiple test procedure. Scand J Stat. "
        "1979;6(2):65–70."
    ),
    "dunnett1955": (
        "Dunnett CW. A multiple comparison procedure for comparing several treatments with a "
        "control. J Am Stat Assoc. 1955;50(272):1096–1121. doi:10.1080/01621459.1955.10501294"
    ),
    "tukey1953": (
        "Tukey JW. The problem of multiple comparisons. Unpublished manuscript, Princeton "
        "University; 1953. Kramer CY. Extension of multiple range tests to group means with "
        "unequal numbers of replications. Biometrics. 1956;12(3):307–310. doi:10.2307/3001469"
    ),
    "bh1995": (
        "Benjamini Y, Hochberg Y. Controlling the false discovery rate: a practical and powerful "
        "approach to multiple testing. J R Stat Soc B. 1995;57(1):289–300."
    ),
    "forootan2017": (
        "Forootan A, Sjöback R, Björkman J, Sjögreen B, Linz L, Kubista M. Methods to determine "
        "limit of detection and limit of quantification in quantitative real-time PCR (qPCR). "
        "Biomol Detect Quantif. 2017;12:1–6. doi:10.1016/j.bdq.2017.04.001"
    ),
    "miller2010": (
        "Miller JN, Miller JC. Statistics and Chemometrics for Analytical Chemistry. 6th ed. "
        "Harlow: Pearson; 2010 (section 5.6, inverse prediction from a calibration line)."
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
    return noun(n, one, many)


# ---- paragraphs ----------------------------------------------------------------------------------


def data(c: Ctx, cite: Cites) -> list[Part]:
    """The data: what was read, from which file."""
    r = c.result
    plates = c.count("n_plates", r.n_plates, "results.json:/n_plates")
    parts: list[Part] = []
    reactions = tok("f_n_reactions") if c.has("f_n_reactions") else None
    samples = tok("f_n_samples") if c.has("f_n_samples") else None
    lead = "Cq values" if c.has("f_cq_only") else "Raw fluorescence"  # no curves: Cq only
    if reactions:
        lead += f" of {reactions} reactions"
    lead += f" on {plates} {noun(r.n_plates, 'plate')}"
    if samples:
        lead += f" ({samples} samples)"
    parts.append(lead + (" were" if c.has("f_cq_only") else " was") + " read from ")
    name = input_label(c.inputs.source)  # the person's own file names, never qPilot's
    meta = c.inputs.rdml
    if name and is_converted(c.inputs.source):
        parts += ["the instrument export ", Q(name), ", converted to RDML by qPilot,"]
    elif name:
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
    if c.has("f_cq_only"):  # a file of Cq values only: no curve was fitted
        return _cq_values(c)
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


def _cq_values(c: Ctx) -> list[Part]:
    """The curve paragraph of a file of Cq values only (``docs/cq-tables.md``): no curve fitted."""
    parts: list[Part] = [
        "The file holds Cq values only (no amplification curves), so no curve was fitted and no "
        "well's own efficiency, baseline or fit quality exists: each well's Cq is the one in the "
        "file, as the instrument software set it, and its starting quantity is its assay's "
        "efficiency raised to the power of minus that Cq. Each assay's efficiency comes from "
        "its dilution series where the design has one (from the slope of Cq against the "
        "logarithm of the standards' quantities), and is otherwise assumed to be "
        f"{tok('f_eff_assumed_value')} (every cycle doubles the product, the ΔΔCq assumption).",
    ]
    words = sorted(fid for fid in c.result.facts if fid.startswith("f_eff_words_"))
    if words:
        parts.append(" " + " ".join(tok(fid) for fid in words))
    parts.append(" A well counts as amplified when the file gives it a Cq")
    if c.has("f_amp_primary"):
        parts.append(f"; the rule in use is {tok('f_amp_primary')}")
    parts.append(".")
    if c.has("f_n_undetermined", "f_n_unknown_wells", "f_pct_undetermined"):
        parts.append(
            f" Of {tok('f_n_unknown_wells')} sample wells, {tok('f_n_undetermined')} "
            f"({tok('f_pct_undetermined')}) had no Cq"
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
    parts += _normalisers(c, cite)
    parts += _between_plates(c, cite)
    return parts


def _normalisers(c: Ctx, cite: Cites) -> list[Part]:
    """NormFinder, geNorm's pair and the global mean, when a person asked to test them."""
    if not c.has("f_axis_normaliser"):
        return []
    parts: list[Part] = []
    if c.has("f_nf_best_pair", "f_nf_pair_stability"):
        parts += [
            " NormFinder ",
            cite("andersen2004"),
            f" ranked the same candidates with the groups; its best pair is "
            f"{tok('f_nf_best_pair')} (stability value {tok('f_nf_pair_stability')})",
        ]
        if c.has("f_nf_agreement"):
            parts.append(f". {tok('f_nf_agreement')}")
        else:
            parts.append(".")
    if c.has("f_gm_n_genes"):
        parts += [
            " The global mean ",
            cite("mestdagh2009"),
            f" (each of {tok('f_gm_n_genes')} genes weighted equally) was ",
        ]
        if c.has("f_axis_normaliser_unavailable_global_mean"):
            parts.append(
                f"not tested: qPilot offers it from {tok('f_gm_min_genes')} genes, its own "
                "default (the paper asks for a large number of genes and gives no minimum)."
            )
        else:
            parts.append("tested as another normaliser.")
    if c.has("f_n_flipped_normaliser", "f_n_genes"):
        parts.append(
            f" Changing only the normaliser changes {tok('f_n_flipped_normaliser')} of "
            f"{tok('f_n_genes')} calls; the reference genes in use were not changed by it."
        )
    elif c.has("f_screen_normaliser"):
        parts.append(" No other normaliser, tried alone, changes a call.")
    return parts


def _between_plates(c: Ctx, cite: Cites) -> list[Part]:
    """Inter-run calibration and factor correction, when a person asked to test them."""
    if not c.has("f_axis_interrun", "f_irc_n_split", "f_irc_n_runs"):
        return []
    parts: list[Part] = [
        f" Of the {tok('f_irc_n_runs')} plates, {tok('f_irc_n_split')} genes have their samples "
        "on more than one; inter-run calibration ",
        cite("hellemans2007"),
        " and factor correction ",
        cite("ruijter2015"),
        " were tested as corrections between plates",
    ]
    if c.has("f_n_flipped_interrun", "f_n_genes"):
        parts.append(
            f": correcting changes {tok('f_n_flipped_interrun')} of {tok('f_n_genes')} calls."
        )
    elif c.facts.value("f_axis_interrun") == "not_applicable":
        parts.append(", but neither can change a result in this study.")
    else:
        parts.append(": neither, tried alone, changes a call.")
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
    if c.quantify:  # no groups compared: the quantities paragraph and its choices say it all
        return []
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
    elif r.comparisons is not None and len(r.comparisons.comparisons) > 1:
        parts.append("The groups come from the confirmed design. ")
    else:
        parts += ["The groups come from the confirmed design: ", Q(a)]
        if hi:
            parts.append(f" ({hi} units)")
        parts += [" against ", Q(b)]
        if lo:
            parts.append(f" ({lo} units)")
        parts.append(". ")
    found = r.comparisons
    if found is not None:  # several comparisons, or a paired one (StudyDesign.comparisons)
        parts += _several(c, cite, found, alpha, fold)
        return parts
    parts += [
        "Technical replicates were averaged within each biological unit (mean log2 N0) and "
        "never counted as n. Each gene was compared between the groups with Welch's t-test ",
        cite("welch1947"),
        " on per-unit log2 normalised quantities; fold changes are reported with 95 % confidence "
        f"intervals. A gene is called up or down only if p < {alpha} and the change is at least "
        f"{fold}-fold; otherwise it has no call.",
    ]
    if c.has("f_n_genes") and c.facts.value("f_n_genes") != 1:
        parts.append(
            f" No correction for multiple testing was applied across the {tok('f_n_genes')} genes."
        )
    parts.append(
        f" At this analysis {c.call_count('up')} "
        f"{noun(c.calls.get('up', 0), 'gene is', 'genes are')} up, {c.call_count('down')} down "
        f"and {c.call_count('none')} {noun(c.calls.get('none', 0), 'has', 'have')} no call"
    )
    if c.has("f_n_withheld") and int(c.facts.value("f_n_withheld") or 0) > 0:
        parts.append(f"; {tok('f_n_withheld')} genes were withheld (too few values in a group)")
    parts.append(".")
    return parts


def _several(c: Ctx, cite: Cites, found, alpha: str, fold: str) -> list[Part]:  # noqa: ANN001
    """The test, the correction and each comparison's calls, for a study with a plan."""
    n = len(found.comparisons)
    parts: list[Part] = []
    if n > 1:
        parts.append(f"The study has {tok('f_n_comparisons')} comparisons: ")
        for i in range(1, n + 1):
            parts.append(
                f"{tok(f'f_cmp{i}_label')} ({tok(f'f_cmp{i}_n_a')} vs {tok(f'f_cmp{i}_n_b')})"
            )
            parts.append("; " if i < n else ". ")
        parts.append(f"The first, {tok('f_cmp1_label')}, is the one the choices describe. ")
    parts.append(
        "Technical replicates were averaged within each biological unit (mean log2 N0) and "
        "never counted as n. "
    )
    if found.pair_by is not None:
        parts += [
            f"Units were paired by {tok('f_cmp_pair_by')}: each comparison is a paired t-test on "
            "the within-pair differences of per-unit log2 normalised quantities (n = complete "
            "pairs); "
        ]
    elif found.correction in ("dunnett", "tukey"):
        parts.append(
            "Each comparison is a t-test on per-unit log2 normalised quantities with one "
            "variance per gene pooled over every compared group (equal variances assumed); "
        )
    else:
        parts += ["Each comparison is a Welch's t-test ", cite("welch1947")]
        parts.append(" on per-unit log2 normalised quantities; ")
    parts.append("fold changes are reported with 95 % confidence intervals for each comparison. ")
    if n > 1 and found.correction == "holm":
        parts += [
            "Each gene's p-values were corrected across its comparisons with Holm's step-down "
            "method ",
            cite("holm1979"),
            f"; a gene is called up or down in a comparison only if its corrected p < {alpha} "
            f"and the change is at least {fold}-fold; otherwise it has no call.",
        ]
    elif n > 1 and found.correction in ("dunnett", "tukey"):
        name, key, what = (
            ("Dunnett's", "dunnett1955", "each group against the control")
            if found.correction == "dunnett"
            else ("Tukey's (Tukey–Kramer)", "tukey1953", "every pair of groups")
        )
        parts += [
            f"Each gene's p-values were corrected with {name} single-step test for comparing "
            f"{what} ",
            cite(key),
            "; the multivariate probabilities were integrated numerically by fixed Gauss "
            f"quadrature. A gene is called up or down in a comparison only if its corrected p < "
            f"{alpha} and the change is at least {fold}-fold; otherwise it has no call.",
        ]
    else:
        if n > 1:
            parts.append("No correction for the several comparisons per gene was chosen; ")
        parts.append(
            f"a gene is called up or down only if p < {alpha} and the change is at least "
            f"{fold}-fold; otherwise it has no call."
        )
    parts += [
        " Benjamini–Hochberg q-values ",
        cite("bh1995"),
        " across the genes of each comparison are reported; they do not enter the calls.",
    ]
    if found.omnibus_groups:
        k = c.count("n_omnibus_groups", len(found.omnibus_groups), "comparisons.omnibus_groups@len")
        parts.append(
            f" Welch's one-way ANOVA across the {k} groups is reported "
            "per gene for orientation; it does not enter the calls."
        )
    for i in range(1, n + 1):
        if c.has(f"f_cmp{i}_label", f"f_cmp{i}_n_up", f"f_cmp{i}_n_down"):
            parts.append(
                f" {tok(f'f_cmp{i}_label')}: {tok(f'f_cmp{i}_n_up')} up and "
                f"{tok(f'f_cmp{i}_n_down')} down."
            )
    return parts


def quantity_choices(c: Ctx, cite: Cites) -> list[Part]:
    """A quantification study's choices: which wells count as detected, and the LOQ line."""
    if not c.quantify or not c.has("f_qn_items", "f_qn_fold"):
        return []
    rules = c.count("qn_rules", int(c.facts.value("f_n_rules")), "facts.json:/f_n_rules")
    parts: list[Part] = [
        f"Every sample result was quantified again under each of {rules} rules for which wells "
        "count as detected (LinRegPCR's own call, and Cq cut-offs) and under a stricter limit "
        "of quantification (a smaller read-back coefficient of variation); a choice waited for "
        "a person only when another option changed what is reported for a sample (its class, "
        f"or its number by more than {tok('f_qn_fold')})"
    ]
    for dim, words in (
        ("amp_call", "which wells count as detected"),
        ("loq_cv", "the limit of quantification"),
    ):
        fid = f"f_qn_changed_{dim}"
        if c.has(fid):
            parts.append(f"; {words} changed {tok(fid)} of {tok('f_qn_items')} sample results")
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
        "efficiency": ("efficiency model", "efficiency models"),
        "normaliser": ("normaliser", "normalisers"),
        "interrun": ("correction between plates", "corrections between plates"),
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
            f" {tok('f_n_hold_lt_80')} of {tok('f_n_genes')} "
            f"{noun(c.facts.value('f_n_genes'), 'gene keeps its', 'genes keep their')} call in "
            f"fewer than {holds} of them."
        )
    alone = [
        (fid, label)
        for fid, label in (
            ("f_n_flipped_refset", "the control genes"),
            ("f_n_flipped_cutoff", "the group cut-off"),
            ("f_n_flipped_amp_call", "the amplification-call rule"),
            ("f_n_flipped_undetermined", "the rule for wells without a quantity"),
            ("f_n_flipped_efficiency", "the efficiency model"),
            ("f_n_flipped_normaliser", "the normaliser"),
            ("f_n_flipped_interrun", "the correction between plates"),
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
    curves = (  # a file of Cq values only: no curve analysis, so no LinRegPCR
        "; no curve analysis (the file holds Cq values only), geNorm"
        if c.has("f_cq_only")
        else "; LinRegPCR from rdmlpython (MIT licence), geNorm"
    )
    text += (
        curves
        + " reimplemented from its paper and Welch's test from SciPy's t distribution"
        + (", NormFinder reimplemented from its paper" if c.has("f_nf_best_pair") else "")
    )
    if c.inputs.audit is not None:
        text += ", and the audit with qPilot's Decision Simulator"
    parts.append(
        text + ". The study's Analysis Record (the input file, every decision and their "
        "checksums) re-runs to the same numbers with qpilot rerun. Reported following MIQE 2.0 "
    )
    parts += [cite("miqe2"), "; the checklist is attached."]
    return parts


def study_quantities(c: Ctx) -> Any:
    """The study's absolute quantification (:mod:`qpilot.qpcr.absolute_study`), or None."""
    from qpilot.qpcr.absolute_study import QuantitiesUnavailable, for_study

    source = c.inputs.source
    if source is None:
        return None
    from qpilot.qpcr.quantify_study import analysis_in_use, is_quantify

    design = c.inputs.design
    choice = analysis_in_use(design, c.inputs.cards) if is_quantify(design) else None
    try:
        found = for_study(c.inputs.study_id, c.result.input_sha256, source, design, choice)
    except (QuantitiesUnavailable, OSError, ValueError):
        return None
    return found.result if found.result.curves else None


def quantities(c: Ctx, cite: Cites) -> list[Part]:
    """Absolute quantification: the standard curves, LOD/LOQ and the unknowns' intervals."""
    result = study_quantities(c)
    if result is None:
        return []
    fitted = [x for x in result.curves if x.fit is not None and x.scope == "plate"]
    if not fitted:
        return []
    path = "quantities:/curves"
    n = c.count("abs_n_curves", len(fitted), f"{path}@fitted")
    n_assays = c.count("abs_n_assays", len({x.target for x in fitted}), f"{path}@assays")
    effs = [x.fit.efficiency for x in fitted]
    r2s = [x.fit.r2 for x in fitted]
    lo = c.num("abs_eff_min", min(effs), f"{path}/efficiency@min", "{:.1%}")
    hi = c.num("abs_eff_max", max(effs), f"{path}/efficiency@max", "{:.1%}")
    r2 = c.num("abs_r2_min", min(r2s), f"{path}/r2@min", "{:.3f}")
    sources = {x.quantity_source for x in fitted}
    where = {
        "design": "as a person set them on the Design page",
        "file": "as the input file declares them",
        "name": "from the standards' names",
    }
    told = "; ".join(where.get(s, s.replace("+", " and ")) for s in sorted(sources))
    rate = c.num(
        "abs_lod_rate", result.settings.lod_rate, "quantities:/settings/lod_rate", "{:.0%}"
    )
    cv = c.num("abs_loq_cv", result.settings.loq_cv, "quantities:/settings/loq_cv", "{:.0%}")
    parts: list[Part] = [
        f"Absolute quantities were read from {n} standard curves ({n_assays} assays, one per "
        f"assay and plate; the standards' quantities {told}): Cq regressed on log10 quantity "
        "over the detected standard wells by ordinary least squares, efficiency "
        f"10^(−1/slope) − 1 from {lo} to {hi}, R² at least {r2}. Each unit's quantity is the "
        "inverse prediction from the mean Cq of its detected wells, with a 95 % prediction "
        "interval ",
        cite("miller2010"),
        f". The limit of detection is the lowest standard detected in at least {rate} of its "
        "wells, and the limit of quantification the lowest whose read-back quantities have a "
        f"log-normal coefficient of variation of at most {cv} ",
        cite("forootan2017"),
    ]
    units = result.unknowns
    if units:
        out = sum(1 for u in units if {"above_top", "below_lowest"} & set(u.flags))
        low = sum(1 for u in units if {"below_loq", "below_lod"} & set(u.flags))
        n_units = c.count("abs_n_units", len(units), "quantities:/unknowns@len", "{:,}")
        n_out = c.count("abs_n_extrapolated", out, "quantities:/unknowns@extrapolated", "{:,}")
        n_low = c.count("abs_n_below_limit", low, "quantities:/unknowns@below_limits", "{:,}")
        parts.append(
            f"; of {n_units} unit estimates, {n_out} lie outside the standards (extrapolated) and "
            f"{n_low} below the limit of quantification or detection, and are flagged as such"
        )
    parts.append(".")
    return parts


PARAGRAPHS = (
    ("data", "Data", data),
    ("curves", "Curve analysis", curves),
    ("quantities", "Absolute quantification", quantities),
    ("normalisation", "Reference genes and normalisation", normalisation),
    ("comparison", "Groups and comparison", comparison),
    ("robustness", "Robustness to analysis choices", robustness),
    ("quantity_choices", "Analysis choices for the quantities", quantity_choices),
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
