"""The MIQE 2.0 checklist: each item met, not met, not applicable, or not answerable from the data.

The item list is ``miqe2_items.yaml`` beside this module (its SHA-256 goes into the report). Each
item names a resolver here; a resolver reads the study (result, facts, confirmed design,
versions, the input file's RDML metadata, the audit) and returns a :class:`Fill` ("Yes" → met,
"No" → not met, with fact-bound evidence), a :class:`Hint` (cannot tell from the data, with what
the data do hold), :class:`NotApplicable`, or None (cannot tell). Items only a person can attest
(class ``d``) are never answered. The headline counts items by status: never a score,
never a claim that a study is compliant.

Ported from branch ``agents/report`` (resolvers reviewed by ``scientist``, bus #0052), re-pointed
at the live store; the status vocabulary is the page's.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from qpilot.report.context import Ctx
from qpilot.report.model import MiqeItem, MiqePack, MiqeStatus, MiqeView
from qpilot.report.text import Part, Q, tok

PACK = Path(__file__).with_name("miqe2_items.yaml")
STATUSES: tuple[MiqeStatus, ...] = ("met", "not_met", "not_applicable", "cannot_tell")
NO_FILE = "The input file is not available here, so what it declares cannot be read."
DEFAULT_HINT = {
    "a": "The data do not show this.",
    "b": "Instrument or quality-control exports hold this, not the RDML file; add it.",
    "c": "Not in the data: add it from the lab's notes (one line in the paper).",
    "d": "Only a person can attest this; qPilot never answers it.",
}


@dataclass
class Fill:
    """The data answer the item: "Yes" (met) or "No" (not met), with the evidence."""

    answer: str
    parts: list[Part]
    sources: list[str] = field(default_factory=list)


@dataclass
class Hint:
    """The data cannot tell; ``parts`` says what they do hold."""

    parts: list[Part]
    sources: list[str] = field(default_factory=list)


@dataclass
class NotApplicable:
    """The item does not apply to this study (the reason in words)."""

    parts: list[Part]


Outcome = Fill | Hint | NotApplicable | None


class MiqeCtx:
    """The report context plus what the MIQE items read (the file's metadata, the design)."""

    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx

    @property
    def rdml(self) -> Any:
        """The input file's RDML metadata, or None without the file."""
        return self.ctx.inputs.rdml

    def n(self, name: str, value: int, path: str) -> str:
        """A derived count token."""
        return self.ctx.count(name, value, path)

    @cached_property
    def samples(self) -> dict[str, dict[str, Any]]:
        """The confirmed design's samples (``{name: {role, quantity, …}}``)."""
        design = self.ctx.inputs.design
        if design is None:
            return {}
        return {k: v.model_dump(mode="json") for k, v in design.samples.items()}

    @cached_property
    def roles(self) -> dict[str, int]:
        """Samples per declared role in the confirmed design."""
        out: Counter[str] = Counter()
        for entry in self.samples.values():
            role = entry.get("role")
            if isinstance(role, str):
                out[role] += 1
        return dict(out)


# ---------- resolvers: the RDML file's metadata ----------


def _rdml_count(m: MiqeCtx, attr: str, what: str, name: str) -> Outcome:
    meta = m.rdml
    if meta is None:
        return Hint([NO_FILE])
    have = getattr(meta, attr)
    if not have:
        return Hint([f"The RDML file declares no {WHAT[attr]} for any target; add them."])
    path = f"input.rdml:/target/{what}@count"
    total = m.n("rdml_n_targets", meta.n_targets, "input.rdml:/target@len")
    return Fill(
        "Yes", [f"In the RDML file for {m.n(name, have, path)} of {total} targets."], [path]
    )


WHAT = {
    "n_targets_with_xref": "database cross-references",
    "n_targets_with_amplicon": "unmasked amplicon sequences",
}


def rdml_xref(m: MiqeCtx) -> Outcome:
    """1.2: database cross-references of the targets."""
    return _rdml_count(m, "n_targets_with_xref", "xRef", "rdml_n_xref")


def rdml_amplicon(m: MiqeCtx) -> Outcome:
    """1.4: amplicon sequences (unmasked) in the file."""
    return _rdml_count(m, "n_targets_with_amplicon", "sequences/amplicon", "rdml_n_amplicon")


def rdml_primers(m: MiqeCtx) -> Outcome:
    """1.5: primer/probe sequences or commercial assay ids (footnote c)."""
    meta = m.rdml
    if meta is None:
        return Hint([NO_FILE])
    if meta.n_targets_with_primers or meta.n_targets_with_assay:
        path = "input.rdml:/target/sequences@count"
        total = m.n("rdml_n_targets", meta.n_targets, "input.rdml:/target@len")
        seq = m.n("rdml_n_primers", meta.n_targets_with_primers, path)
        assay = m.n(
            "rdml_n_assays", meta.n_targets_with_assay, "input.rdml:/target/commercialAssay@count"
        )
        return Fill(
            "Yes",
            [
                f"Of {total} targets, {seq} have primer or probe sequences and {assay} a "
                "commercial assay id in the RDML file; for a commercial assay, MIQE asks for the "
                "assay context sequence."
            ],
            [path],
        )
    return Hint(["The RDML file holds no primer or probe sequences; give them in the paper."])


def rdml_tags(m: MiqeCtx) -> Outcome:
    """1.6: oligonucleotide modifications (tags)."""
    meta = m.rdml
    if meta is None or not meta.n_oligo_tags:
        return None
    path = "input.rdml:/target/sequences/tag@count"
    return Fill(
        "Yes", [f"{m.n('rdml_n_tags', meta.n_oligo_tags, path)} tags in the RDML file."], [path]
    )


def rdml_template(m: MiqeCtx) -> Outcome:
    """2.11 and 3.3: template quantities declared in the file."""
    meta = m.rdml
    if meta is None or not meta.n_template_quantities:
        return None
    path = "input.rdml:/sample/templateQuantity@count"
    n = m.n("rdml_n_template", meta.n_template_quantities, path)
    return Hint(
        [f"{n} samples declare a template quantity in the RDML file; please confirm."], [path]
    )


def rdml_dnase(m: MiqeCtx) -> Outcome:
    """2.12: DNase treatment as declared in the file."""
    meta = m.rdml
    if meta is None or not meta.dnase:
        return None
    words = "DNase-treated" if meta.dnase == [True] else "DNase treatment declared as mixed or no"
    return Hint([f"The RDML file declares the template {words}; please confirm."], ["input.rdml"])


def rdml_priming(m: MiqeCtx) -> Outcome:
    """3.1: cDNA priming method declared in the file (concentration needs the scientist)."""
    meta = m.rdml
    if meta is None or not meta.priming:
        return None
    return Hint(
        [
            "Priming declared in the RDML file: ",
            Q(", ".join(meta.priming)),
            "; the primer concentration is not.",
        ],
        ["input.rdml:/sample/cdnaSynthesisMethod/primingMethod"],
    )


def rdml_cycling(m: MiqeCtx) -> Outcome:
    """4.1: thermal-cycling programme in the file."""
    meta = m.rdml
    if meta is None or not meta.n_cycling_programmes:
        return None
    path = "input.rdml:/thermalCyclingConditions/step@count"
    steps = m.n("rdml_n_steps", meta.n_cycling_steps, path)
    return Hint(
        [f"The RDML file holds a cycling programme ({steps} steps); please confirm."], [path]
    )


def rdml_cycling_volume(m: MiqeCtx) -> Outcome:
    """4.5: cycling parameters and reaction volume."""
    meta = m.rdml
    if meta is None:
        return Hint([NO_FILE])
    have = []
    if meta.volumes:
        vol = m.ctx.facts.derive(
            "rdml_volume",
            ", ".join(f"{v:g}" for v in meta.volumes),
            "input.rdml:/react/vol@distinct",
            unit=" µL",
        )
        have.append(f"the reaction volume ({tok(vol)})")
    if meta.n_cycling_programmes:
        have.append("a cycling programme")
    if not have:
        return None
    return Hint(
        [f"The RDML file holds {' and '.join(have)}; the full cycling parameters are not in it."]
    )


def rdml_instrument(m: MiqeCtx) -> Outcome:
    """4.6: instrument named in the file."""
    meta = m.rdml
    if meta is None:
        return Hint([NO_FILE])
    if not meta.instruments:
        return Hint(["The RDML file names no instrument; give the manufacturer and model."])
    return Fill(
        "Yes",
        ["Instrument named in the RDML file: ", Q("; ".join(meta.instruments)), "."],
        ["input.rdml:/run/instrument"],
    )


# ---------- resolvers: the study and the engine ----------


def sample_counts(m: MiqeCtx) -> Outcome:
    """2.1: study samples, biological units per group, controls typed in the design."""
    c = m.ctx
    if not c.has("f_n_samples", "f_n_hi", "f_n_lo"):
        return None
    a, b = c.group_names
    parts: list[Part] = [
        f"{tok('f_n_samples')} samples; ",
        Q(a),
        f" {tok('f_n_hi')} and ",
        Q(b),
        f" {tok('f_n_lo')} biological units compared.",
    ]
    roles = {r: n for r, n in m.roles.items() if r != "unkn"}
    if roles:
        bits = [
            f"{m.n(f'role_{r}', n, f'study_design.json:/samples@count=role:{r}')} {r.upper()}"
            for r, n in sorted(roles.items())
        ]
        parts.append(" Controls and standards typed in the design: " + ", ".join(bits) + ".")
    return Fill("Yes", parts, ["results.json", "study_design.json:/samples"])


def nrt(m: MiqeCtx) -> Outcome:
    """3.5: copies with and without RT (footnote e: desirable, no longer essential)."""
    meta = m.rdml
    n_nrt = m.roles.get("nrt", 0) + (meta.sample_types.get("nrt", 0) if meta else 0)
    if n_nrt == 0 and (meta is not None or m.roles):
        return Fill(
            "No",
            [
                "The study has no no-RT control samples, in the design or the RDML file (MIQE "
                "2.0: desirable, no longer essential once the samples are shown to be free of DNA)."
            ],
            ["study_design.json:/samples", "input.rdml:/sample/type"],
        )
    if n_nrt:
        n = m.n("n_nrt", n_nrt, "study_design.json:/samples@count=role:nrt")
        return Hint(
            [f"{n} no-RT control samples are declared; their result is not evaluated here."]
        )
    return None


def raw_data(m: MiqeCtx) -> Outcome:
    """5.1: raw fluorescence in RDML."""
    meta = m.rdml
    if m.ctx.has("f_cq_only"):
        return Fill("No", [CQ_ONLY_WORDS["raw_data"]])
    if meta is None:
        return Hint(["The input file is not here; deposit the RDML file with the paper."])
    if not meta.n_reactions_with_curves:
        return Hint(["The RDML file holds no amplification curves."])
    curves = m.ctx.count(
        "rdml_n_curves",
        meta.n_reactions_with_curves,
        "input.rdml:/react/data/adp@count",
        fmt="{:,}",
    )
    sha = tok(
        m.ctx.facts.derive("input_sha256", m.ctx.result.input_sha256, "results.json:/input_sha256")
    )
    clause = m.ctx.reactions_in_file(meta.n_reactions_with_curves, meta.n_runs)
    where = f", {clause}" if clause else ""
    return Fill(
        "Yes",
        [
            f"Raw fluorescence of {curves} reactions in the RDML file (SHA-256 {sha}){where}; "
            "the Analysis Record carries the file byte for byte."
        ],
        ["input.rdml"],
    )


def quantification(m: MiqeCtx) -> Outcome:
    """5.2: quantification method (relative, from efficiency-corrected N0)."""
    if m.ctx.has("f_cq_only"):
        return Fill("Yes", [CQ_ONLY_WORDS["quantification"]], ["docs/cq-tables.md"])
    return Fill(
        "Yes",
        [
            "Relative quantification from efficiency-corrected starting quantities (LinRegPCR "
            "N0); standard curves are not used to quantify."
        ],
        ["methods/linregpcr.md"],
    )


def baseline_cq(m: MiqeCtx) -> Outcome:
    """5.3: baseline and Cq method."""
    if m.ctx.has("f_cq_only"):  # set by the instrument software, before the file was written
        return Hint([CQ_ONLY_WORDS["baseline_cq"]])
    commit = m.ctx.version("rdmlpython_vendored")
    text = (
        "Per-well baseline estimated and subtracted by LinRegPCR; Cq is TD0, the cycle where the "
        "third derivative of the curve crosses zero."
    )
    if commit:
        text += f" rdmlpython commit {commit}."
    return Fill("Yes", [text], ["versions", "methods/linregpcr.md"])


def software(m: MiqeCtx) -> Outcome:
    """5.4: analysis program and version."""
    qp, rp = m.ctx.version("qpilot"), m.ctx.version("rdmlpython_vendored")
    if qp is None:
        return None
    text = f"qPilot {qp}"
    if m.ctx.has("f_cq_only"):
        text += (
            " (no curve analysis: the file holds Cq values only, set by the instrument software)"
        )
    elif rp:
        text += f" with LinRegPCR from rdmlpython (commit {rp})"
    py = m.ctx.version("python")
    if py:
        text += f", Python {py}"
    return Fill("Yes", [text + "."], ["versions"])


def controls(m: MiqeCtx) -> Outcome:
    """5.5: which positive and negative controls the design types."""
    roles = {r: n for r, n in m.roles.items() if r != "unkn"}
    path = "study_design.json:/samples@count=role:"
    meta = m.rdml
    if not roles and meta is not None:
        roles = {r: n for r, n in meta.sample_types.items() if r != "unkn"}
        path = "input.rdml:/sample/type@count="
    if not roles:
        return None
    bits = [f"{m.n(f'ctl_{r}', n, path + r)} {r.upper()}" for r, n in sorted(roles.items())]
    return Fill(
        "Yes", ["Control and standard samples: " + ", ".join(bits) + "."], [path.split("@")[0]]
    )


def ntc_results(m: MiqeCtx) -> Outcome:
    """5.6: NTC frequency and Cq (the audit's observations, when there is one)."""
    audit = m.ctx.inputs.audit
    obs = ((audit.summary.get("troubleshooting") or {}).get("observations") or {}) if audit else {}
    if isinstance(obs.get("ntc"), int):
        n = m.ctx.audit_num(
            "ntc_observations", "summary.json", "troubleshooting", "observations", "ntc"
        )
        return Hint(
            [
                f"The audit lists {n} observations on no-template controls (see its issue queue); "
                "qPilot does not tabulate their frequency and Cq."
            ]
        )
    return Hint(
        ["qPilot does not tabulate how often the no-template controls amplified, or their Cq."]
    )


def examples(m: MiqeCtx) -> Outcome:
    """5.7: examples of positive and negative results (the curves are on the page)."""
    if m.ctx.has("f_cq_only"):
        return Hint([CQ_ONLY_WORDS["examples"]])
    return Hint(["Every well's raw curve is in the Curves section; choose examples for the paper."])


def efficiency(m: MiqeCtx) -> Outcome:
    """5.8: efficiency per well from the curve (LinRegPCR)."""
    c = m.ctx
    if c.has("f_cq_only"):
        return _cq_efficiency(m)
    eff = c.result.efficiency
    if not eff:
        return Fill("No", ["No efficiency in this study: quantities assume one (footnote j)."])
    lo = c.num("eff_min", min(eff.values()), "results.json:/efficiency@min")
    hi = c.num("eff_max", max(eff.values()), "results.json:/efficiency@max")
    text = (
        "Estimated per well from the log-linear phase of each curve (LinRegPCR); per-assay means "
        f"from {lo} to {hi}"
    )
    if c.has("f_eff_median"):
        text += f" (median {tok('f_eff_median')})"
    return Fill(
        "Yes", [text + ", as amplification factor per cycle."], ["results.json:/efficiency"]
    )


def quantity_method(m: MiqeCtx) -> Outcome:
    """5.9: efficiency-corrected target quantity (footnote j)."""
    if m.ctx.has("f_cq_only"):
        if m.ctx.has("f_n_eff_assumed") and m.ctx.result.facts["f_n_eff_assumed"].value:
            return Fill(
                "No",
                [
                    "Efficiency was assumed, not measured, for the assays without a dilution "
                    f"series: {tok('f_eff_assumed_genes')} (footnote j)."
                ],
                ["results.json:/facts/f_eff_assumed_genes"],
            )
        return Fill("Yes", [CQ_ONLY_WORDS["quantity_method"]], ["docs/cq-tables.md"])
    if not m.ctx.result.efficiency:
        return Fill("No", ["Efficiency was assumed, not measured (footnote j)."])
    return Fill(
        "Yes",
        [
            "Efficiency-corrected starting quantity per well (LinRegPCR N0, with the assay's "
            "mean efficiency)."
        ],
        ["methods/linregpcr.md"],
    )


def _cq_efficiency(m: MiqeCtx) -> Outcome:
    """5.8 for a file of Cq values only: each assay's dilution series, else assumed."""
    c = m.ctx
    facts = c.result.facts
    series = int(facts["f_n_eff_series"].value) if "f_n_eff_series" in facts else 0
    words = [tok(fid) for fid in sorted(facts) if fid.startswith("f_eff_words_")]
    head = (
        "No curve was available (the file holds Cq values only), so no well's own efficiency "
        "was estimated. "
    )
    if not series:
        return Fill(
            "No",
            [
                head + "No assay has a dilution series, so every assay's efficiency is assumed: "
                f"{tok('f_eff_assumed_value')}, every cycle doubling the product (footnote j)."
            ],
            ["results.json:/facts"],
        )
    answer = "Yes" if not int(facts["f_n_eff_assumed"].value) else "No"
    return Fill(
        answer,
        [head + "Each assay's efficiency is from its dilution series where it has one, else "
         "assumed: " + " ".join(words)],
        ["results.json:/facts", "docs/cq-tables.md"],
    )  # fmt: skip


def replicates(m: MiqeCtx) -> Outcome:
    """5.10: biological units vs technical replicates."""
    c = m.ctx
    if not c.has("f_n_hi", "f_n_lo"):
        return None
    return Fill(
        "Yes",
        [
            f"n is the number of biological units ({tok('f_n_hi')} and {tok('f_n_lo')}); "
            "technical replicates are averaged within a unit before any test and never counted "
            "as n."
        ],
        ["results.json", "methods/contrast.md"],
    )


LOD_RATE = 0.95  # qpilot.qpcr.absolute.LOD_RATE


def _curves(m: MiqeCtx) -> list[Any]:
    """The study's fitted per-plate standard curves (:mod:`qpilot.qpcr.absolute`), if any."""
    from qpilot.report.methods import study_quantities

    result = study_quantities(m.ctx)
    if result is None:
        return []
    return [c for c in result.curves if c.fit is not None and c.scope == "plate"]


def lod(m: MiqeCtx) -> Outcome:
    """5.13: the standards' LOD per assay (Forootan et al. 2017), when the study has curves.

    Met when at least one assay's dilution series reaches a level detected in fewer than 95 %
    of its wells (the LOD is then located); a series every level of which was detected bounds
    the LOD (at or below the lowest standard) without calculating it: not met, and said so.
    """
    curves = _curves(m)
    if not curves:
        return Fill(
            "No",
            [
                "Not determined by this analysis: it needs replicate detection rates at low input "
                "or a standard series evaluated for that purpose; change this answer if it was "
                "determined elsewhere."
            ],
            ["results.json:/confidence"],
        )
    located = [c for c in curves if c.lod.quantity is not None and not c.lod.at_most]
    path = "quantities:/curves"
    n = m.n("lod_n_curves", len(curves), f"{path}@fitted")
    if located:
        k = m.n("lod_n_located", len(located), f"{path}@lod_located")
        rate = m.ctx.num("lod_rate", LOD_RATE, "quantities:/settings/lod_rate", "{:.0%}")
        return Fill(
            "Yes",
            [
                f"For {k} of {n} standard curves the limit of detection was calculated as the "
                f"lowest standard detected in at least {rate} of its wells (Forootan et al.; a "
                "logistic fit is added where levels are partly detected); see the Standard "
                "curves table."
            ],
            ["methods/absolute_quantification.md"],
        )
    return Fill(
        "No",
        [
            f"Every level of all {n} standard curves was detected in every well, so the limit "
            "of detection is only known to be at or below the lowest standard; a series "
            "reaching non-detection is needed to calculate it."
        ],
        ["methods/absolute_quantification.md"],
    )


def dynamic_range(m: MiqeCtx) -> Outcome:
    """5.14: the linear range of the standard curves qPilot fitted (never called an LOQ)."""
    curves = _curves(m)
    if curves:
        path = "quantities:/curves"
        n = m.n("range_n_curves", len(curves), f"{path}@fitted")
        low = m.ctx.num("range_lowest", min(c.lowest for c in curves), f"{path}/lowest@min", "{:g}")
        top = m.ctx.num("range_top", max(c.top for c in curves), f"{path}/top@max", "{:g}")
        return Fill(
            "Yes",
            [
                f"{n} standard curves, the standards spanning {low} to {top} per reaction; each "
                "unknown outside its curve's standards is flagged as extrapolated (the Quantities "
                "table), and each curve's slope, R² and efficiency are in the Standard curves "
                "table."
            ],
            ["methods/absolute_quantification.md"],
        )
    with_quantity = [s for s in m.samples.values() if s.get("role") == "std" and s.get("quantity")]
    if with_quantity:
        n = m.n(
            "n_std_quantity",
            len(with_quantity),
            "study_design.json:/samples@count=role:std,quantity",
        )
        return Hint(
            [
                f"The design declares {n} standard samples with quantities, but no assay has a "
                "standard curve with at least three detected levels; give the linear range if "
                "one was evaluated."
            ]
        )
    source = (
        "the file holds Cq values only, and no assay has a dilution series"
        if m.ctx.has("f_cq_only")
        else "quantities come from each curve's own efficiency"
    )
    return Fill(
        "No",
        [
            f"No standard curve is evaluated ({source}); change this answer if the range was "
            "determined elsewhere."
        ],
    )


def refgene_validation(m: MiqeCtx) -> Outcome:
    """5.15: geNorm M and V, and the control-gene group-effect check."""
    c = m.ctx
    g = c.result.genorm
    if not g.M_initial:
        return None
    lo = c.num("m_min", min(g.M_initial.values()), "results.json:/genorm/M_initial@min")
    hi = c.num("m_max", max(g.M_initial.values()), "results.json:/genorm/M_initial@max")
    text = f"geNorm stability M from {lo} to {hi}"
    if c.has("f_genorm_v_min"):
        text += f"; lowest pairwise variation V {tok('f_genorm_v_min')}"
    text += "."
    if c.has("f_n_ref_pairs_flagged", "f_n_ref_pairs"):
        text += (
            f" Pairwise ratios between the groups: {tok('f_n_ref_pairs_flagged')} of "
            f"{tok('f_n_ref_pairs')} control-gene pairs shift."
        )
    return Fill("Yes", [text], ["results.json:/genorm", "methods/genorm.md"])


def normalisation(m: MiqeCtx) -> Outcome:
    """5.16: geometric mean of the reference genes."""
    c = m.ctx
    refs = list(c.result.design.refs_primary)
    if not refs:
        return None
    n = c.count("n_refs", len(refs), "results.json:/design/refs_primary@len")
    return Fill(
        "Yes",
        [
            f"Each target divided by the geometric mean of {n} reference genes (",
            Q(", ".join(refs)),
            "), on the log2 scale per biological unit.",
        ],
        ["results.json:/design/refs_primary"],
    )


def statistics(m: MiqeCtx) -> Outcome:
    """5.17: Welch's t-test on per-unit log2 quantities."""
    return Fill(
        "Yes",
        [
            "Welch's t-test on per-unit log2 normalised quantities; fold changes with 95 % "
            "confidence intervals; no correction for multiple testing; every call re-checked "
            "under qPilot's choice grid."
        ],
        ["methods/contrast.md"],
    )


def significance(m: MiqeCtx) -> Outcome:
    """5.18: significance level (from the rule); power is not in the data (scientist #0052)."""
    rule = m.ctx.result.conclusion_rule
    alpha = f"{rule.get('alpha', 0.05):g}"
    fold = f"{2 ** rule.get('min_log2fc', 1.0):g}"
    parts: list[Part] = [
        f"A gene is called only when p < {alpha} and the change is at least {fold}-fold. A priori "
        "power is not in the data; add it if it was calculated."
    ]
    return Fill("Yes", parts, ["results.json:/conclusion_rule"])


NO_MELT = (
    "The study's file has no melt curves, so qPilot could not check the products' melting "
    "temperatures; say how specificity was confirmed (melt curve, gel or sequencing)."
)


def _melt(m: MiqeCtx) -> tuple[Any, list[Any]] | None:
    """The study's melt curves and calls (``qpcr/melt.py``, the pack's G-MELT thresholds)."""
    from qpilot.qpcr import melt
    from qpilot.qpcr.gate_rules import melt_params, resolve_pack
    from qpilot.qpcr.study import StudySettings

    source = m.ctx.inputs.source
    if source is None:
        return None
    design = m.ctx.inputs.design
    settings = StudySettings.from_design(design) if design is not None else StudySettings()
    try:
        return melt.study_melt(source, settings, melt_params(resolve_pack()))
    except Exception:  # an unreadable file: the item cannot be told, said below
        return None


def specificity(m: MiqeCtx) -> Outcome:
    """5.19: the melt curves, analysed when the file has them (``qpcr/melt.py``, rule G-MELT)."""
    found = _melt(m)
    if found is None:
        return Hint([NO_FILE if m.ctx.inputs.source is None else NO_MELT])
    data, assays = found
    if not data.has_melt or not assays:
        return Hint([NO_MELT])
    path = "melt:/"
    wells = sum(len(a.with_melt) for a in assays)
    flagged = sum(1 for a in assays for w in a.wells if w.flagged)
    medians = [a.expected_tm for a in assays if a.expected_tm is not None]
    n_wells = m.n("melt_n_wells", wells, path + "wells@len")
    n_assays = m.n("melt_n_assays", len(assays), path + "assays@len")
    n_flagged = m.n("melt_n_flagged", flagged, path + "wells@flagged")
    parts: list[Part] = [
        f"qPilot analysed the melt curves of {n_wells} wells ({n_assays} assays on their "
        "plates): each well's -dF/dT peaks against its assay's product temperature."
    ]
    if medians:
        lo = m.ctx.num("melt_tm_lo", min(medians), path + "assays@tm_min", "{:.1f}", " °C")
        hi = m.ctx.num("melt_tm_hi", max(medians), path + "assays@tm_max", "{:.1f}", " °C")
        parts.append(f"The products melt between {lo} and {hi}.")
    parts.append(
        f"The Run Gate's rule G-MELT points at {n_flagged} wells (an extra peak, no product at "
        "the expected temperature, or a product in a no-template control)."
    )
    parts.append(
        "A single peak at the expected temperature does not guarantee that it is the intended "
        "amplicon (MIQE 2.0)."
    )
    return Fill("Yes", parts, ["methods/melt_curve.md", "packs/research-default.yaml#G-MELT"])


#: The MIQE items of a file of Cq values only (``docs/cq-tables.md``): what no curve leaves out.
CQ_ONLY_WORDS: dict[str, str] = {
    "raw_data": (
        "Not available: the file holds Cq values only, so no raw fluorescence (amplification "
        "curves) was available to qPilot. Deposit the instrument's raw export with the paper if "
        "it still exists."
    ),
    "quantification": (
        "Relative quantification from the file's Cq values (no curves): each well's starting "
        "quantity is its assay's efficiency raised to the power of minus its Cq, the assay's "
        "efficiency taken from its dilution series where the design has one, else assumed."
    ),
    "baseline_cq": (
        "Not available from this file: it holds Cq values only, so the baseline and the Cq were "
        "set by the instrument software before export. State that software, its baseline "
        "setting and its threshold (or Cq) method."
    ),
    "examples": (
        "Not available: the file holds Cq values only, so there are no curves to show; show "
        "examples from the instrument software. The Cq table is on the Curves page."
    ),
    "quantity_method": (
        "Efficiency-corrected: each well's quantity uses its assay's efficiency from the "
        "assay's dilution series (the file holds Cq values only)."
    ),
}


RESOLVERS: dict[str, Callable[[MiqeCtx], Outcome]] = {
    f.__name__: f
    for f in (
        rdml_xref,
        rdml_amplicon,
        rdml_primers,
        rdml_tags,
        rdml_template,
        rdml_dnase,
        rdml_priming,
        rdml_cycling,
        rdml_cycling_volume,
        rdml_instrument,
        sample_counts,
        nrt,
        raw_data,
        quantification,
        baseline_cq,
        software,
        controls,
        ntc_results,
        examples,
        efficiency,
        quantity_method,
        replicates,
        lod,
        dynamic_range,
        refgene_validation,
        normalisation,
        statistics,
        significance,
        specificity,
    )
}
#: Items whose pack entry has no resolver but that the data speak to.
EXTRA_FILL = {"5.7": "examples"}


def load_pack(path: Path = PACK) -> tuple[dict[str, Any], str]:
    """The item pack and its SHA-256."""
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def miqe(ctx: Ctx, pack_path: Path = PACK) -> MiqeView:
    """Answer every MIQE 2.0 item the data can, and count the items by status."""
    pack, digest = load_pack(pack_path)
    m = MiqeCtx(ctx)
    items = []
    for item in pack["items"]:
        cls = str(item.get("class"))
        name = item.get("fill") or EXTRA_FILL.get(item["id"])
        resolver = RESOLVERS.get(name or "")
        outcome = resolver(m) if resolver is not None and cls != "d" else None
        section = str(pack["sections"][item["id"].split(".")[0]])
        status: MiqeStatus = "cannot_tell"
        parts: list[Part] = [DEFAULT_HINT.get(cls, DEFAULT_HINT["a"])]
        sources: list[str] = []
        if isinstance(outcome, Fill):
            status = "met" if outcome.answer == "Yes" else "not_met"
            parts, sources = outcome.parts, outcome.sources
        elif isinstance(outcome, Hint):
            parts, sources = outcome.parts, outcome.sources
        elif isinstance(outcome, NotApplicable):
            status, parts = "not_applicable", outcome.parts
        items.append(
            MiqeItem(
                id=str(item["id"]),
                section=section,
                label=str(item["label"]),
                status=status,
                attest=cls == "d",
                evidence=ctx.t(*parts),
                sources=sources,
            )
        )
    counts = Counter(i.status for i in items)
    path = "report:/miqe/items@count=status:"
    tokens = {s: ctx.count(f"miqe_{s}", counts[s], path + s) for s in STATUSES}
    total = ctx.count("miqe_items", len(items), "report:/miqe/items@len")
    headline = ctx.t(
        f"Of the {total} MIQE 2.0 items, the data show {tokens['met']} met and "
        f"{tokens['not_met']} not met; {tokens['not_applicable']} do not apply and "
        f"{tokens['cannot_tell']} cannot be told from the data (the scientist answers them). A "
        "count, never a score: qPilot never answers an item only a person can attest."
    )
    return MiqeView(
        pack=MiqePack(
            name=str(pack.get("name")),
            version=str(pack.get("version")),
            sha256=digest,
            citation=" ".join(str(pack.get("citation", "")).split()),
        ),
        items=items,
        counts={s: counts[s] for s in STATUSES},
        n_items=len(items),
        headline=headline,
    )
